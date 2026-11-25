"""Self-test of the PL sweep path with the engine's own test ramp (no RF, no ADC, no ADF4351 needed).

With `DET_CFG.src = 1` the engine does not read a detector: the sample of result point i is
`(DET_TEST.base + (i & 0xFF)) & 0xFFFF`, so the sum of N_AVG samples is

    sum_i = N_AVG * ((base + (i & 0xFF)) & 0xFFFF)

Everything about the answer is known in advance, which makes it a pass/fail test of the whole software/hardware
path: table upload, start, N_AVG, per-point loop, result memory, counters, the flags, and the offload layer of
this package. `docs/selftest.md` has the specification and the criteria; `check_sweep` is where they live.

Run it ON THE BOARD (as root, no sweepd running; ~/sadiy/selftest.sh does both checks and the call):

    python3 -m sadiy_ebaz.ramp_test [--points 401 | --fill] [--n-avg 4] [--base 10000] [--sweeps 5] [--wrap]
    python3 -m sadiy_ebaz.ramp_test --model          # the same code against the PL model, on a PC

Exit code: 0 all checks passed | 1 a check failed | 2 the sweep core was not found / PL not ready.
The table has `points` measure-only entries (no SPI word, lock wait skipped), so the ADF4351 is not touched.
The pins and the I2C bus are handed to the engine for the run (the attenuator keeps the levels it was sent last) and given back at the end.
"""
from __future__ import annotations

import argparse
import sys
import time
from dataclasses import dataclass, field
from typing import Callable, List, Optional, Sequence

from .platform import OffloadResult, SweepOffload, TableEntry

DEFAULT_POINTS = 401
DEFAULT_N_AVG = 4
DEFAULT_BASE = 10000
DEFAULT_SWEEPS = 5
RAMP_PERIOD = 256                    # the index part of the ramp is 8 bits wide


def expected_sums(n_points: int, n_avg: int, base: int) -> List[int]:
    """The result sums the engine must return for the test ramp (rtl-spec: sample = base + (index & 0xFF), 16 bit)."""
    return [n_avg * ((base + (i & 0xFF)) & 0xFFFF) for i in range(n_points)]


def ramp_table(n_points: int) -> List[TableEntry]:
    """Measure-only entries: no SPI word, no attenuator change, no lock wait."""
    return [TableEntry(word=0, measure=True, skip_lock=True) for _ in range(n_points)]


@dataclass
class Check:
    name: str
    ok: bool
    detail: str = ""

    def line(self) -> str:
        text = f"{'PASS' if self.ok else 'FAIL'}  {self.name}"
        return f"{text}: {self.detail}" if self.detail and not self.ok else text


@dataclass
class Report:
    checks: List[Check] = field(default_factory=list)
    info: List[str] = field(default_factory=list)

    def check(self, name: str, ok: bool, detail: str = "") -> bool:
        self.checks.append(Check(name, bool(ok), detail))
        return bool(ok)

    @property
    def ok(self) -> bool:
        return bool(self.checks) and all(c.ok for c in self.checks)

    @property
    def failed(self) -> List[Check]:
        return [c for c in self.checks if not c.ok]

    def lines(self, verbose: bool = False) -> List[str]:
        """Report text. Checks of one sweep ("sweep 2: ...") are folded into one PASS line unless `verbose`;
        a failed check is always listed on its own."""
        out: List[str] = []
        groups: dict = {}
        for c in self.checks:
            head, sep, rest = c.name.partition(": ")
            groups.setdefault(head if sep else "", []).append(Check(rest if sep else c.name, c.ok, c.detail))
        for head, items in groups.items():
            bad = [c for c in items if not c.ok]
            if verbose or bad or not head:
                out += [f"{'PASS' if c.ok else 'FAIL'}  {head + ': ' if head else ''}{c.line()[6:]}" for c in items
                        if verbose or not c.ok or not head]
            if not bad and head and not verbose:
                out.append(f"PASS  {head}: {len(items)} checks")
        out += [f"info  {t}" for t in self.info]
        out.append(f"RESULT: {'PASS' if self.ok else 'FAIL'} ({len(self.checks) - len(self.failed)} of "
                   f"{len(self.checks)} checks passed)")
        return out


def diagnose(got: Sequence[int], want: Sequence[int], n_avg: int, base: int) -> str:
    """One line on what a wrong result looks like: where it starts to differ and a guess at the cause."""
    if len(got) != len(want):
        return f"{len(got)} results, want {len(want)}"
    bad = [i for i, (g, w) in enumerate(zip(got, want)) if g != w]
    if not bad:
        return ""
    first = bad[0]
    text = f"{len(bad)} of {len(want)} wrong, first at index {first}: got {got[first]}, want {want[first]}"
    if len(set(got)) == 1:
        return text + f"; every result is {got[0]} (generator stuck, or not the test source)"
    if len(got) >= 2 and not any(got):
        return text + "; all zero"
    if len(got) >= 3 and got[1] > got[0]:           # fit n' * (b' + i) on the first two points
        n2, b2 = got[1] - got[0], None
        if got[0] % n2 == 0:
            b2 = got[0] // n2
            if all(g == n2 * ((b2 + (i & 0xFF)) & 0xFFFF) for i, g in enumerate(got)) and (n2, b2) != (n_avg, base):
                return text + f"; fits N_AVG={n2}, DET_TEST.base={b2} (wrong register value reached the engine)"
    if bad == list(range(first, len(got))) or len(bad) == len(want) - first:
        return text + "; everything from there on differs (a skipped or repeated point shifts the rest)"
    return text


def check_sweep(rep: Report, tag: str, res: Optional[OffloadResult], status: dict, *, n_points: int, n_avg: int,
                base: int, sweep_count_before: Optional[int], previous: Optional[List[int]] = None,
                elapsed_s: Optional[float] = None, floor_s: Optional[float] = None, ceil_s: Optional[float] = None,
                read_s: Optional[float] = None, raw_words: Optional[Sequence[int]] = None, first_err_index: Optional[int] = None
                ) -> Optional[List[int]]:
    """The pass/fail criteria of one sweep of the ramp table. `res` is None when the run raised. Returns the sums
    when the sweep delivered a result."""
    if not rep.check(f"{tag}: sweep finished", res is not None):
        return None
    rep.check(f"{tag}: not aborted", not res.aborted)
    rep.check(f"{tag}: no table error", not res.err_table)
    rep.check(f"{tag}: no lock error flag (lock wait is skipped)", not res.err_lock and not any(res.unlocked),
              f"err_lock={res.err_lock}, unlocked points: {[i for i, u in enumerate(res.unlocked) if u][:8]}")
    rep.check(f"{tag}: STATUS clean (done, not busy, no err_lock/err_table/aborted)",
              bool(status.get("done")) and not status.get("busy") and not (status.get("err_lock") or status.get("err_table")
                                                                          or status.get("aborted")),
              str({k: status.get(k) for k in ("done", "busy", "err_lock", "err_table", "aborted", "state")}))
    rep.check(f"{tag}: engine idle (state 0, not waiting for samples)",
              not status.get("state") and not status.get("wait_sample"),
              f"state={status.get('state')}, wait_sample={status.get('wait_sample')}")
    rep.check(f"{tag}: engine owns the pins (pin_owner_act)", bool(status.get("pin_owner_act")))
    if first_err_index is not None:
        rep.check(f"{tag}: FIRST_ERR_INDEX = 0", first_err_index == 0, f"{first_err_index}")
    if raw_words is not None:
        stray = [i for i, w in enumerate(raw_words) if w >> 28]
        rep.check(f"{tag}: result bits 31:28 are 0 (unlocked / ovr / reserved)", not stray,
                  f"{len(stray)} words, first at index {stray[0] if stray else 0}: "
                  f"0x{raw_words[stray[0]] if stray else 0:08X}")
    rep.check(f"{tag}: result count = {n_points}", len(res.sums) == n_points, f"{len(res.sums)} results")
    rep.check(f"{tag}: POINT_COUNT = {n_points}", status.get("point_count") == n_points, f"{status.get('point_count')}")
    rep.check(f"{tag}: ENTRY_INDEX = {n_points}", status.get("entry_index") == n_points, f"{status.get('entry_index')}")
    if sweep_count_before is not None:
        rep.check(f"{tag}: SWEEP_COUNT went up by one", status.get("sweep_count") == sweep_count_before + 1,
                  f"{sweep_count_before} -> {status.get('sweep_count')}")
    rep.check(f"{tag}: n_avg reported = {n_avg}", res.n_avg == n_avg, f"{res.n_avg}")
    want = expected_sums(n_points, n_avg, base)
    rep.check(f"{tag}: every sum = N_AVG * ((base + (i & 0xFF)) & 0xFFFF)", list(res.sums) == want,
              diagnose(res.sums, want, n_avg, base))
    if previous is not None:
        rep.check(f"{tag}: identical to the previous sweep", list(res.sums) == previous)
    if elapsed_s is not None and floor_s:
        rep.check(f"{tag}: not faster than the hardware floor (T_MIN + T_SETTLE + N_AVG us per point)",
                  elapsed_s >= floor_s, f"{elapsed_s * 1e3:.2f} ms for {n_points} points, floor {floor_s * 1e3:.2f} ms")
    if elapsed_s is not None and ceil_s:
        rep.check(f"{tag}: not slower than the floor plus sequencer overhead and polling slack", elapsed_s <= ceil_s,
                  f"{elapsed_s * 1e3:.2f} ms for {n_points} points, limit {ceil_s * 1e3:.2f} ms")
    if elapsed_s is not None:
        rep.info.append(f"{tag}: {elapsed_s * 1e3:.1f} ms, {elapsed_s / max(1, n_points) * 1e6:.0f} us per point "
                        + ("(start to done, incl. up to 1 ms polling" if read_s is not None else "(incl. Python polling")
                        + (f"; reading the results {read_s * 1e3:.1f} ms)" if read_s is not None else ")"))
    return list(res.sums)


def sweep_bases(base: int, sweeps: int) -> List[int]:
    """DET_TEST.base of each checked sweep: all different, so every sweep must write new results (the result memory
    is not cleared by start, a stale copy of the last run would otherwise pass). With three or more sweeps the last
    one repeats the first base, which must reproduce sweep 1 exactly."""
    bases = [(base + k) & 0xFFFF for k in range(max(1, sweeps) - (1 if sweeps >= 3 else 0))]
    return bases + ([bases[0]] if sweeps >= 3 else [])


def run_selftest(offload: SweepOffload, *, n_points: int = DEFAULT_POINTS, n_avg: int = DEFAULT_N_AVG,
                 base: int = DEFAULT_BASE, sweeps: int = DEFAULT_SWEEPS, floor_s: Optional[float] = None,
                 ceil_s: Optional[float] = None, sweep_count: Optional[Callable[[], int]] = None,
                 raw_results: Optional[Callable[[int], Sequence[int]]] = None,
                 first_err_index: Optional[Callable[[], int]] = None,
                 set_base: Optional[Callable[[int], None]] = None,
                 pins_before: Optional[tuple] = None, pins_now: Optional[Callable[[], tuple]] = None, prefix: str = "",
                 clock: Callable[[], float] = time.monotonic, report: Optional[Report] = None) -> Report:
    """Upload the ramp table, run a poison sweep, then `sweeps` checked sweeps. `offload` must have been built with
    the test source (`det_src=SRC_TEST`). `set_base(b)` writes DET_TEST.base (idle only); without it every sweep
    uses `base`, which cannot tell fresh results from stale ones (the checks still run). `floor_s` is the shortest time
    a sweep can take (T_MIN_US + T_SETTLE_US + N_AVG us per point), `ceil_s` the longest that still passes.
    `sweep_count()`, `raw_results(n)` (the unmasked result words) and `first_err_index()` are optional register reads.
    Pin neutrality: `pins_before` = (attenuator levels ATT_STAT.levels, CE level) taken before the sweeps,
    `pins_now()` = the same while the engine sweeps; they must be equal after every sweep."""
    rep = report if report is not None else Report()
    try:
        offload.upload(ramp_table(n_points))
        rep.check(f"{prefix}table upload accepted", True)
    except (RuntimeError, ValueError) as exc:
        rep.check(f"{prefix}table upload accepted", False, str(exc))
        return rep
    bases = sweep_bases(base, sweeps) if set_base else [base] * sweeps
    if set_base:                                # poison: the memory then holds values no checked sweep expects
        set_base(base ^ 0x5555)
        try:
            offload.run(n_avg)
            rep.check(f"{prefix}poison sweep: finished", True)
        except (RuntimeError, TimeoutError) as exc:
            rep.check(f"{prefix}poison sweep: finished", False, f"{type(exc).__name__}: {exc}")
            offload.abort()
    first: Optional[List[int]] = None
    for k, bk in enumerate(bases, 1):
        if set_base:
            set_base(bk)
        before = sweep_count() if sweep_count is not None else None
        res: Optional[OffloadResult] = None
        t0 = clock()
        try:
            res = offload.run(n_avg)
        except (RuntimeError, TimeoutError) as exc:
            rep.check(f"{prefix}sweep {k}: sweep finished", False, f"{type(exc).__name__}: {exc}")
            offload.abort()
            continue
        dt = clock() - t0
        read_s = None
        sweep_s = getattr(offload, "last_sweep_s", 0.0)            # RegOffload: start to done, and the readout after it
        if isinstance(sweep_s, float) and sweep_s > 0.0 and isinstance(getattr(offload, "last_read_s", None), float):
            read_s = offload.last_read_s
            dt = sweep_s                                           # the hardware time, without the host's readout
            if floor_s and ceil_s:
                ceil_s = floor_s * 1.3 + 0.002                     # 30 % sequencer overhead plus the 1 ms poll
        tag = f"{prefix}sweep {k}"
        repeat = set_base is not None and sweeps >= 3 and k == len(bases)
        got = check_sweep(rep, tag, res, offload.status(), n_points=n_points, n_avg=n_avg, base=bk,
                          sweep_count_before=before, previous=first if repeat else None, elapsed_s=dt,
                          floor_s=floor_s, ceil_s=ceil_s, read_s=read_s, raw_words=raw_results(n_points) if raw_results else None,
                          first_err_index=first_err_index() if first_err_index else None)
        if pins_before is not None and pins_now is not None:
            now = pins_now()
            rep.check(f"{tag}: pins unchanged (attenuator levels the engine sent, CE)", now == pins_before,
                      f"before pe=0x{pins_before[0]:02X} ce={pins_before[1]}, now pe=0x{now[0]:02X} ce={now[1]}")
        if first is None:
            first = got
    return rep


# ---- on the registers of a core (board, model, or the core a running sweepd already has) ----------------------
KEEP = ("N_AVG", "DET_CFG", "DET_TEST", "T_MIN_US", "T_SETTLE_US")      # always restored
KEEP_ON_RELEASE = ("ADF_PINS", "PE4302")                               # restored only together with the pins


def is_simulated(off) -> bool:
    """True for the PL model (no real time passes in it: the time checks make no sense there)."""
    owner = getattr(getattr(off, "_rd", None), "__self__", None)
    return type(owner).__module__.endswith(("ebaz_pl_model", "platforms.fake_pl"))


def run_on_core(off, *, points: int = DEFAULT_POINTS, runs: Sequence[tuple] = ((DEFAULT_N_AVG, DEFAULT_BASE),),
                sweeps: int = DEFAULT_SWEEPS, fill: bool = False, t_min: int = 20, t_settle: int = 20,
                check_time: Optional[bool] = None, release: bool = False, report: Optional[Report] = None) -> Report:
    """The whole self-test on a `RegOffload`: `runs` is a list of (N_AVG, base). With `release=False` (a sweepd
    that is sweeping) the engine keeps the pins it has and PE4302 / ADF_PINS are not written back (that could move
    the pins); with `release=True` (the command line) the pins are given back, the engine reset and everything
    restored. N_AVG, DET_CFG, DET_TEST and the two waits are always put back. The caller must upload its own
    sweep table again afterwards (the ramp table replaced it)."""
    from . import regmap_toml
    from .reg_offload import SRC_TEST

    rep = report if report is not None else Report()
    regs = regmap_toml.REGS
    rd = lambda name: off._rd(regs[name].offset)  # noqa: E731
    wr = lambda name, v: off._wr(regs[name].offset, v)  # noqa: E731
    fld = lambda reg, name, v: regs[reg].fields[name].get(v)  # noqa: E731
    simulated = is_simulated(off)
    timed = (not simulated) if check_time is None else bool(check_time)
    saved = {n: rd(n) for n in KEEP + KEEP_ON_RELEASE}
    rep.info.append(f"register map {off.version >> 16}.{off.version & 0xFFFF}, {off.max_entries} table entries, "
                    f"{off.max_points} result points, clock {off.clk_hz / 1e6:.0f} MHz"
                    f"{' (PL model)' if simulated else ''}")
    if fill:
        points = min(off.max_entries, off.max_points)
    if not rep.check("table can hold the test", points <= off.max_points and points <= off.max_entries,
                     f"{points} points, core holds {min(off.max_points, off.max_entries)}"):
        return rep
    if points < 257:
        rep.info.append("fewer than 257 points: the 8-bit index wrap of the ramp is not exercised")
    try:
        # known waits, so that the time floor can tell "waits not applied" (the registers keep what was left there)
        wr("T_MIN_US", t_min)
        wr("T_SETTLE_US", t_settle)
        for n_avg, base in runs:
            if release:
                off.soft_reset()
            wr("DET_CFG", regs["DET_CFG"].fields["src"].put(SRC_TEST))
            wr("DET_TEST", base & 0xFFFF)
            cfg = rd("DET_CFG")
            rep.check("DET_CFG is video path (mode 0), test generator (src 1), stream 0",
                      fld("DET_CFG", "mode", cfg) == 0 and fld("DET_CFG", "src", cfg) == SRC_TEST
                      and fld("DET_CFG", "stream", cfg) == 0, f"DET_CFG = 0x{cfg:X}")
            rep.check("DET_TEST.base reads back", fld("DET_TEST", "base", rd("DET_TEST")) == base & 0xFFFF)
            # pin neutral: the ramp table has no attenuator entries, so the attenuator keeps the levels it has
            # (ATT_STAT.levels) and, set here, CE the level of the pad; `pins_now` proves both after every sweep
            pin_state = rd("PIN_STATE")
            before = (fld("ATT_STAT", "levels", rd("ATT_STAT")), fld("PIN_STATE", "ce", pin_state))
            if not fld("STATUS", "pin_owner_act", rd("STATUS")):     # an owning engine drives ADF_PINS.ce already: leave it
                wr("ADF_PINS", regs["ADF_PINS"].fields["ce"].put(before[1]))
            tmin, tsettle = rd("T_MIN_US") & 0xFFFFF, rd("T_SETTLE_US") & 0xFFFFF
            floor_s = points * (tmin + tsettle + n_avg) * 1e-6        # + 0.11 us per entry of sequencer overhead
            ceil_s = 2 * points * (tmin + tsettle + n_avg + 0.11) * 1e-6 + 0.05
            rep.info.append(f"run: N_AVG={n_avg}, DET_TEST.base={base} (0x{base:X}), {points} points x "
                            f"{sweeps} sweeps, T_MIN {tmin} us, T_SETTLE {tsettle} us, pins PE4302 "
                            f"0x{before[0]:02X} CE {before[1]}")

            def raw(n: int) -> List[int]:
                wr("RESULT_ADDR", 0)
                return [rd("RESULT_DATA") for _ in range(n)]

            def pins_now() -> tuple:
                return fld("ATT_STAT", "levels", rd("ATT_STAT")), fld("PIN_STATE", "ce", rd("PIN_STATE"))

            try:
                run_selftest(off, n_points=points, n_avg=n_avg, base=base, sweeps=sweeps,
                             floor_s=floor_s if timed else None, ceil_s=ceil_s if timed else None,
                             sweep_count=lambda: rd("SWEEP_COUNT") & 0xFFFFFFFF, raw_results=raw,
                             first_err_index=lambda: rd("FIRST_ERR_INDEX") & 0xFFFF,
                             set_base=lambda b: wr("DET_TEST", b & 0xFFFF),
                             pins_before=before, pins_now=pins_now, report=rep,
                             prefix=f"N_AVG {n_avg}, base 0x{base:X}, " if len(runs) > 1 else "")
            finally:
                off.abort()
    finally:
        names = KEEP
        if release:
            try:
                off.release_pins()
            finally:
                off.soft_reset()
            names = KEEP + KEEP_ON_RELEASE
        for n in names:                                  # leave the configuration as it was found
            wr(n, saved[n])
    return rep


# ---- command line (on the board, or against the model) ----------------------------------------------------------
def _model_offload():
    from .ebaz_pl_model import PlModel
    from .reg_offload import RegOffload

    model = PlModel()
    model.ld_now = True
    return RegOffload(model.read, model.write, poll_s=0.0)


def main(argv: Optional[Sequence[str]] = None) -> int:
    ap = argparse.ArgumentParser(description=__doc__.split("\n\n")[0])
    ap.add_argument("--points", type=int, default=DEFAULT_POINTS, help="measured points per sweep")
    ap.add_argument("--n-avg", type=int, default=DEFAULT_N_AVG, help="samples summed per point (N_AVG)")
    ap.add_argument("--base", type=lambda s: int(s, 0), default=DEFAULT_BASE, help="DET_TEST.base (0..0xFFFF)")
    ap.add_argument("--sweeps", type=int, default=DEFAULT_SWEEPS,
                    help="checked sweeps per run, each with another base (a poison sweep comes first; from 3 the last repeats the first)")
    ap.add_argument("--fill", action="store_true", help="use as many points as the table and result memory hold (4096)")
    ap.add_argument("--t-min", type=int, default=20, help="T_MIN_US during the test (restored afterwards)")
    ap.add_argument("--t-settle", type=int, default=20, help="T_SETTLE_US during the test (restored afterwards)")
    ap.add_argument("-v", "--verbose", action="store_true", help="list every check, not one line per sweep")
    ap.add_argument("--wrap", action="store_true", help="after the main run also run N_AVG 1, base 0xFFF0 (16-bit wrap)")
    ap.add_argument("--model", action="store_true", help="against the PL model, on a PC (no board)")
    ap.add_argument("--base-addr", type=lambda s: int(s, 0), default=None, help="register base address on the board")
    ap.add_argument("--fpga-state", default=None, help=argparse.SUPPRESS)
    args = ap.parse_args(argv)

    from .reg_offload import RegOffload

    regs = None
    try:
        if args.model:
            off = _model_offload()
        else:
            from .devmem import DEFAULT_BASE as DEVMEM_BASE, FPGA_STATE, DevMemRegs, pl_not_ready

            why = pl_not_ready(args.fpga_state or FPGA_STATE)
            if why:
                print(f"ramp_test: {why}: run ./fpga.sh first", file=sys.stderr)
                return 2
            try:
                regs = DevMemRegs(args.base_addr if args.base_addr is not None else DEVMEM_BASE)
                off = RegOffload(regs.read, regs.write)
            except (OSError, RuntimeError, ValueError) as exc:
                print(f"ramp_test: sweep core not usable: {exc}", file=sys.stderr)
                return 2
        runs = [(args.n_avg, args.base)] + ([(1, 0xFFF0)] if args.wrap else [])
        rep = run_on_core(off, points=args.points, runs=runs, sweeps=args.sweeps, fill=args.fill, t_min=args.t_min,
                          t_settle=args.t_settle, release=True)
    finally:
        if regs is not None:
            regs.close()
    print("\n".join(rep.lines(args.verbose)))
    return 0 if rep.ok else 1


if __name__ == "__main__":
    sys.exit(main())
