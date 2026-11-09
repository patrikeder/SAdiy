import pytest

from sadiy.core.freqplan import DIVIDERS, PllPlan, build_sweep, plan_pll
from sadiy.drivers.adf4351 import (
    Adf4351, Output, Outputs, pack_r0, pack_r1, pack_r2, pack_r3, pack_r5, prescaler_89, register_of,
)
from sadiy.hal.fake import FakeSpi

MAIN_EN = 1 << 5


def make(**kw):
    spi = FakeSpi()
    return Adf4351(spi, 25e6, **kw), spi


def sent(spi):
    return [int.from_bytes(b, "big") for b in spi.sent]


# --- single words -------------------------------------------------------------------------------

def test_words_match_the_adi_example_words_as_recalled():
    # VERIFY: these four are the example words I remember from ADI's software, not read from a file
    assert pack_r5() == 0x00580005
    assert pack_r3(int_mode=False) == 0x000004B3
    assert pack_r2(int_mode=False) == 0x00004E42
    assert pack_r1(5, True) == 0x08008029


def test_r0_fields():
    assert pack_r0(160, 0) == 0x00500000
    assert pack_r0(1, 0) == 1 << 15
    assert pack_r0(0, 1) == 1 << 3
    assert pack_r0(0xFFFF, 0xFFF) == 0x7FFFFFF8
    assert register_of(pack_r0(100, 7)) == 0
    for bad in ((0x10000, 0), (1, 0x1000), (-1, 0)):
        with pytest.raises(ValueError):
            pack_r0(*bad)


def test_r1_fields():
    assert pack_r1(2, False) == (1 << 15) | (2 << 3) | 1
    assert pack_r1(4095, True, phase=0) == (1 << 27) | (4095 << 3) | 1
    assert pack_r1(100, False, phase=7) >> 15 & 0xFFF == 7
    assert pack_r1(100, False) & (1 << 28) == 0                   # phase adjust stays off
    assert register_of(pack_r1(10, False)) == 1
    for bad in ((1, False), (4096, False)):
        with pytest.raises(ValueError):
            pack_r1(*bad)
    with pytest.raises(ValueError):
        pack_r1(5, False, phase=5)


def test_r2_fields():
    assert register_of(pack_r2(False)) == 2
    assert pack_r2(False) >> 14 & 0x3FF == 1                      # R = 1
    assert pack_r2(False, cp_index=0) >> 9 & 0xF == 0
    assert pack_r2(False, cp_index=15) >> 9 & 0xF == 15
    assert pack_r2(False) & (1 << 6)                               # positive polarity
    assert pack_r2(False) & ((1 << 25) | (1 << 24)) == 0           # no doubler, no divide by 2
    assert pack_r2(False) >> 26 & 0b111 == 0                       # MUXOUT three-state
    assert pack_r2(False) >> 29 == 0                               # low noise
    assert pack_r2(False, low_spur=True) >> 29 == 0b11
    assert pack_r2(False) & 0b1000_0000 == 0 and pack_r2(False) & 0b1_0000_0000 == 0
    assert pack_r2(True) == pack_r2(False) | (1 << 8) | (1 << 7)   # LDF and LDP for integer-N
    # power-down, charge pump three-state and counter reset are never set
    assert pack_r2(True, low_spur=True) & ((1 << 5) | (1 << 4) | (1 << 3)) == 0
    with pytest.raises(ValueError):
        pack_r2(False, cp_index=16)


def test_r3_fields():
    assert register_of(pack_r3(False)) == 3
    assert pack_r3(False) >> 3 & 0xFFF == 150
    assert pack_r3(False, clock_divider=0xFFF) >> 3 & 0xFFF == 0xFFF
    assert pack_r3(False) >> 15 & 0b11 == 0                        # clock divider mode off
    assert pack_r3(False) & ((1 << 23) | (1 << 18)) == 0           # band select clock low, no CSR
    assert pack_r3(True) == pack_r3(False) | (1 << 22) | (1 << 21)
    with pytest.raises(ValueError):
        pack_r3(False, clock_divider=0x1000)


def test_r5_leaves_the_ld_pin_as_digital_lock_detect():
    assert register_of(pack_r5()) == 5
    assert pack_r5() >> 22 & 0b11 == 0b01
    assert pack_r5() >> 19 & 0b11 == 0b11


def test_prescaler_rule():
    assert not prescaler_89(2.2e9)
    assert not prescaler_89(3.6e9)
    assert prescaler_89(3.6e9 + 1)
    assert prescaler_89(4.4e9)


# --- registers() -------------------------------------------------------------------------------

def test_registers_for_100_mhz_integer_n():
    dev, _ = make()
    pll = plan_pll(100e6, 25e6)
    assert (pll.rf_div, pll.int_n, pll.frac, pll.mod) == (32, 128, 0, 2)
    assert dev.registers(pll) == [
        0x00580005,                  # R5
        0x00DC8004,                  # R4: divider 32, band select divider 200, outputs off
        0x006004B3,                  # R3: integer-N: ABP 3 ns (bit 22), charge cancel (bit 21)
        0x00004FC2,                  # R2: LDF and LDP set
        0x00008011,                  # R1: MOD 2, 4/5 prescaler, phase 1
        0x00400000,                  # R0: INT 128
    ]


def test_registers_for_a_fractional_point():
    dev, _ = make()
    pll = plan_pll(110.7e6, 25e6)
    assert (pll.rf_div, pll.int_n, pll.frac, pll.mod) == (32, 141, 87, 125)
    r5, r4, r3, r2, r1, r0 = dev.registers(pll)
    assert r3 == 0x000004B3 and r2 == 0x00004E42               # fractional-N settings
    assert r1 == (1 << 15) | (125 << 3) | 1                    # VCO 3.54 GHz: still 4/5
    assert r0 == (141 << 15) | (87 << 3)


def test_8_9_prescaler_above_3_6_ghz_vco():
    dev, _ = make()
    pll = plan_pll(260.7e6, 25e6)                              # VCO 4.17 GHz
    assert dev.registers(pll)[4] & (1 << 27)
    assert not dev.registers(plan_pll(100e6, 25e6))[4] & (1 << 27)


def test_write_order_is_r5_r4_r3_r2_r1_r0():
    dev, _ = make()
    words = dev.registers(plan_pll(150e6, 25e6))
    assert [register_of(w) for w in words] == [5, 4, 3, 2, 1, 0]


def test_outputs_stay_off_in_registers_until_enabled():
    dev, _ = make()
    pll = plan_pll(100e6, 25e6)
    assert dev.registers(pll)[1] & MAIN_EN == 0
    dev.set_outputs(Outputs(main=Output(True, 2)))
    r4 = dev.registers(pll)[1]
    assert r4 & MAIN_EN and (r4 >> 3) & 0b11 == 2
    dev.disable_outputs()
    assert dev.registers(pll)[1] & MAIN_EN == 0


def test_cp_index_and_low_spur_reach_r2():
    dev, _ = make(cp_index=3, low_spur=True)
    r2 = dev.registers(plan_pll(110.7e6, 25e6))[3]
    assert r2 >> 9 & 0xF == 3 and r2 >> 29 == 0b11


def test_invalid_plans_are_refused():
    dev, _ = make()
    ok = plan_pll(260.7e6, 25e6)
    with pytest.raises(ValueError, match="INT"):
        dev.registers(PllPlan(ok.f_out_hz, ok.f_actual_hz, ok.rf_div, 74, ok.frac, ok.mod, ok.f_vco_hz, ok.f_pfd_hz))
    low = plan_pll(100e6, 25e6)
    with pytest.raises(ValueError, match="INT"):
        dev.registers(PllPlan(low.f_out_hz, low.f_actual_hz, low.rf_div, 22, 0, 2, low.f_vco_hz, low.f_pfd_hz))
    with pytest.raises(ValueError, match="FRAC"):
        dev.registers(PllPlan(low.f_out_hz, low.f_actual_hz, low.rf_div, 128, 5, 5, low.f_vco_hz, low.f_pfd_hz))
    with pytest.raises(ValueError, match="rf_div"):
        dev.registers(PllPlan(low.f_out_hz, low.f_actual_hz, 3, 128, 0, 2, low.f_vco_hz, low.f_pfd_hz))


def decode(words, pfd_hz=25e6):
    r4, r1, r0 = words[1], words[4], words[5]
    div = 1 << (r4 >> 20 & 0b111)
    n = (r0 >> 15 & 0xFFFF) + (r0 >> 3 & 0xFFF) / (r1 >> 3 & 0xFFF)
    return n * pfd_hz / div


def test_every_sweep_point_decodes_to_its_frequency():
    dev, _ = make()
    for pt in build_sweep(30e6, 480e6, 401, 10.7e6, "high", 25e6):
        words = dev.registers(pt.pll)
        assert abs(decode(words) - pt.pll.f_actual_hz) < 1e-3
        assert abs(decode(words) - pt.f_lo_hz) < 100            # PLL resolution at 25 MHz / 4095 / 64
        assert all(0 <= w < 1 << 32 for w in words)
        assert [register_of(w) for w in words] == [5, 4, 3, 2, 1, 0]


def test_the_whole_divider_range_packs():
    dev, _ = make()
    seen = set()
    for f in (35e6, 60e6, 100e6, 200e6, 400e6, 800e6, 1.6e9, 3.2e9, 4.4e9):
        pll = plan_pll(f, 25e6)
        dev.registers(pll)
        seen.add(pll.rf_div)
    assert seen == set(DIVIDERS)


def test_tune_writes_the_six_words_and_remembers_the_divider():
    dev, spi = make()
    spi.sent.clear()
    pt = build_sweep(100e6, 100e6, 1, 10.7e6, "high", 25e6)[0]
    dev.tune(pt)
    assert [register_of(w) for w in sent(spi)] == [5, 4, 3, 2, 1, 0]
    assert sent(spi) == dev.registers(pt.pll)
    assert dev.r4_word() == sent(spi)[1]                        # divider carried over to later R4 writes


# --- readback: decoding the words that were written ---------------------------------------------

def test_decode_registers_inverts_the_packing_for_every_sweep_point():
    from sadiy.drivers.adf4351 import decode_registers

    dev, _ = make()
    dev.set_outputs(Outputs(main=Output(True, 2), aux=Output(False, -1)))
    for pt in build_sweep(30e6, 480e6, 101, 10.7e6, "high", 25e6):
        words = dev.registers(pt.pll)
        d = decode_registers({register_of(w): w for w in words}, 25e6)
        assert (d["int_n"], d["frac"], d["mod"], d["rf_div"]) == (pt.pll.int_n, pt.pll.frac, pt.pll.mod, pt.pll.rf_div)
        assert abs(d["f_out_hz"] - pt.pll.f_actual_hz) < 1e-3
        assert d["mode"] == ("integer-N" if pt.pll.frac == 0 else "fractional-N")
        assert d["main"] == {"enabled": True, "power_dbm": 2} and d["aux"]["enabled"] is False   # a disabled output keeps no power
        assert list(d["words"]) == ["R5", "R4", "R3", "R2", "R1", "R0"]


def test_decode_registers_knows_only_what_was_written():
    from sadiy.drivers.adf4351 import decode_registers, pack_r4

    d = decode_registers({4: pack_r4(8, Outputs(), 200)}, 25e6)
    assert d["rf_div"] == 8 and d["f_out_hz"] is None and d["mode"] is None and d["main"]["enabled"] is False
    assert decode_registers({}, 25e6)["words"] == {} and decode_registers({}, 25e6)["main"] is None
    # 8/9 prescaler is reported from R1
    dev, _ = make()
    d = decode_registers({register_of(w): w for w in dev.registers(plan_pll(4.0e9, 25e6))}, 25e6)
    assert d["prescaler"] == "8/9" and abs(d["f_out_hz"] - 4.0e9) < 10
