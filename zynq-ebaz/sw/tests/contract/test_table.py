"""TableEntry packing, build_table and att_pins_for against the real drivers."""
import itertools

import pytest
from sadiy_ebaz.platform import OffloadResult, TableEntry, att_pins_for, build_table
from sadiy_ebaz.regmap_toml import REGS

from sadiy.core.freqplan import build_sweep
from sadiy.drivers.adf4351 import Adf4351, Output, Outputs
from sadiy.drivers.pe4302 import DEFAULT_WEIGHTS_DB, PE4302, STEP_DB
from sadiy.hal.fake import FakeGpio, FakeSpi, PinLog

STEPS = [int(round(w / STEP_DB)) for w in DEFAULT_WEIGHTS_DB]


def make_synth():
    spi = FakeSpi()
    synth = Adf4351(spi, pfd_hz=25e6)
    synth.set_outputs(Outputs(main=Output(True, -4)))
    spi.sent.clear()
    return synth, spi


def sweep(n=8, start=30e6, stop=480e6):
    return build_sweep(start, stop, n, 10.7e6, "high", 25e6)


def test_entry_word_layout():
    e = TableEntry(0xDEADBEEF, att=0x2A, spi_en=True, att_en=True, measure=True, skip_lock=True)
    assert e.w0() == 0xDEADBEEF
    assert e.w1() == 0x2A | 1 << 8 | 1 << 9 | 1 << 10 | 1 << 11
    assert TableEntry(1).w1() == 0


def test_entry_round_trip():
    for flags in itertools.product((False, True), repeat=4):
        e = TableEntry(0x12345678, 0x15, *flags)
        assert TableEntry.from_words(e.w0(), e.w1()) == e
    assert TableEntry.from_words(0, 0xFFFFFFFF).att == 0x3F       # undefined bits are ignored


def test_entry_layout_matches_regmap():
    f = REGS["TABLE_W1"].fields
    e = TableEntry(0, 0x3F)
    assert e.w1() == f["att"].mask
    for name, kw in (("spi_en", "spi_en"), ("att_en", "att_en"), ("measure", "measure"), ("skip_lock", "skip_lock")):
        assert TableEntry(0, **{kw: True}).w1() == f[name].mask


def test_result_words():
    r = OffloadResult.from_result_words([0x00000400, 0x80000401, 0x0FFFFFFF], 4)
    assert r.sums == [0x400, 0x401, 0x0FFFFFFF]
    assert r.unlocked == [False, True, False]
    assert r.err_lock and r.n_avg == 4 and not r.aborted and not r.err_table


def test_first_point_sends_all_six_in_order():
    synth, _ = make_synth()
    pts = sweep()
    table = build_table(pts, synth, 0x15)
    words = synth.registers(pts[0].pll)
    assert [e.word for e in table[:6]] == words
    assert [e.word & 7 for e in table[:6]] == [5, 4, 3, 2, 1, 0]
    assert all(e.spi_en for e in table)


def test_later_points_only_changed_words_r0_last_with_measure():
    synth, _ = make_synth()
    pts = sweep(16)
    table = build_table(pts, synth, 0)
    # replay: split into points at the measure entries
    groups, cur = [], []
    for e in table:
        cur.append(e)
        if e.measure:
            groups.append(cur)
            cur = []
    assert cur == [] and len(groups) == len(pts)
    last = {}
    for pt, group in zip(pts, groups):
        words = synth.registers(pt.pll)
        expect = [w for w in words if w & 7 == 0 or last.get(w & 7) != w]
        assert [e.word for e in group] == expect
        assert group[-1].word & 7 == 0 and group[-1].measure
        assert not any(e.measure for e in group[:-1])
        last.update({w & 7: w for w in words})
    assert sum(len(g) for g in groups[1:]) < 6 * (len(pts) - 1)       # something was saved


def test_r0_is_sent_even_when_unchanged():
    synth, _ = make_synth()
    pt = sweep(2)[0]
    table = build_table([pt, pt, pt], synth, 0)
    assert len(table) == 6 + 1 + 1
    assert [e.measure for e in table].count(True) == 3


def test_full_sends_six_per_point():
    synth, _ = make_synth()
    pts = sweep(5)
    table = build_table(pts, synth, 0, full=True)
    assert len(table) == 30
    assert sum(e.measure for e in table) == 5
    for k in range(5):
        assert [e.word & 7 for e in table[6 * k:6 * k + 6]] == [5, 4, 3, 2, 1, 0]


def test_att_and_skip_lock_flags():
    synth, _ = make_synth()
    table = build_table(sweep(3), synth, 0x2A, skip_lock=True)
    assert table[0].att_en and table[0].att == 0x2A
    assert not any(e.att_en for e in table[1:])
    assert all(e.skip_lock == e.measure for e in table)
    assert not any(e.skip_lock for e in build_table(sweep(3), synth, 0x2A))


def test_r4_carries_output_state_and_no_spi_traffic():
    synth, spi = make_synth()
    table = build_table(sweep(4), synth, 0)
    assert spi.sent == []                                   # building a table never touches the SPI
    r4 = [e.word for e in table if e.word & 7 == 4]
    assert r4 and all(w & (1 << 5) for w in r4)             # main output enable bit
    synth.disable_outputs()
    spi.sent.clear()
    table_off = build_table(sweep(4), synth, 0)
    assert not any(e.word & (1 << 5) for e in table_off if e.word & 7 == 4)
    assert spi.sent == []


def test_empty_points():
    synth, _ = make_synth()
    assert build_table([], synth, 5) == []


@pytest.mark.parametrize("active_high", [True, False])
def test_att_pins_for_matches_pe4302(active_high):
    log = PinLog()
    lines = [FakeGpio(f"V{i}", log) for i in range(6)]
    dev = PE4302(lines, DEFAULT_WEIGHTS_DB, active_high)
    for code in range(64):
        dev.set_attenuation(code * STEP_DB)
        levels = sum(ln.level << i for i, ln in enumerate(lines))
        assert att_pins_for(code, STEPS, active_high) == levels, code
