#!/usr/bin/env python3
"""Golden vectors for the SystemVerilog testbenches, from the Python drivers and the PL model.

Writes plain text files for $readmemh into `vectors/` (one hex value per line, fixed width, no comments in the
data) and `vectors/README.md` that describes every file. Deterministic. `--check` writes nothing and exits 1 when
a file on disk differs from what would be written.

    python zynq-ebaz/rtl/sim/gen_vectors.py [--check]
"""
from __future__ import annotations

import argparse
import sys
from pathlib import Path
from typing import Dict, List

HERE = Path(__file__).resolve().parent
REPO = HERE.parents[2]
sys.path[:0] = [str(REPO / "src"), str(REPO / "zynq-ebaz" / "sw")]

from sadiy.core.freqplan import build_sweep                      # noqa: E402
from sadiy.drivers.adf4351 import Adf4351, Outputs, Output      # noqa: E402
from sadiy.drivers.pe4302 import DEFAULT_WEIGHTS_DB, STEP_DB, PE4302  # noqa: E402
from sadiy.hal.fake import FakeGpio, FakeSpi, PinLog            # noqa: E402

from sadiy_ebaz.ebaz_pl_model import PlModel                     # noqa: E402
from sadiy_ebaz.platform import build_table                      # noqa: E402
from sadiy_ebaz.regmap_toml import OFFSET, REGS                  # noqa: E402

VECTORS = HERE / "vectors"
PFD_HZ = 25e6
IF_HZ = 10.7e6
STEPS = [int(round(w / STEP_DB)) for w in DEFAULT_WEIGHTS_DB]
CORNER_WORDS = (0x00000000, 0xFFFFFFFF, 0xAAAAAAAA, 0x55555555, 0x80000001)

SCENARIO = dict(start_hz=50e6, stop_hz=450e6, points=24, n_avg=4, det_base=0x0100, att_pins=0x15,
                unlocked_indices=(5, 17))


def hexlines(values, digits: int) -> str:
    return "".join(f"{v:0{digits}X}\n" for v in values)


def make_synth() -> Adf4351:
    """The synthesiser as sweepd configures it: main output on at -4 dBm. Nothing is sent anywhere real."""
    synth = Adf4351(FakeSpi(), pfd_hz=PFD_HZ)
    synth.set_outputs(Outputs(main=Output(True, -4)))
    return synth


def sweep_points(start_hz: float, stop_hz: float, n: int):
    return build_sweep(start_hz, stop_hz, n, IF_HZ, "high", PFD_HZ)


# ---- spi_words ---------------------------------------------------------------------------------------------
def spi_words() -> List[int]:
    synth = make_synth()
    words: List[int] = []
    for pt in sweep_points(30e6, 480e6, 16):
        words += synth.registers(pt.pll)
    return words + list(CORNER_WORDS)


# ---- make-before-break -------------------------------------------------------------------------------------
def code_of_levels(levels: int, active_high: bool) -> int:
    """Attenuation code (0.5 dB units) whose pin levels are `levels`."""
    on_mask = levels if active_high else ~levels & 0x3F
    return sum(step for i, step in enumerate(STEPS) if on_mask >> i & 1)


def mbb_table(active_high: bool) -> List[int]:
    """{old, new, make} per transition, make taken from the writes of the real PE4302 driver: the state after
    its 'turning on' writes and before its first 'turning off' write."""
    log = PinLog()
    lines = [FakeGpio(f"V{i + 1}", log) for i in range(6)]
    dev = PE4302(lines, DEFAULT_WEIGHTS_DB, active_high)
    out = []
    for old in range(64):
        for new in range(64):
            dev.set_attenuation(code_of_levels(old, active_high) * STEP_DB)
            assert sum(ln.level << i for i, ln in enumerate(lines)) == old
            log.events.clear()
            dev.set_attenuation(code_of_levels(new, active_high) * STEP_DB)
            state, make, seen_off = old, None, False
            for name, level in log.events:
                bit = 1 << (int(name[1:]) - 1)                # "V3" -> line 2
                is_on = bool(level) == active_high
                if not is_on and not seen_off:
                    make, seen_off = state, True
                assert not (is_on and seen_off), "a turning-on write came after a turning-off write"
                state = state & ~bit | (bit if level else 0)
            assert state == new
            out.append((old << 12) | (new << 6) | (state if make is None else make))
    return out


# ---- complete sweep scenario -------------------------------------------------------------------------------
def scenario() -> Dict[str, List[int]]:
    sc = SCENARIO
    synth = make_synth()
    table = build_table(sweep_points(sc["start_hz"], sc["stop_hz"], sc["points"]), synth, sc["att_pins"])
    model = PlModel()
    bad = set(sc["unlocked_indices"])
    model.lock_model = lambda index, word: index not in bad
    w = lambda name, value: model.write(OFFSET[name], value)          # noqa: E731
    w("DET_CFG", 1)
    w("DET_TEST", sc["det_base"])
    w("N_AVG", sc["n_avg"])
    w("CTRL", REGS["CTRL"].fields["pin_owner"].mask)
    w("TABLE_ADDR", 0)
    for e in table:
        w("TABLE_W0", e.w0())
        w("TABLE_W1", e.w1())
    w("N_ENTRIES", len(table))
    w("CTRL", REGS["CTRL"].fields["pin_owner"].mask | REGS["CTRL"].fields["start"].mask)
    status = model.read(OFFSET["STATUS"])
    done, busy = REGS["STATUS"].fields["done"], REGS["STATUS"].fields["busy"]
    assert done.get(status) and not busy.get(status), "scenario sweep did not finish"
    count = model.read(OFFSET["POINT_COUNT"])
    w("RESULT_ADDR", 0)
    results = [model.read(OFFSET["RESULT_DATA"]) for _ in range(count)]
    assert count == sc["points"]
    return {
        "table": [e.w1() << 32 | e.w0() for e in table],
        "spi": list(model.spi_words),
        "result": results,
        "unlock": [int(i in bad) for i in range(count)],
        "meta": [len(table), count, sc["n_avg"], sc["det_base"], sc["att_pins"], len(model.spi_words)],
    }


README = """# Golden vectors

Generated by `zynq-ebaz/rtl/sim/gen_vectors.py` (run `rtl/scripts/gen.sh`; never edit by hand). Plain text for
`$readmemh`: one hex value per line, fixed width, upper case, no `0x`. `gen_vectors.py --check` (and the pytest
`rtl/tests/test_gen_vectors.py`) fail when these files are not current.

| File | Lines | Width | Content |
|---|---|---|---|
| `spi_words.hex` | 101 | 8 digits | ADF4351 register words, `Adf4351.registers()` (write order R5..R0, all six) for 16 points 30..480 MHz (high-side LO, IF 10.7 MHz, PFD 25 MHz), main output on at -4 dBm; then the corner words `00000000`, `FFFFFFFF`, `AAAAAAAA`, `55555555`, `80000001` |
| `spi_words.cnt` | 1 | 8 digits | number of words in `spi_words.hex` |
| `mbb_high.hex` | 4096 | 5 digits | `{{old[5:0], new[5:0], make[5:0]}}` (18 bit), index `old*64+new`, PIN LEVEL masks (bit i = line i), PE4302 active high. `make` is the pin state the real `PE4302` driver shows after its turning-on writes and before its turning-off writes. Rule: `make = old | new` |
| `mbb_low.hex` | 4096 | 5 digits | the same for active low (a low pin switches the stage in). Rule: `make = old & new` |
| `sweep_table.hex` | {n_entries} | 16 digits | table of the scenario below, `{{w1, w0}}` (64 bit, `w0` the SPI word, `w1` the flags of rtl-spec.md section 5) |
| `sweep_spi.hex` | {n_spi} | 8 digits | SPI words the engine must send, in order |
| `sweep_result.hex` | {n_results} | 8 digits | result words the engine must store, in order |
| `sweep_unlock.hex` | {n_results} | 1 digit | per result index: `1` = the testbench's lock model must time out for that point, `0` = lock |
| `sweep_meta.hex` | 6 | 8 digits | n_entries, n_results, n_avg, det_base, att_pins, number of SPI words |

Scenario of `sweep_*`: produced by `PlModel` with `DET_CFG.src = 1`, `DET_TEST.base = 0x{det_base:04X}`,
`N_AVG = {n_avg}`, all timing registers at their reset values, `stop_on_err = 0`, `PE4302.manual` at its reset
value, `pin_owner = 1`. Table from `build_table()` for {points} points {start:g}..{stop:g} MHz (IF 10.7 MHz, high-side
LO), `att_pins = 0x{att_pins:02X}` on the first entry, main output on at -4 dBm. Lock fails (timeout, result
bit 31 set) for result indices {unlocked}; every other point locks. A result sum is `N_AVG * ((base + (index & 255)) & 0xFFFF)`.
"""


def build_files() -> Dict[str, str]:
    words = spi_words()
    sc = scenario()
    files = {
        "spi_words.hex": hexlines(words, 8),
        "spi_words.cnt": hexlines([len(words)], 8),
        "mbb_high.hex": hexlines(mbb_table(True), 5),
        "mbb_low.hex": hexlines(mbb_table(False), 5),
        "sweep_table.hex": hexlines(sc["table"], 16),
        "sweep_spi.hex": hexlines(sc["spi"], 8),
        "sweep_result.hex": hexlines(sc["result"], 8),
        "sweep_unlock.hex": hexlines(sc["unlock"], 1),
        "sweep_meta.hex": hexlines(sc["meta"], 8),
    }
    s = SCENARIO
    files["README.md"] = README.format(
        n_entries=len(sc["table"]), n_spi=len(sc["spi"]), n_results=len(sc["result"]), det_base=s["det_base"],
        n_avg=s["n_avg"], points=s["points"], start=s["start_hz"] / 1e6, stop=s["stop_hz"] / 1e6,
        att_pins=s["att_pins"], unlocked=", ".join(str(i) for i in s["unlocked_indices"]))
    return files


def main(argv=None) -> int:
    ap = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    ap.add_argument("--check", action="store_true", help="write nothing; exit 1 if files on disk differ")
    args = ap.parse_args(argv)
    files = build_files()
    if args.check:
        stale = [n for n, text in files.items()
                 if not (VECTORS / n).exists() or (VECTORS / n).read_text() != text]
        if stale:
            print("vectors out of date: " + ", ".join(stale), file=sys.stderr)
            return 1
        print(f"vectors current ({len(files)} files)")
        return 0
    VECTORS.mkdir(parents=True, exist_ok=True)
    for name, text in files.items():
        (VECTORS / name).write_text(text)
    print(f"wrote {len(files)} files to {VECTORS}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
