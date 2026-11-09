"""Sweep daemon: runs sweeps, publishes frames over ZeroMQ, accepts commands.

Run on a PC with the simulated chain:   python -m sadiy.server.sweepd --sim
It is a separate process from any UI, so plotting can never stall the SPI / GPIO timing.
"""
from __future__ import annotations

import argparse
import dataclasses
import json
import logging
import os
import signal
import sys
import time
from typing import Optional

from .. import config as config_mod
from .. import logs
from ..core.cal import Cal
from ..core.detector import Detector
from ..core.freqplan import build_opposite_sweep, build_sweep
from ..core.sweep import SweepEngine, next_atten_db
from . import protocol
from .bench import Bench, fake_backend, linux_backend

log = logging.getLogger("sadiy.server.sweepd")      # not __name__: that is __main__ under python -m

SETTABLE = ("start_hz", "stop_hz", "points", "atten_db", "auto_atten", "averages", "image_reject")


def build_sim_engine(cfg: dict) -> SweepEngine:
    from ..sim import SimAdc, SimAtten, SimChain, SimSynth

    det = Detector.from_config(cfg["detector"])
    sim = cfg.get("sim", {})                     # optional [sim] section, see config/default.toml
    chain = SimChain(
        det,
        tones=[(float(f), float(p)) for f, p in sim.get("tones", ((100e6, -30.0), (250e6, -45.0)))],
        if_hz=cfg["rf"]["if_hz"],
        rbw_hz=float(sim.get("rbw_hz", 230e3)),
        gain_db=cfg["cal"]["default_gain_db"],
        noise_dbm_in=float(sim.get("noise_dbm_in", -100.0)),
    )
    sw = cfg["sweep"]
    return SweepEngine(
        SimSynth(chain, sim.get("unlock_ranges_hz", ())),
        SimAtten(chain),
        SimAdc(chain),
        det,
        Cal(default_gain_db=cfg["cal"]["default_gain_db"]),
        averages=sw["averages"],
        settle_s=0.0,
        sleep=lambda s: None,
        combine_method=sw.get("combine", "median"),
        outlier_db=float(sw.get("outlier_db", 3.0)),
        lock_retries=int(sw.get("lock_retries", 2)),
    )


def build_hw_engine(cfg: dict) -> SweepEngine:
    raise NotImplementedError(
        "Hardware wiring is not implemented yet: needs Adf4351.registers() and the pin map "
        "(src/sadiy/pinmap.py, hw/wiring-bbb.md). Use --sim until then."
    )


class Sweepd:
    def __init__(self, cfg: dict, engine: Optional[SweepEngine], bench: Optional[Bench] = None,
                 ring: Optional[logs.RingLog] = None) -> None:
        self.cfg = cfg
        self.ring = ring            # what the `log` command serves; None: no records kept
        self.last_error = ""
        self.warn_every_s = 10.0    # a recurring sweep warning is repeated at most this often
        self._warned: dict = {}     # key -> [time of the last warning, sweeps since]
        self._lock_note = False
        self._announce = True       # the next sweep is logged at INFO (first after run or a settings change)
        self.engine = engine        # None: no sweep hardware yet, the daemon only offers bench mode
        self.bench = bench
        self.settings = {
            "start_hz": cfg["rf"]["rf_min_hz"],
            "stop_hz": cfg["rf"]["rf_max_hz"],
            "points": cfg["sweep"]["points"],
            "atten_db": 10.0,
            "auto_atten": True,
            "averages": cfg["sweep"]["averages"],
            "image_reject": bool(cfg["sweep"].get("image_reject", False)),
        }
        self.running = engine is not None
        self.seq = 0
        self._points = None
        self._key = None

    def handle_raw(self, raw: bytes) -> dict:
        """One command as received. Always returns a reply: a REQ client would wait for ever otherwise."""
        try:
            cmd = json.loads(raw)
        except ValueError:
            log.warning("command is not JSON, ignored")
            return {"ok": False, "error": "command is not JSON"}
        if not isinstance(cmd, dict):
            log.warning("command is not a JSON object, ignored")
            return {"ok": False, "error": "command must be a JSON object"}
        try:
            return self.apply(cmd)
        except Exception as exc:        # a bug must not leave the client waiting or kill the daemon
            log.error("command %r failed: %s", cmd.get("cmd"), exc, exc_info=True)
            self.last_error = f"command {cmd.get('cmd')!r} failed: {exc}"
            return {"ok": False, "error": self.last_error}

    def apply(self, cmd: dict) -> dict:
        reply = self._apply(cmd)
        if not reply.get("ok") and not (reply.get("needs_confirm") or reply.get("sweep_running")):
            if not str(cmd.get("cmd", "")).startswith(protocol.BENCH_PREFIX):   # bench logs its own
                log.warning("command %r refused: %s", cmd.get("cmd"), reply.get("error"))
        return reply

    def _apply(self, cmd: dict) -> dict:
        name = cmd.get("cmd")
        if isinstance(name, str) and name.startswith(protocol.BENCH_PREFIX):
            return self._bench_command(cmd)
        if name == "set":
            new = dict(self.settings)
            new.update({k: cmd[k] for k in SETTABLE if k in cmd})
            new["image_reject"] = bool(new["image_reject"])
            if not new["start_hz"] < new["stop_hz"]:
                return {"ok": False, "error": "start_hz must be below stop_hz"}
            if not 2 <= int(new["points"]) <= 4001:
                return {"ok": False, "error": "points must be 2..4001"}
            rf = self.cfg["rf"]    # outside this range the LO plan raises and would kill the daemon
            if new["start_hz"] < rf["rf_min_hz"] or new["stop_hz"] > rf["rf_max_hz"]:
                return {
                    "ok": False,
                    "error": f"range must be within {rf['rf_min_hz'] / 1e6:g}..{rf['rf_max_hz'] / 1e6:g} MHz",
                }
            changed = {k: v for k, v in new.items() if self.settings.get(k) != v}
            self.settings = new
            if changed:
                log.info("settings: %s", ", ".join(f"{k}={v:g}" if isinstance(v, float) else f"{k}={v}"
                                                   for k, v in changed.items()))
                if set(changed) & {"start_hz", "stop_hz", "points", "averages", "image_reject"}:
                    self._announce = True
            return {"ok": True, "settings": self.settings}
        if name == "run":
            if self.bench_active:
                return {"ok": False, "error": "bench mode is active: leave it before sweeping"}
            if self.engine is None:
                return {"ok": False, "error": "this sweepd has no sweep hardware (--bench-only)"}
            if not self.running:
                log.info("sweep started")
            self.running = True
            self._announce = True
            return {"ok": True}
        if name == "stop":
            if self.running:
                log.info("sweep stopped by a client")
            self.running = False
            return {"ok": True}
        if name == "log":
            if self.ring is None:
                return {"ok": True, "entries": [], "last_seq": 0, "boot": ""}
            try:
                entries = self.ring.entries(int(cmd.get("since", 0)), logs.parse_level(cmd.get("level", "debug")),
                                            int(cmd["limit"]) if cmd.get("limit") else None)
            except (ValueError, TypeError) as exc:
                return {"ok": False, "error": f"bad log request: {exc}"}
            return {"ok": True, "entries": [e.to_dict() for e in entries], "last_seq": self.ring.last_seq,
                    "boot": self.ring.boot}
        if name == "status":
            rf = self.cfg["rf"]
            return {
                "ok": True,
                "running": self.running,
                "seq": self.seq,
                "settings": self.settings,
                "bench": {"active": self.bench_active},
                "last_error": self.last_error,
                "last_sweep": dataclasses.asdict(self.engine.last_stats) if self.engine is not None else None,
                "log_seq": self.ring.last_seq if self.ring is not None else 0,
                "limits": {"rf_min_hz": rf["rf_min_hz"], "rf_max_hz": rf["rf_max_hz"], "points_max": 4001},
                "lo": {"if_hz": rf["if_hz"], "injection": rf["injection"], "pfd_hz": self.cfg["synth"]["pfd_hz"],
                       "mod_max": self.cfg["synth"]["mod_max"]},
                "synth": self.synth_readback(),
            }
        return {"ok": False, "error": f"unknown command {name!r}"}

    def synth_readback(self) -> Optional[dict]:
        """The ADF4351 for `status`: the bench's view of it while bench mode is open (words written, lock detect),
        else the LO of the last sweep point when the engine's synth can say. None when nothing knows."""
        if self.bench_active:
            return self.bench.synth_state()
        reader = getattr(self.engine.synth, "readback", None) if self.engine is not None else None
        return reader() if reader is not None and self.running else None

    @property
    def bench_active(self) -> bool:
        return self.bench is not None and self.bench.active

    def _bench_command(self, cmd: dict) -> dict:
        if self.bench is None:
            return {"ok": False, "error": "this sweepd has no bench backend"}
        if self.running and cmd["cmd"] != "bench_status":    # sweeping and bench mode are exclusive
            return {"ok": False, "sweep_running": True, "error": "a sweep is running: stop it first"}
        return self.bench.handle(cmd)

    def service_bench(self) -> bool:
        """Between commands: lease check and pattern steps. True when a pattern is running."""
        if self.bench is None:
            return False
        self.bench.tick()
        if self.bench.pattern_running:
            self.bench.service()
            return True
        return False

    def shutdown(self) -> None:
        if self.bench is not None:
            self.bench.close("sweepd is stopping")

    def step(self):
        """Run one sweep and return the frame as a list of ZeroMQ parts."""
        st = self.settings
        key = (st["start_hz"], st["stop_hz"], int(st["points"]), bool(st["image_reject"]))
        if key != self._key:
            rf = self.cfg["rf"]
            self._points = build_sweep(
                st["start_hz"],
                st["stop_hz"],
                int(st["points"]),
                rf["if_hz"],
                rf["injection"],
                self.cfg["synth"]["pfd_hz"],
            )
            self._other = None
            if st["image_reject"]:
                self._other, self._have_other = build_opposite_sweep(
                    self._points, rf["if_hz"], rf["injection"], self.cfg["synth"]["pfd_hz"])
                missing = int((~self._have_other).sum())
                if missing:
                    first = self._points[int(self._have_other.argmax())].f_rf_hz if self._have_other.any() else None
                    log.info("image rejection: %d of %d points have no opposite-side LO (ADF4351 or AD831 limit)%s; "
                             "they keep their image and are flagged", missing, len(self._points),
                             "" if first is None else f", suppression starts at {first / 1e6:.3f} MHz")
            self._key = key
        self.engine.averages = int(st["averages"])
        if st["image_reject"]:
            p_dbm = self.engine.run_rejecting(self._points, self._other, self._have_other, st["atten_db"])
        else:
            p_dbm = self.engine.run(self._points, st["atten_db"])
        used_atten = self.engine.last_atten_db
        if st["auto_atten"]:
            st["atten_db"] = next_atten_db(self.engine.last_peak_det_dbm, used_atten)
        step_hz = (st["stop_hz"] - st["start_hz"]) / (int(st["points"]) - 1)
        frame = protocol.encode_frame(self.seq, st["start_hz"], step_hz, used_atten, p_dbm, self.engine.last_flags,
                                       image_reject=bool(st["image_reject"]))
        self.seq += 1
        return frame

    def run_step(self):
        """`step()` as the main loop uses it: a failed sweep stops sweeping and is reported, the daemon
        stays up (so the GUI can read why, and bench mode still works). Returns the frame or None."""
        t0 = time.monotonic()
        try:
            frame = self.step()
        except Exception as exc:
            self.running = False
            self.last_error = f"sweep failed: {exc}"
            log.error("sweep failed, sweeping stopped: %s", exc, exc_info=True)
            for problem in self.engine.safe_state():
                log.warning("safe state after the failed sweep: %s", problem)
            return None
        dt = time.monotonic() - t0
        st = self.settings
        self._report(self.engine.last_stats, st)
        if self._announce:
            self._announce = False
            log.info("sweeping %.3f to %.3f MHz, %d points, %d averages%s: %.2f s per sweep, attenuation %.1f dB",
                     st["start_hz"] / 1e6, st["stop_hz"] / 1e6, int(st["points"]), int(st["averages"]),
                     ", image rejection on (two sweeps per trace)" if st["image_reject"] else "", dt,
                     self.engine.last_atten_db)
        else:
            log.log(logs.TRACE, "sweep %d: %.3f s, attenuation %.1f dB", self.seq - 1, dt, self.engine.last_atten_db)
        return frame


    def _report(self, stats, st: dict) -> None:
        """What the last sweep found out about itself, as log lines. A fault that lasts is reported when it
        starts and then every `warn_every_s`, with the number of sweeps in between, and again when it is gone."""
        if not stats.lock_checked and not self._lock_note:
            self._lock_note = True
            log.info("no lock detect available: points are not gated on PLL lock")
        problems = {}
        if stats.unlocked:
            problems["unlocked"] = (
                f"{stats.unlocked} of {stats.points} points read without PLL lock, the first at "
                f"{stats.first_unlocked_hz / 1e6:.3f} MHz; they are flagged")
        if stats.overrange:
            hint = "auto-ranging adds attenuation" if st["auto_atten"] else "raise the attenuation"
            problems["overload"] = (f"detector overload on {stats.overrange} of {stats.points} points ({hint}); "
                                    "they are flagged")
        now = time.monotonic()
        for key, text in problems.items():
            entry = self._warned.get(key)
            if entry is None or now - entry[0] >= self.warn_every_s:
                more = f" (also in {entry[1]} sweeps since the last report)" if entry and entry[1] else ""
                log.warning("%s%s", text, more)
                self._warned[key] = [now, 0]
            else:
                entry[1] += 1
        for key in [k for k in self._warned if k not in problems]:
            log.info("%s", {"unlocked": "PLL lock is back on every point", "overload": "no detector overload"}[key])
            del self._warned[key]
        if stats.outliers:
            log.debug("%d points had a rejected sample", stats.outliers)
        if stats.retunes:
            log.debug("%d points needed a second tune to lock", stats.retunes)


def _try_realtime(priority: int = 10) -> None:
    try:
        os.sched_setscheduler(0, os.SCHED_FIFO, os.sched_param(priority))
    except (AttributeError, PermissionError, OSError):
        pass  # not fatal: run at normal priority


def main(argv=None) -> None:
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("--config", help="TOML file merged over config/default.toml")
    ap.add_argument("--sim", action="store_true", help="use the simulated RF chain")
    ap.add_argument("--bench-only", action="store_true",
                    help="no sweeps, only bench mode (real SPI / GPIO / ADCs unless --sim); works before build_hw_engine exists")
    ap.add_argument("--rt", action="store_true", help="request SCHED_FIFO priority")
    ap.add_argument("--sweeps", type=int, default=0, help="stop after N sweeps (0 = run forever)")
    ap.add_argument(
        "--period", type=float, default=None,
        help="minimum seconds per sweep (default 0.1 with --sim, 0 on hardware)",
    )
    ap.add_argument("--log-level", choices=list(logs.LEVELS),
                    help="stderr verbosity, default from [log] level in the config (info). "
                         "trace logs every point and SPI word: for ssh only, it is never sent to the GUI")
    ap.add_argument("-v", "--verbose", action="count", default=0, help="-v is debug, -vv is trace")
    ap.add_argument("-q", "--quiet", action="count", default=0, help="-q is warning, -qq is error")
    args = ap.parse_args(argv)
    period = args.period if args.period is not None else (0.1 if args.sim else 0.0)

    cfg = config_mod.load(args.config)
    log_cfg = cfg.get("log", {})
    if args.log_level:
        level = logs.parse_level(args.log_level)
    else:
        level = logs.level_from_verbosity(args.verbose, args.quiet, str(log_cfg.get("level", "info")).lower())
    ring = logs.setup(level, ring=logs.RingLog(int(log_cfg.get("ring_lines", 500)),
                                               float(log_cfg.get("dedup_s", 5.0))))
    mode = "bench-only" if args.bench_only else "simulated chain" if args.sim else "hardware"
    log.info("sweepd starting: %s, log level %s", mode, logs.level_name(level))
    if args.bench_only:
        engine = None
    else:
        engine = build_sim_engine(cfg) if args.sim else build_hw_engine(cfg)
    bench = Bench(fake_backend() if args.sim else linux_backend(cfg), cfg)
    daemon = Sweepd(cfg, engine, bench, ring)
    if args.rt:
        _try_realtime()

    import zmq

    ctx = zmq.Context()
    pub = ctx.socket(zmq.PUB)
    pub.bind(cfg["server"]["pub"])
    rep = ctx.socket(zmq.REP)
    rep.bind(cfg["server"]["rep"])
    log.info("publishing on %s, commands on %s", cfg["server"]["pub"], cfg["server"]["rep"])

    def publish_log(entry) -> None:
        try:
            pub.send_multipart(protocol.encode_log(entry), flags=zmq.NOBLOCK)
        except zmq.ZMQError:
            pass                    # a full queue must never slow the sweep; the GUI backfills by `log`

    ring.add_listener(publish_log)

    signal.signal(signal.SIGTERM, lambda *_: sys.exit(0))   # so the finally below runs on systemctl stop
    done = 0
    try:
        while args.sweeps == 0 or done < args.sweeps:
            ring.flush()
            try:
                while True:  # drain pending commands between sweeps
                    raw = rep.recv(flags=zmq.NOBLOCK)
                    rep.send_json(daemon.handle_raw(raw))
            except zmq.Again:
                pass
            if daemon.service_bench():
                continue
            if daemon.running:
                t0 = time.monotonic()
                frame = daemon.run_step()
                if frame is None:
                    continue
                pub.send_multipart(frame)
                done += 1
                spare = period - (time.monotonic() - t0)
                if spare > 0:
                    time.sleep(spare)
            else:
                rep.poll(50)     # idle: wake at once for a command
    finally:
        log.info("sweepd stopping")
        daemon.shutdown()        # lines back to the safe state, whatever ended the loop


if __name__ == "__main__":
    main()
