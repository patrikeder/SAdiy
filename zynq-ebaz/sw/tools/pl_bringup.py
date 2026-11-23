#!/usr/bin/env python3
"""Bring-up test of the PL sweep engine on the board (register level), with hints for the logic analyzer.

Run ON THE EBAZ4205 after the bitstream is loaded (an AXI access to an unconfigured PL stalls the CPU):

    python3 pl_bringup.py                      # automatic stages: ident regs gen push owner ctrl lock adc if
    python3 pl_bringup.py ident gen            # chosen stages only
    python3 pl_bringup.py spi att              # stages for the logic analyzer (they ask before each capture)
    python3 pl_bringup.py --model              # same code against the PlModel on a PC (self test, no board)

Stages
  ident  ID / VERSION / CAPS                                   (stops the run when the core is not ours)
  regs   read / write back of the configuration registers, TABLE_ADDR, RESULT_ADDR
  gen    sweep with the test generator (no RF): results = N_AVG * (DET_TEST + index), counters, timing
  push   sweep fed by DET_PUSH (the path the ADS1115 uses), samples pushed while idle are dropped
  owner  pin owner switching, refused starts (owner and start in one write, N_ENTRIES = 0, too many)
  ctrl   abort while waiting for samples, soft_reset, irq_ack, interrupt count
  lock   lock wait: timeout flags when LD is low, no flags when LD is high, stop_on_err
  adc    ADS1115 reader of the PL (DET_CFG.src = 3): samples without software in the loop, I2C pin hand-over
  if     IF fast path with the sample generator: a pattern with two tones is loaded, the NCO sweeps across it,
         every result word is compared with the Python reference (bit-exact) and the peaks are checked
  ce     (not in auto) ADF4351 CE pin through ADF_PINS.ce: drives CE low for a moment
  spi    (LA)  ADF4351 SPI frames at several SPI_DIV values: CLK, DAT, LE
  att    (LA)  PE4302 make-before-break changes: V1..V6

Safety: the SPI words of these tests have control bits 111, which is no ADF4351 register, so a connected
ADF4351 should ignore them. Still unplug it or hold CE low for the first run. RF outputs are never enabled
here. The engine is given the pins at 31.5 dB (all stages in, the same level as the pull-ups) and the pins
go back to the PS at the end of every stage.

Exit code 0 when no check failed, 1 when a check failed, 2 when the core was not found.
Written by session R. The register names and fields come from regmap.toml (`sadiy_ebaz.regmap_toml`).
"""
from __future__ import annotations

import argparse
import os
import re
import sys
import time
from pathlib import Path
from typing import Callable, Dict, List, Optional, Sequence

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))   # zynq-ebaz/sw (or set PYTHONPATH on the board)

from sadiy_ebaz.platform import TableEntry  # noqa: E402
from sadiy_ebaz.regmap_toml import REGS  # noqa: E402

DEFAULT_BASE = 0x43C00000
ID_MAGIC = 0x53410001
SRC_PUSH, SRC_TEST = 0, 1
ALL_IN = 0x3F                                        # PE4302 levels V1..V6: every stage in (31.5 dB)
SAFE_WORDS = [0xA5A5A5A7, 0x5A5A5A5F, 0x00000007, 0xFFFFFFFF]   # control bits 111: no ADF4351 register
AUTO = ["ident", "regs", "gen", "push", "owner", "ctrl", "lock", "adc", "if", "fe"]
SRC_ADC = 3
LA_STAGES = ["spi", "att"]


# ------------------------------------------------------------------------------------------------ helpers
class Report:
    def __init__(self) -> None:
        self.passed = 0
        self.failed = 0
        self.skipped = 0

    def check(self, name: str, ok: bool, detail: str = "") -> bool:
        self.passed += bool(ok)
        self.failed += not ok
        print(f"  {'PASS' if ok else 'FAIL'}  {name}" + (f"   ({detail})" if detail else ""))
        return bool(ok)

    def info(self, text: str) -> None:
        print(f"  info  {text}")

    def la(self, text: str) -> None:
        print(f"  LA    {text}")

    def skip(self, text: str) -> None:
        self.skipped += 1
        print(f"  SKIP  {text}")


class Regs:
    """Register access by name; `rd` / `wr` are the 32-bit accessors of DevMemRegs or PlModel."""

    def __init__(self, rd: Callable[[int], int], wr: Callable[[int, int], None]) -> None:
        self._rd, self._wr = rd, wr

    def rd(self, name: str) -> int:
        return self._rd(REGS[name].offset)

    def wr(self, name: str, value: int) -> None:
        self._wr(REGS[name].offset, value & 0xFFFFFFFF)

    def get(self, reg: str, fld: str) -> int:
        return REGS[reg].fields[fld].get(self.rd(reg))

    def put(self, reg: str, fld: str, value: int) -> None:
        f = REGS[reg].fields[fld]
        self.wr(reg, (self.rd(reg) & ~f.mask) | f.put(value))

    def status(self) -> Dict[str, int]:
        word = self.rd("STATUS")
        return {n: f.get(word) for n, f in REGS["STATUS"].fields.items()}

    def ctrl(self, *, start: int = 0, abort: int = 0, soft_reset: int = 0, irq_ack: int = 0, **levels: int) -> None:
        """One CTRL write: the level bits keep their value unless given, the pulse bits are as given."""
        f = REGS["CTRL"].fields
        cur = self.rd("CTRL")
        v = 0
        for n in ("irq_en", "pin_owner", "stop_on_err"):
            v |= f[n].put(levels.get(n, f[n].get(cur)))
        for n, val in (("start", start), ("abort", abort), ("soft_reset", soft_reset), ("irq_ack", irq_ack)):
            v |= f[n].put(val)
        self.wr("CTRL", v)


class Ctx:
    def __init__(self, r: Regs, rep: Report, args: argparse.Namespace, model=None) -> None:
        self.r, self.rep, self.args, self.model = r, rep, args, model
        self.core_ok = False                    # set by the ident stage; nothing else writes before that

    @property
    def real(self) -> bool:
        return self.model is None

    # -- engine handling
    def reset(self) -> None:
        self.r.ctrl(soft_reset=1)

    def take_pins(self) -> bool:
        self.r.put("PE4302", "manual", ALL_IN)
        self.r.ctrl(pin_owner=1)
        return bool(self.r.status()["pin_owner_act"])

    def release_pins(self) -> None:
        self.r.ctrl(pin_owner=0)

    def upload(self, entries: Sequence[TableEntry]) -> bool:
        r = self.r
        r.wr("TABLE_ADDR", 0)
        for e in entries:
            r.wr("TABLE_W0", e.w0())
            r.wr("TABLE_W1", e.w1())
        r.wr("N_ENTRIES", len(entries))
        return r.rd("TABLE_ADDR") == len(entries)

    def wait_done(self, timeout: float = 5.0) -> bool:
        t0 = time.monotonic()
        while time.monotonic() - t0 < timeout:
            s = self.r.status()
            if s["done"] and not s["busy"]:
                return True
            time.sleep(0.0005)
        return False

    def sweep(self, entries: Sequence[TableEntry], timeout: float = 5.0):
        """Upload, start, wait. Returns (finished, seconds)."""
        if not self.upload(entries):
            return False, 0.0
        t0 = time.monotonic()
        self.r.ctrl(start=1)
        ok = self.wait_done(timeout)
        return ok, time.monotonic() - t0

    def results(self, n: int) -> List[int]:
        self.r.wr("RESULT_ADDR", 0)
        return [self.r.rd("RESULT_DATA") for _ in range(n)]

    def pause(self, text: str) -> None:
        print(f"  >>>   {text}")
        if not self.args.no_prompt and sys.stdin.isatty():
            input("        press Enter to continue ")


def points(n: int, words: Sequence[int], **flags) -> List[TableEntry]:
    return [TableEntry(word=words[i % len(words)], spi_en=True, measure=True, **flags) for i in range(n)]


class Saved:
    """Save registers, restore them on exit."""

    def __init__(self, r: Regs, names: Sequence[str]) -> None:
        self.r, self.names = r, list(names)

    def __enter__(self) -> "Saved":
        self.vals = {n: self.r.rd(n) for n in self.names}
        return self

    def __exit__(self, *exc) -> None:
        for n, v in self.vals.items():
            self.r.wr(n, v)


def irq_count() -> Optional[int]:
    """Sum of the interrupt counts of /proc/interrupts lines that look like the engine (uio / sadiy), or None."""
    try:
        text = Path("/proc/interrupts").read_text()
    except OSError:
        return None
    total, found = 0, False
    for line in text.splitlines():
        if re.search(r"uio|sadiy|sweep", line, re.I):
            found = True
            total += sum(int(x) for x in line.split(":", 1)[1].split() if x.isdigit())
    return total if found else None


# ------------------------------------------------------------------------------------------------ stages
def stage_ident(c: Ctx) -> None:
    r, rep = c.r, c.rep
    magic, version = r.rd("ID"), r.rd("VERSION")
    if not rep.check("ID = 0x53410001", magic == ID_MAGIC, f"read 0x{magic:08X}"):
        print("The core is not there (bitstream not loaded, wrong base address, or a stale one). Stopping.")
        raise SystemExit(2)
    c.core_ok = True
    rep.check("VERSION major = 1", version >> 16 == 1, f"read 0x{version:08X}")
    caps = r.rd("CAPS")
    clk, raw, taw = r.get("CAPS", "clk_mhz"), r.get("CAPS", "result_aw"), r.get("CAPS", "table_aw")
    rep.info(f"CAPS = 0x{caps:08X}: clk {clk} MHz, table 2^{taw} = {1 << taw} entries, results 2^{raw} = {1 << raw}")
    rep.check("fabric clock = 100 MHz (the microsecond timing assumes it)", clk == 100, f"{clk} MHz")
    st = r.status()
    rep.info("STATUS = " + ", ".join(f"{k}={v}" for k, v in st.items()))
    rep.info(f"PE4302 reg = 0x{r.rd('PE4302'):08X} (active_high={r.get('PE4302', 'active_high')}), "
             f"PIN_STATE = 0x{r.rd('PIN_STATE'):08X}")


def stage_regs(c: Ctx) -> None:
    r, rep = c.r, c.rep
    c.reset()
    names = ["N_ENTRIES", "N_AVG", "SPI_DIV", "T_ATT_GAP_CYC", "T_MIN_US", "T_LOCK_STABLE_US", "T_LOCK_TIMEOUT_US",
             "T_SETTLE_US", "DET_CFG", "DET_TEST"]
    with Saved(r, names):
        for n in names:
            mask = sum(f.mask for f in REGS[n].fields.values() if f.access == "rw")
            ok = True
            for pat in (0x2AAAAAAA, 0x15555555, 0):
                r.wr(n, pat & mask)
                got = r.rd(n)
                ok &= got == pat & mask
            rep.check(f"{n} writes read back (mask 0x{mask:X})", ok)
    r.wr("ID", 0)
    rep.check("ID is read-only", r.rd("ID") == ID_MAGIC)
    r.wr("TABLE_ADDR", 0)
    for _ in range(3):
        r.wr("TABLE_W0", 0)
        r.wr("TABLE_W1", 0)
    rep.check("TABLE_ADDR counts the TABLE_W1 writes", r.rd("TABLE_ADDR") == 3, f"{r.rd('TABLE_ADDR')}")
    r.wr("TABLE_ADDR", 0)
    rep.check("TABLE_ADDR can be set back", r.rd("TABLE_ADDR") == 0)
    r.wr("RESULT_ADDR", 5)
    rep.check("RESULT_ADDR write / read", r.rd("RESULT_ADDR") == 5)
    r.wr("RESULT_ADDR", 0)


def stage_gen(c: Ctx) -> None:
    r, rep = c.r, c.rep
    n_pts = c.args.points
    rep.info("SPI words go to the ADF4351 pins now (control bits 111); unplug it or hold CE low on the first run")
    c.reset()
    with Saved(r, ["N_AVG", "DET_CFG", "DET_TEST", "SPI_DIV"]):
        try:
            if not rep.check("engine takes the pins (pin_owner_act)", c.take_pins()):
                return
            r.put("DET_CFG", "src", SRC_TEST)
            for n_avg, base, sweep_no in ((4, 1000, 1), (1, 0xFFF0, 2)):
                r.wr("N_AVG", n_avg)
                r.wr("DET_TEST", base)
                ok, dt = c.sweep(points(n_pts, SAFE_WORDS, skip_lock=True))
                tag = f"sweep {sweep_no} (N_AVG={n_avg}, base=0x{base:X}, {n_pts} points)"
                if not rep.check(f"{tag}: finished", ok):
                    r.ctrl(abort=1)
                    continue
                s = r.status()
                rep.check(f"{tag}: no error flags", not (s["err_lock"] or s["err_table"] or s["aborted"]), str(s))
                rep.check(f"{tag}: POINT_COUNT = {n_pts}", r.rd("POINT_COUNT") == n_pts, f"{r.rd('POINT_COUNT')}")
                rep.check(f"{tag}: ENTRY_INDEX = {n_pts}", r.rd("ENTRY_INDEX") == n_pts)
                rep.check(f"{tag}: SWEEP_COUNT = {sweep_no}", r.rd("SWEEP_COUNT") == sweep_no, f"{r.rd('SWEEP_COUNT')}")
                got = c.results(n_pts)
                want = [n_avg * ((base + (i & 0xFF)) & 0xFFFF) for i in range(n_pts)]
                rep.check(f"{tag}: results = N_AVG * (DET_TEST + index)", got == want,
                          "" if got == want else f"got {got[:4]}.. want {want[:4]}..")
                if c.real:
                    per = r.rd("T_MIN_US") + r.rd("T_SETTLE_US")
                    floor = n_pts * per * 1e-6
                    rep.check(f"{tag}: not faster than T_MIN + T_SETTLE", dt >= 0.9 * floor,
                              f"{dt * 1e3:.2f} ms for {n_pts} points, waits alone {floor * 1e3:.2f} ms")
                    rep.info(f"{tag}: {dt / n_pts * 1e6:.0f} us per point incl. Python polling (waits: {per} us)")
        finally:
            c.release_pins()
            c.reset()
    rep.la("CLK / DAT / LE: one 32-bit frame per point, words " + ", ".join(f"0x{w:08X}" for w in SAFE_WORDS))


def stage_push(c: Ctx) -> None:
    r, rep = c.r, c.rep
    k, n_avg, n_pts = 1234, 3, 3
    c.reset()
    with Saved(r, ["N_AVG", "DET_CFG"]):
        try:
            if not rep.check("engine takes the pins", c.take_pins()):
                return
            r.put("DET_CFG", "src", SRC_PUSH)
            r.wr("N_AVG", n_avg)
            for _ in range(5):
                r.wr("DET_PUSH", 0xFFFF)                     # idle: these must be dropped
            if not c.upload(points(n_pts, SAFE_WORDS, skip_lock=True)):
                rep.check("table upload", False)
                return
            r.ctrl(start=1)
            t0, pushed = time.monotonic(), 0
            while time.monotonic() - t0 < 5.0:
                s = r.status()
                if s["done"] and not s["busy"]:
                    break
                if s["wait_sample"]:
                    r.wr("DET_PUSH", k)
                    pushed += 1
            ok = r.status()["done"]
            rep.check("sweep finished with PS-pushed samples", ok)
            if not ok:
                r.ctrl(abort=1)
                return
            got = c.results(n_pts)
            rep.check(f"every sum = N_AVG * {k} (idle pushes were dropped)", got == [n_avg * k] * n_pts,
                      f"got {got}")
            rep.info(f"{pushed} pushes for {n_pts * n_avg} counted samples (the rest arrived outside SAMPLE or in the "
                     "same SAMPLE as the last one and were dropped)")
        finally:
            c.release_pins()
            c.reset()


def stage_owner(c: Ctx) -> None:
    r, rep = c.r, c.rep
    c.reset()
    rep.la("capture pe4302_v[5:0], clk, dat, le during this stage: no glitch may appear at any owner change")
    with Saved(r, ["N_ENTRIES"]):
        try:
            c.release_pins()
            rep.check("owner = PS: pin_owner_act = 0", r.status()["pin_owner_act"] == 0)
            ps = r.rd("PIN_STATE")
            rep.info(f"PS owns the pins: pe_t = 0x{r.get('PIN_STATE', 'pe_t'):02X} (0x3F = Linux has not driven them), "
                     f"pe_in = 0x{r.get('PIN_STATE', 'pe_in'):02X}, le/clk/dat = "
                     f"{r.get('PIN_STATE', 'le')}/{r.get('PIN_STATE', 'clk')}/{r.get('PIN_STATE', 'dat')}")
            _ = ps
            rep.check("owner = engine: pin_owner_act = 1", c.take_pins())
            rep.check("engine pins at ALL IN (31.5 dB)", r.get("PIN_STATE", "pe_out") == ALL_IN,
                      f"pe_out = 0x{r.get('PIN_STATE', 'pe_out'):02X}")
            rep.check("engine drives LE high, CLK low when idle", (r.get("PIN_STATE", "le"), r.get("PIN_STATE", "clk")) == (1, 0),
                      f"le={r.get('PIN_STATE', 'le')} clk={r.get('PIN_STATE', 'clk')}")
            c.release_pins()
            rep.check("back to PS: pin_owner_act = 0", r.status()["pin_owner_act"] == 0)

            # pin_owner and start in one write: the pins are taken, the start is refused
            c.reset()
            c.upload([TableEntry(word=SAFE_WORDS[0], spi_en=True)])
            r.ctrl(pin_owner=1, start=1)
            time.sleep(0.01)
            s = r.status()
            rep.check("pin_owner + start in one write: start refused (err_table, done, not busy)",
                      bool(s["err_table"] and s["done"] and not s["busy"]), str(s))
            rep.check("... and the pins were taken", s["pin_owner_act"] == 1)
            c.reset()
            c.release_pins()

            # N_ENTRIES = 0 and too many, with the engine owning the pins
            c.take_pins()
            for label, n in (("N_ENTRIES = 0", 0), ("N_ENTRIES = depth + 1", (1 << r.get("CAPS", "table_aw")) + 1)):
                c.reset()
                r.wr("N_ENTRIES", n)
                r.ctrl(start=1)
                time.sleep(0.01)
                s = r.status()
                rep.check(f"{label}: start refused (err_table, done, not busy)",
                          bool(s["err_table"] and s["done"] and not s["busy"]), str(s))
        finally:
            c.reset()
            c.release_pins()


def stage_ctrl(c: Ctx) -> None:
    r, rep = c.r, c.rep
    c.reset()
    with Saved(r, ["N_AVG", "DET_CFG", "N_ENTRIES"]):
        try:
            c.take_pins()
            # abort: with source PUSH and no pushes the sweep waits in SAMPLE
            r.put("DET_CFG", "src", SRC_PUSH)
            r.wr("N_AVG", 1)
            c.upload(points(1, SAFE_WORDS, skip_lock=True))
            r.ctrl(start=1)
            t0, waiting = time.monotonic(), False
            while time.monotonic() - t0 < 3.0:
                if r.status()["wait_sample"]:
                    waiting = True
                    break
            rep.check("sweep waits for samples (busy, wait_sample)", waiting and r.status()["busy"] == 1)
            r.ctrl(abort=1)
            c.wait_done(2.0)
            s = r.status()
            rep.check("abort: done, aborted, not busy, IDLE", bool(s["done"] and s["aborted"] and not s["busy"] and s["state"] == 0),
                      str(s))
            rep.check("abort: no result stored, SWEEP_COUNT not incremented",
                      r.rd("POINT_COUNT") == 0 and r.rd("SWEEP_COUNT") == 0)
            c.reset()
            s = r.status()
            rep.check("soft_reset clears done / aborted / err flags", not (s["done"] or s["aborted"] or s["err_lock"] or s["err_table"]), str(s))

            # irq_ack and the interrupt
            r.put("DET_CFG", "src", SRC_TEST)
            before = irq_count() if c.real else None
            r.ctrl(irq_en=1)
            ok, _ = c.sweep(points(2, SAFE_WORDS, skip_lock=True))
            rep.check("sweep with irq_en finished", ok)
            if before is not None:
                time.sleep(0.05)
                after = irq_count()
                rep.check("interrupt count of the engine increased", after is not None and after > before,
                          f"{before} -> {after}")
            else:
                rep.skip("interrupt count: no uio / sadiy line in /proc/interrupts (overlay loaded?) or running on the model")
            r.ctrl(irq_ack=1)
            rep.check("irq_ack clears done", r.status()["done"] == 0)
            r.ctrl(irq_en=0)
        finally:
            c.release_pins()
            c.reset()


def stage_lock(c: Ctx) -> None:
    r, rep = c.r, c.rep
    c.reset()
    names = ["N_AVG", "DET_CFG", "T_MIN_US", "T_LOCK_STABLE_US", "T_LOCK_TIMEOUT_US", "T_SETTLE_US"]
    with Saved(r, names):
        try:
            if not rep.check("engine takes the pins", c.take_pins()):
                return
            r.put("DET_CFG", "src", SRC_TEST)
            r.wr("N_AVG", 1)
            r.wr("T_MIN_US", 20)
            r.wr("T_LOCK_STABLE_US", 50)
            r.wr("T_LOCK_TIMEOUT_US", 2000)
            r.wr("T_SETTLE_US", 20)
            ld = r.status()["ld_now"]
            rep.info(f"lock detect reads {ld} (STATUS.ld_now, PIN_STATE.ld = {r.get('PIN_STATE', 'ld')})")
            rep.la("LD, LE, CLK, DAT: one frame per point, then LD must stay high 50 us (or time out after 2 ms)")
            entries = points(2, SAFE_WORDS)                       # no skip_lock: waits for LD
            if not ld:
                ok, dt = c.sweep(entries)
                rep.check("LD low: sweep finishes after the timeouts", ok)
                s = r.status()
                rep.check("LD low: err_lock set", bool(s["err_lock"]), str(s))
                rep.check("LD low: FIRST_ERR_INDEX = 0, 2 points stored", r.rd("FIRST_ERR_INDEX") == 0 and r.rd("POINT_COUNT") == 2)
                res = c.results(2)
                rep.check("LD low: both results flagged unlocked (bit 31)", all(w >> 31 for w in res),
                          ", ".join(f"0x{w:08X}" for w in res))
                if c.real:
                    rep.check("LD low: took at least 2 x the timeout", dt >= 0.9 * 2 * 2e-3, f"{dt * 1e3:.2f} ms")
                r.ctrl(stop_on_err=1)
                ok, _ = c.sweep(entries)
                s = r.status()
                rep.check("stop_on_err: sweep ends at the first timeout (done, err_lock, nothing stored)",
                          bool(ok and s["err_lock"] and r.rd("POINT_COUNT") == 0 and r.rd("ENTRY_INDEX") == 0), str(s))
                r.ctrl(stop_on_err=0)
            else:
                ok, dt = c.sweep(entries)
                rep.check("LD high: sweep finished", ok)
                s = r.status()
                rep.check("LD high: no err_lock, 2 points", not s["err_lock"] and r.rd("POINT_COUNT") == 2, str(s))
                res = c.results(2)
                rep.check("LD high: no result flagged unlocked", not any(w >> 31 for w in res))
                if c.real:
                    rep.info(f"LD high: {dt / 2 * 1e6:.0f} us per point (waits 20 + 50 + 20 us, plus Python polling)")
                rep.info("to test the timeout path, make LD low (ADF4351 CE low or unplugged) and run this stage again")
        finally:
            c.release_pins()
            c.reset()


def stage_adc(c: Ctx) -> None:
    r, rep = c.r, c.rep
    if r.rd("VERSION") & 0xFFFF < 1 or "ADC_CFG" not in REGS:
        rep.skip("this bitstream has no ADS1115 reader (register map 1.0)")
        return
    n_avg, n_pts = 4, 2
    c.reset()
    with Saved(r, ["N_AVG", "DET_CFG", "T_MIN_US", "T_SETTLE_US"]):
        try:
            cfgw, addr = r.get("ADC_CFG", "config"), r.get("ADC_CFG", "addr")
            div, t_conv = max(4, r.rd("ADC_I2C_DIV")), r.rd("ADC_T_CONV_US")
            rep.info(f"ADC_CFG: config 0x{cfgw:04X}, address 0x{addr:02X}; I2C {100e3 / (4 * div):.0f} kHz; "
                     f"conversion wait {t_conv} us")
            rep.check("config word is single shot with OS set", bool(cfgw & 0x8000 and cfgw & 0x0100), f"0x{cfgw:04X}")
            rep.check("PS owns the I2C pins before (PIN_STATE.i2c_pl = 0)", r.get("PIN_STATE", "i2c_pl") == 0)
            rep.check("bus idle: SCL and SDA high", (r.get("PIN_STATE", "scl"), r.get("PIN_STATE", "sda")) == (1, 1),
                      f"scl={r.get('PIN_STATE', 'scl')} sda={r.get('PIN_STATE', 'sda')} (pull-ups? ADC powered?)")
            r.put("DET_CFG", "src", SRC_ADC)
            if not rep.check("engine takes the pins", c.take_pins()):
                return
            rep.check("the reader owns the I2C pins now (PIN_STATE.i2c_pl = 1)", r.get("PIN_STATE", "i2c_pl") == 1)
            r.wr("N_AVG", n_avg)
            r.wr("T_MIN_US", 10)
            r.wr("T_SETTLE_US", 10)
            count0 = r.get("ADC_STAT", "count")
            rep.la(f"i2c_scl / i2c_sda: per sample S {addr:02X}+W 01 {cfgw >> 8:02X} {cfgw & 0xFF:02X} P, {t_conv} us, "
                   f"S {addr:02X}+W 00 P, S {addr:02X}+R hi lo P")
            ok, dt = c.sweep([TableEntry(word=0, measure=True, skip_lock=True)] * n_pts, timeout=10.0)
            if not rep.check(f"{n_pts} points x {n_avg} samples taken by the PL", ok):
                r.ctrl(abort=1)
                return
            nack = r.get("ADC_STAT", "err_nack")
            rep.check("the ADS1115 acknowledged (no err_nack)", nack == 0,
                      "no answer: check SDA / SCL wiring, the address pin, 3.3 V supply and pull-ups" if nack else "")
            got = c.results(n_pts)
            done = (r.get("ADC_STAT", "count") - count0) & 0xFF
            rep.check(f"{n_pts * n_avg} conversions read", done == n_pts * n_avg or bool(nack), f"{done}")
            last = r.get("ADC_STAT", "last")
            signed = last - 0x10000 if last & 0x8000 else last
            fs = {0: 6.144, 1: 4.096, 2: 2.048, 3: 1.024, 4: 0.512, 5: 0.256}.get((cfgw >> 9) & 7, 0.256)
            for i, w in enumerate(got):
                mean = (w & 0x0FFFFFFF) / n_avg
                rep.info(f"point {i}: sum {w & 0x0FFFFFFF}, mean code {mean:.1f} = {mean * fs / 32768:.4f} V at the ADC pin")
            rep.info(f"last conversion register 0x{last:04X} = {signed} = {signed * fs / 32768:.4f} V")
            if not nack:
                rep.check("codes are in range (0 .. 32767 per sample)", all((w & 0x0FFFFFFF) <= n_avg * 32767 for w in got))
                spread = max(got) - min(got)
                rep.info(f"difference between the two points: {spread / n_avg:.1f} codes")
            if c.real:
                rep.info(f"{dt / (n_pts * n_avg) * 1e3:.2f} ms per sample incl. Python polling "
                         f"(wait {t_conv} us + about {90 * 4 * div / 100:.0f} us on the bus)")
        finally:
            c.release_pins()
            c.reset()
    rep.check("I2C pins back with the PS (PIN_STATE.i2c_pl = 0)", r.get("PIN_STATE", "i2c_pl") == 0)


def stage_if(c: Ctx) -> None:
    import math

    from sadiy_ebaz import ifpath

    r, rep = c.r, c.rep
    if r.rd("VERSION") & 0xFFFF < 2 or "IF_CIC" not in REGS:
        rep.skip("this bitstream has no IF path (register map before 1.2)")
        return
    n, tones, div = 1024, ((100, 16000.0), (260, 1600.0)), max(1, c.args.gen_div)
    cic_r, skip, n_avg, bin0, dbin, n_pts = 16, 4, 8, 40, 5, 56
    shift = ifpath.shift_for(cic_r)
    pat = ifpath.make_pattern(n, tones, noise_rms=20.0, seed=7)
    inc0, step = ifpath.inc_for(bin0 / n, 1.0), ifpath.inc_for(dbin / n, 1.0)
    f = {name: REGS[reg].fields[name] for reg, name in (("GEN_CFG", "enable"), ("GEN_CFG", "sync"),
                                                        ("GEN_CFG", "len_m1"), ("GEN_CFG", "div"))}
    c.reset()
    with Saved(r, ["N_AVG", "DET_CFG", "T_MIN_US", "T_SETTLE_US", "GEN_CFG", "IF_NCO", "IF_NCO_STEP", "IF_CIC"]):
        try:
            r.wr("GEN_CFG", 0)
            r.wr("GEN_ADDR", 0)
            for v in pat:
                r.wr("GEN_DATA", v & 0xFFFF)
            rep.check(f"pattern of {n} samples written (GEN_ADDR wrapped to {n & 0xFFF})", r.rd("GEN_ADDR") == n & 0xFFF)
            r.wr("GEN_CFG", f["enable"].put(1) | f["sync"].put(1) | f["len_m1"].put(n - 1) | f["div"].put(div))
            r.wr("DET_CFG", REGS["DET_CFG"].fields["mode"].put(1) | REGS["DET_CFG"].fields["stream"].put(1))
            r.wr("IF_NCO", inc0)
            r.wr("IF_NCO_STEP", step)
            cic = REGS["IF_CIC"].fields
            r.wr("IF_CIC", cic["r"].put(cic_r) | cic["shift"].put(shift) | cic["skip"].put(skip))
            r.wr("N_AVG", n_avg)
            r.wr("T_MIN_US", 5)
            r.wr("T_SETTLE_US", 5)
            if not rep.check("engine takes the pins", c.take_pins()):
                return
            fs = 100e6 / div
            rep.info(f"generator: {fs / 1e6:.2f} MSPS, tones at bins {tones[0][0]} and {tones[1][0]} of {n} "
                     f"({tones[0][0] * fs / n / 1e3:.1f} kHz, {tones[1][0] * fs / n / 1e3:.1f} kHz, second 20 dB lower); "
                     f"CIC R = {cic_r} (RBW about {fs / cic_r / 1e3:.0f} kHz), {n_pts} points of {dbin} bins")
            ok, dt = c.sweep([TableEntry(word=0, measure=True, skip_lock=True)] * n_pts, timeout=20.0)
            if not rep.check(f"IF sweep of {n_pts} points finished", ok):
                r.ctrl(abort=1)
                return
            got = c.results(n_pts)
            want = [ifpath.if_power_ref(pat, (inc0 + k * step) & 0xFFFFFFFF, cic_r, shift, skip, n_avg)
                    for k in range(n_pts)]
            wantw = [w | (int(o) << ifpath.OVR_BIT) for w, o in want]
            bad = [k for k in range(n_pts) if got[k] != wantw[k]]
            rep.check("every result word equals the Python reference (bit-exact DSP chain)", not bad,
                      "" if not bad else f"{len(bad)} differ, first at point {bad[0]}: 0x{got[bad[0]]:08X}, "
                                         f"reference 0x{wantw[bad[0]]:08X}")
            db = [10 * math.log10(max(1, ifpath.decode(w)[0]) / n_avg) for w in got]
            k1, k2 = (tones[0][0] - bin0) // dbin, (tones[1][0] - bin0) // dbin
            peak = max(range(n_pts), key=lambda k: db[k])
            rep.check(f"strongest point is the first tone (point {k1})", peak == k1, f"point {peak}")
            ref = 10 * math.log10(ifpath.tone_power(tones[0][1], cic_r, shift))
            rep.check("level of the first tone as calculated (within 0.2 dB)", abs(db[k1] - ref) < 0.2,
                      f"{db[k1]:.2f} dB, expected {ref:.2f} dB")
            rep.check("second tone 20 dB below the first (within 1 dB)", abs((db[k1] - db[k2]) - 20.0) < 1.0,
                      f"{db[k1] - db[k2]:.2f} dB")
            floor = sorted(db)[n_pts // 4]
            rep.info(f"first tone {db[k1]:.1f} dB, second {db[k2]:.1f} dB, lower quartile of the trace {floor:.1f} dB "
                     f"(dynamic range shown: {db[k1] - floor:.0f} dB)")
            rep.check("no over-range flag", not any(ifpath.decode(w)[1] for w in got))
            if c.real:
                per = (skip + n_avg) * cic_r * div * 10e-9
                rep.info(f"{dt / n_pts * 1e6:.0f} us per point incl. Python polling (filter time alone {per * 1e6:.1f} us)")
        finally:
            r.wr("GEN_CFG", 0)
            c.release_pins()
            c.reset()


def stage_fe(c: Ctx) -> None:
    """ADC front end (register map 1.3): clock, capture, tie-off, traffic generator and the IF path behind them.
    Needs no ADC and no pins: the data lines are the tie-off or the generator. The pins source is only reported."""
    from sadiy_ebaz import ifpath

    r, rep = c.r, c.rep
    if r.rd("VERSION") & 0xFFFF < 3 or "FE_CFG" not in REGS:
        rep.skip("this bitstream has no ADC front end (register map before 1.3)")
        return
    fe = REGS["FE_CFG"].fields

    def cfg(enable=1, src=0, tg_mode=0, twos=0, div=2, phase=1):
        r.wr("FE_CFG", fe["enable"].put(enable) | fe["src"].put(src) | fe["tg_mode"].put(tg_mode)
             | fe["twos"].put(twos) | fe["div"].put(div) | fe["phase"].put(phase))

    def stat(n=1):
        out = []
        for _ in range(n):
            w = r.rd("FE_STAT")
            f = REGS["FE_STAT"].fields
            out.append({k: f[k].get(w) for k in f})
        return out

    c.reset()
    with Saved(r, ["FE_CFG", "FE_TIE", "FE_TG_INC", "DET_CFG", "N_AVG", "T_MIN_US", "T_SETTLE_US", "IF_NCO",
                   "IF_NCO_STEP", "IF_CIC"]):
        try:
            rep.info(f"FE_CFG at reset 0x{r.rd('FE_CFG'):08X} (expected 0x00010200: off, 50 MS/s, phase 1), "
                     f"FE_TG_INC 0x{r.rd('FE_TG_INC'):08X} (10.7 MHz at 50 MS/s)")
            # The counter keeps its last value while the front end is off (only reset and the clear bit zero it),
            # so after an earlier run it is not 0: clear it first, then it must stay 0 with the front end off.
            r.wr("FE_CFG", r.rd("FE_CFG") | 1 << fe["clear"].lsb)
            rep.check("front end off at reset (clock pin low, no samples counted)",
                      r.rd("FE_CFG") == 0x10200 and all(x["count"] == 0 for x in stat(3)))
            # ---- tie-off
            r.wr("FE_TIE", 0x123)
            cfg(src=0)
            s = stat(4)
            rep.check("tie-off: last code is FE_TIE.code", all(x["last_code"] == 0x123 for x in s[1:]),
                      f"{[hex(x['last_code']) for x in s]}")
            rep.check("tie-off: sample counter advances (clock runs, capture works)",
                      len({x["count"] for x in s}) > 1, f"counts {[x['count'] for x in s]}")
            r.wr("FE_TIE", 0x1_0123)
            time.sleep(0.001)
            s = stat(2)
            rep.check("tie-off OTR reaches last_otr and the sticky otr_seen", s[-1]["last_otr"] == 1 and s[-1]["otr_seen"] == 1)
            r.wr("FE_TIE", 0x123)
            r.wr("FE_CFG", r.rd("FE_CFG") | fe["clear"].put(1))
            time.sleep(0.001)
            s = stat(2)
            rep.check("clear drops otr_seen and the counter restarts", s[0]["otr_seen"] == 0 and s[0]["last_otr"] == 0,
                      f"{s[0]}")
            # ---- traffic generator
            cfg(src=1, tg_mode=0)
            s = stat(20)
            codes = [x["last_code"] for x in s]
            rep.check("ramp generator: codes change from read to read", len(set(codes)) > 10, f"{codes[:8]}")
            cfg(src=1, tg_mode=1)
            s = stat(40)
            rep.check("walking one: every code has exactly one bit set",
                      all(bin(x["last_code"]).count("1") == 1 for x in s[2:]), f"{[hex(x['last_code']) for x in s[2:10]]}")
            seen = {x["last_code"] for x in s}
            rep.check("walking one: several different data lines seen (no line stuck)", len(seen) >= 4, f"{sorted(seen)}")
            cfg(src=1, tg_mode=3)
            r.wr("FE_TIE", 0x5A5)
            time.sleep(0.001)
            rep.check("constant generator mode shows FE_TIE.code", stat(2)[-1]["last_code"] == 0x5A5)
            # ---- clock off: the counter stops
            cfg(enable=0)
            a, b = stat(2)
            rep.check("front end off: counter stops", a["count"] == b["count"])
            # ---- pins: reported only
            cfg(src=2)
            s = stat(3)[-1]
            rep.info(f"pins source: last code 0x{s['last_code']:03X}, OTR {s['last_otr']} (0x800 / 0 when the build has no ADC "
                     f"pads or no module is wired)")
            # ---- IF path behind the front end
            cic = REGS["IF_CIC"].fields
            det = REGS["DET_CFG"].fields
            if not rep.check("engine takes the pins", c.take_pins()):
                return
            r.wr("T_MIN_US", 5)
            r.wr("T_SETTLE_US", 5)
            r.wr("DET_CFG", det["mode"].put(1) | det["src"].put(2))
            r.wr("IF_NCO_STEP", 0)
            r.wr("N_AVG", 1)
            entries = [TableEntry(word=0, measure=True, skip_lock=True)]
            r.wr("FE_TIE", 0xC00)
            cfg(src=0)
            r.wr("IF_NCO", 0)
            r.wr("IF_CIC", cic["r"].put(4) | cic["shift"].put(5) | cic["skip"].put(4))
            ok, _ = c.sweep(entries, timeout=5.0)
            if not rep.check("IF sweep on the tie-off stream finished", ok):
                r.ctrl(abort=1)
                return
            want, _ = ifpath.if_power_ref([16384], 0, 4, 5, 4, 1)
            got = c.results(1)[0]
            rep.check("tie-off stream: result word equals the Python reference (bit-exact)", got & 0x0FFFFFFF == want,
                      f"0x{got:08X}, reference 0x{want:08X}")
            r.wr("FE_TIE", 0x1_0C00)
            ok, _ = c.sweep(entries, timeout=5.0)
            got = c.results(1)[0] if ok else 0
            rep.check("OTR of the front end reaches the result word (bit 30)", ok and got >> ifpath.OVR_BIT & 1 == 1)
            r.wr("FE_TIE", 0x800)
            cfg(src=1, tg_mode=2)
            inc = r.rd("FE_TG_INC")
            r.wr("IF_NCO", inc)
            r.wr("IF_CIC", cic["r"].put(64) | cic["shift"].put(16) | cic["skip"].put(4))
            ok, _ = c.sweep(entries, timeout=5.0)
            on = c.results(1)[0] if ok else 0
            r.wr("IF_NCO", (inc + (1 << 27)) & 0xFFFFFFFF)
            ok2, _ = c.sweep(entries, timeout=5.0)
            off = c.results(1)[0] if ok2 else 0
            e_on, e_off = on >> 22 & 0x3F, off >> 22 & 0x3F
            rep.check("tone generator at the NCO frequency: strong, no over-range (exponent 9..11)",
                      ok and 9 <= e_on <= 11 and not on >> ifpath.OVR_BIT & 1, f"word 0x{on:08X}")
            rep.check("tone two filter nulls (fs / R) away: at least 8 powers of two lower",
                      ok2 and e_off <= e_on - 8, f"exponents {e_on} and {e_off}")
        finally:
            cfg(enable=0)
            c.release_pins()
            c.reset()


def stage_ce(c: Ctx) -> None:
    r, rep = c.r, c.rep
    if "ADF_PINS" not in REGS or r.rd("VERSION") & 0xFFFF < 1:
        rep.skip("this bitstream has no ADF_PINS register (register map 1.0)")
        return
    c.reset()
    rep.info("CE goes low for a moment: the ADF4351 powers down and loses lock. If CE is jumpered high on the "
             "adapter the pin cannot follow (read-back stays 1): remove the jumper to control CE.")
    try:
        r.wr("ADF_PINS", 1)
        c.take_pins()
        rep.check("ADF_PINS.ce = 1: pin high", r.get("PIN_STATE", "ce") == 1)
        r.wr("ADF_PINS", 0)
        time.sleep(0.01)
        rep.check("ADF_PINS.ce = 0: pin low", r.get("PIN_STATE", "ce") == 0)
        rep.info(f"lock detect with CE low: {r.status()['ld_now']}")
        r.wr("ADF_PINS", 1)
        time.sleep(0.01)
        rep.check("ADF_PINS.ce = 1 again: pin high", r.get("PIN_STATE", "ce") == 1)
    finally:
        r.wr("ADF_PINS", 1)
        c.release_pins()
        c.reset()


def stage_spi(c: Ctx) -> None:
    r, rep = c.r, c.rep
    divs = [int(x) for x in c.args.div.split(",")]
    words = [int(x, 0) for x in c.args.words.split(",")] if c.args.words else SAFE_WORDS
    rep.info("words: " + ", ".join(f"0x{w:08X}" for w in words) + "; first word MSB first = " + format(words[0], "032b"))
    c.reset()
    with Saved(r, ["SPI_DIV"]):
        try:
            if not rep.check("engine takes the pins", c.take_pins()):
                return
            for div in divs:
                r.wr("SPI_DIV", div)
                eff = max(div, 2)
                f_mhz = 100.0 / (2 * eff)
                c.pause(f"SPI_DIV = {div}: arm the LA (trigger on LE or CLK), sample >= 100 MHz")
                for _ in range(c.args.repeat):
                    ok, _ = c.sweep([TableEntry(word=w, spi_en=True) for w in words])
                    s = r.status()
                    rep.check(f"SPI_DIV {div}: {len(words)} words sent, sweep finished",
                              bool(ok and r.rd("ENTRY_INDEX") == len(words) and r.rd("POINT_COUNT") == 0), str(s))
                    time.sleep(0.002)
                rep.la(f"SPI_DIV {div}: CLK = {f_mhz:.2f} MHz (period {2 * eff * 10} ns), word = 32 clocks = "
                       f"{32 * 2 * eff * 10 / 1000:.2f} us; DAT stable at the rising CLK edge, MSB first; "
                       "LE low during the whole word, one LE pulse after the last clock (>= 20 ns, datasheet)")
        finally:
            c.release_pins()
            c.reset()


def stage_att(c: Ctx) -> None:
    r, rep = c.r, c.rep
    levels = [int(x, 0) for x in c.args.att_levels.split(",")]
    c.reset()
    with Saved(r, ["T_ATT_GAP_CYC"]):
        try:
            if not rep.check("engine takes the pins", c.take_pins()):
                return
            gap = r.rd("T_ATT_GAP_CYC")
            active_high = r.get("PE4302", "active_high")
            rep.info(f"PE4302.active_high = {active_high}, T_ATT_GAP_CYC = {gap} ({gap * 10} ns per hold)")
            cur = ALL_IN
            for new in levels + [ALL_IN]:
                make = (cur | new) if active_high else (cur & new)
                c.pause(f"change V1..V6 0x{cur:02X} -> 0x{new:02X}: arm the LA on pe4302_v[5:0]")
                ok, _ = c.sweep([TableEntry(word=0, att=new, att_en=True)])
                pe_out, pe_in = r.get("PIN_STATE", "pe_out"), r.get("PIN_STATE", "pe_in")
                rep.check(f"0x{cur:02X} -> 0x{new:02X}: finished, pins at the new level", ok and pe_out == new,
                          f"pe_out = 0x{pe_out:02X}")
                rep.check(f"0x{cur:02X} -> 0x{new:02X}: pad read-back equals the driven level", pe_in == new,
                          f"pe_in = 0x{pe_in:02X}")
                rep.la(f"0x{cur:02X} -> make state 0x{make:02X} for {gap * 10} ns -> 0x{new:02X}, then {gap * 10} ns "
                       "before the entry ends; attenuation never below the lower of old and new")
                cur = new
        finally:
            c.release_pins()
            c.reset()


STAGES = {"ident": stage_ident, "regs": stage_regs, "gen": stage_gen, "push": stage_push, "owner": stage_owner,
          "ctrl": stage_ctrl, "lock": stage_lock, "adc": stage_adc, "if": stage_if, "fe": stage_fe, "ce": stage_ce,
          "spi": stage_spi,
          "att": stage_att}


# ------------------------------------------------------------------------------------------------ main
def _banner() -> None:
    """Which copy of the software this is, and which register map file it reads (a stale package is the usual surprise)."""
    try:
        from sadiy import buildinfo
        what = buildinfo.describe()
    except ImportError:
        what = "sadiy build unknown"
    try:
        from sadiy_ebaz import regmap_toml
        path = os.environ.get("SADIY_REGMAP_TOML") or regmap_toml.DEFAULT_PATH
        v = regmap_toml.map_version(path)
        what += f"; regmap.toml {v >> 16}.{v & 0xFFFF} ({path})"
    except (ImportError, OSError, KeyError):
        pass
    print(f"pl_bringup: {what}")


def make_parser() -> argparse.ArgumentParser:
    p = argparse.ArgumentParser(description=__doc__.split("\n\n")[0],
                                epilog="Stages: " + " ".join(STAGES) + "; 'auto' = " + " ".join(AUTO)
                                + "; 'la' = " + " ".join(LA_STAGES) + "; 'all' = everything.")
    p.add_argument("stages", nargs="*", help="stages to run (default: auto)")
    p.add_argument("--base", type=lambda x: int(x, 0), default=DEFAULT_BASE, help="register base address (0x43C00000)")
    p.add_argument("--model", action="store_true", help="run against the PlModel (no board)")
    p.add_argument("--points", type=int, default=16, help="points in the gen stage (16)")
    p.add_argument("--div", default="2,3,5,10", help="SPI_DIV values of the spi stage (2,3,5,10)")
    p.add_argument("--words", default="", help="SPI words of the spi stage, comma separated (control bits 111 set)")
    p.add_argument("--repeat", type=int, default=3, help="repetitions per SPI_DIV in the spi stage (3)")
    p.add_argument("--att-levels", default="0x00,0x20,0x01,0x1F", help="PE4302 level sequence of the att stage")
    p.add_argument("--gen-div", type=int, default=4, help="clocks per generator sample in the if stage (4 = 25 MSPS)")
    p.add_argument("--no-prompt", action="store_true", help="do not wait for Enter before the LA captures")
    return p


def run(argv: Optional[Sequence[str]] = None, model=None) -> int:
    args = make_parser().parse_args(argv)
    _banner()
    names: List[str] = []
    for s in args.stages or ["auto"]:
        names += AUTO if s == "auto" else LA_STAGES if s == "la" else AUTO + LA_STAGES if s == "all" else [s]
    bad = [n for n in names if n not in STAGES]
    if bad:
        print("unknown stage:", ", ".join(bad))
        return 2
    if "ident" not in names:
        names.insert(0, "ident")                      # always: nothing else makes sense without it
    if args.model and model is None:
        from sadiy_ebaz.ebaz_pl_model import PlModel
        model = PlModel()
        model.lock_model = lambda idx, word, m=model: bool(m.ld_now)
        model.adc_code = lambda idx: 8000 + idx
    if model is not None:
        regs = Regs(model.read, model.write)
        close = lambda: None  # noqa: E731
    else:
        from sadiy_ebaz.devmem import DevMemRegs
        dm = DevMemRegs(args.base)
        regs, close = Regs(dm.read, dm.write), dm.close
    rep = Report()
    ctx = Ctx(regs, rep, args, model)
    try:
        for n in names:
            print(f"== {n}")
            STAGES[n](ctx)
    except SystemExit as e:
        return int(e.code or 0)
    finally:
        if ctx.core_ok:
            try:
                ctx.release_pins()
            except Exception:
                pass
        close()
    print(f"\n{rep.passed} passed, {rep.failed} failed, {rep.skipped} skipped")
    return 1 if rep.failed else 0


if __name__ == "__main__":
    sys.exit(run())
