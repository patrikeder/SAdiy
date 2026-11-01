"""Sweep daemon: runs sweeps, publishes frames over ZeroMQ, accepts commands.

Run on a PC with the simulated chain:   python -m sadiy.server.sweepd --sim
It is a separate process from any UI, so plotting can never stall the SPI / GPIO timing.
"""
from __future__ import annotations

import argparse
import os
import time

from .. import config as config_mod
from ..core.cal import Cal
from ..core.detector import Detector
from ..core.freqplan import build_sweep
from ..core.sweep import SweepEngine, next_atten_db
from . import protocol

SETTABLE = ("start_hz", "stop_hz", "points", "atten_db", "auto_atten", "averages")


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
    return SweepEngine(
        SimSynth(chain),
        SimAtten(chain),
        SimAdc(chain),
        det,
        Cal(default_gain_db=cfg["cal"]["default_gain_db"]),
        averages=cfg["sweep"]["averages"],
        settle_s=0.0,
        sleep=lambda s: None,
    )


def build_hw_engine(cfg: dict) -> SweepEngine:
    raise NotImplementedError(
        "Hardware wiring is not implemented yet: needs Adf4351.registers() and the pin map "
        "from hw/wiring.md. Use --sim until then."
    )


class Sweepd:
    def __init__(self, cfg: dict, engine: SweepEngine) -> None:
        self.cfg = cfg
        self.engine = engine
        self.settings = {
            "start_hz": cfg["rf"]["rf_min_hz"],
            "stop_hz": cfg["rf"]["rf_max_hz"],
            "points": cfg["sweep"]["points"],
            "atten_db": 10.0,
            "auto_atten": True,
            "averages": cfg["sweep"]["averages"],
        }
        self.running = True
        self.seq = 0
        self._points = None
        self._key = None

    def apply(self, cmd: dict) -> dict:
        name = cmd.get("cmd")
        if name == "set":
            new = dict(self.settings)
            new.update({k: cmd[k] for k in SETTABLE if k in cmd})
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
            self.settings = new
            return {"ok": True, "settings": self.settings}
        if name == "run":
            self.running = True
            return {"ok": True}
        if name == "stop":
            self.running = False
            return {"ok": True}
        if name == "status":
            rf = self.cfg["rf"]
            return {
                "ok": True,
                "running": self.running,
                "seq": self.seq,
                "settings": self.settings,
                "limits": {"rf_min_hz": rf["rf_min_hz"], "rf_max_hz": rf["rf_max_hz"], "points_max": 4001},
            }
        return {"ok": False, "error": f"unknown command {name!r}"}

    def step(self):
        """Run one sweep and return the frame as a list of ZeroMQ parts."""
        st = self.settings
        key = (st["start_hz"], st["stop_hz"], int(st["points"]))
        if key != self._key:
            self._points = build_sweep(
                st["start_hz"],
                st["stop_hz"],
                int(st["points"]),
                self.cfg["rf"]["if_hz"],
                self.cfg["rf"]["injection"],
                self.cfg["synth"]["pfd_hz"],
            )
            self._key = key
        self.engine.averages = int(st["averages"])
        p_dbm = self.engine.run(self._points, st["atten_db"])
        used_atten = self.engine.last_atten_db
        if st["auto_atten"]:
            st["atten_db"] = next_atten_db(self.engine.last_peak_det_dbm, used_atten)
        step_hz = (st["stop_hz"] - st["start_hz"]) / (int(st["points"]) - 1)
        frame = protocol.encode_frame(self.seq, st["start_hz"], step_hz, used_atten, p_dbm)
        self.seq += 1
        return frame


def _try_realtime(priority: int = 10) -> None:
    try:
        os.sched_setscheduler(0, os.SCHED_FIFO, os.sched_param(priority))
    except (AttributeError, PermissionError, OSError):
        pass  # not fatal: run at normal priority


def main(argv=None) -> None:
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("--config", help="TOML file merged over config/default.toml")
    ap.add_argument("--sim", action="store_true", help="use the simulated RF chain")
    ap.add_argument("--rt", action="store_true", help="request SCHED_FIFO priority")
    ap.add_argument("--sweeps", type=int, default=0, help="stop after N sweeps (0 = run forever)")
    ap.add_argument(
        "--period", type=float, default=None,
        help="minimum seconds per sweep (default 0.1 with --sim, 0 on hardware)",
    )
    args = ap.parse_args(argv)
    period = args.period if args.period is not None else (0.1 if args.sim else 0.0)

    cfg = config_mod.load(args.config)
    engine = build_sim_engine(cfg) if args.sim else build_hw_engine(cfg)
    daemon = Sweepd(cfg, engine)
    if args.rt:
        _try_realtime()

    import zmq

    ctx = zmq.Context()
    pub = ctx.socket(zmq.PUB)
    pub.bind(cfg["server"]["pub"])
    rep = ctx.socket(zmq.REP)
    rep.bind(cfg["server"]["rep"])

    done = 0
    while args.sweeps == 0 or done < args.sweeps:
        try:
            while True:  # drain pending commands between sweeps
                cmd = rep.recv_json(flags=zmq.NOBLOCK)
                rep.send_json(daemon.apply(cmd))
        except zmq.Again:
            pass
        if daemon.running:
            t0 = time.monotonic()
            pub.send_multipart(daemon.step())
            done += 1
            spare = period - (time.monotonic() - t0)
            if spare > 0:
                time.sleep(spare)
        else:
            time.sleep(0.05)


if __name__ == "__main__":
    main()
