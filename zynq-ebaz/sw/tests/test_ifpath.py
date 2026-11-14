"""Reference of the IF path (`sadiy_ebaz.ifpath`) and the PL model's use of it."""
import math

import pytest
from sadiy_ebaz import ifpath
from sadiy_ebaz.ebaz_pl_model import PlModel
from sadiy_ebaz.regmap_toml import OFFSET, REGS


def test_sine_table():
    rom = ifpath.nco_rom()
    assert len(rom) == 2048 and rom[0] == 0 and rom[512] == 32767 and rom[1536] == -32767
    assert all(rom[i] == -rom[i + 1024] for i in range(1024))
    assert max(rom) == 32767 and min(rom) == -32767


@pytest.mark.parametrize("acc", [0, 1, (1 << 22) - 1, 1 << 22, 0x3FFE0004, (1 << 49) - 1])
def test_float_word_roundtrip(acc):
    value, ovr, unlocked = ifpath.decode(ifpath.float28(acc))
    assert not ovr and not unlocked
    assert value <= acc and acc - value < max(1, acc >> 21)      # 22-bit mantissa, truncated


def test_tone_level_and_selectivity():
    n, r = 1024, 16
    shift = ifpath.shift_for(r)
    pat = ifpath.make_pattern(n, [(100, 16000.0)])

    def db(cyc):
        word, sat = ifpath.if_power_ref(pat, ifpath.inc_for(cyc / n, 1.0), r, shift, 4, 8)
        assert not sat
        return 10 * math.log10(max(1, ifpath.decode(word)[0]) / 8)

    assert db(100) == pytest.approx(10 * math.log10(ifpath.tone_power(16000.0, r, shift)), abs=0.05)
    assert db(100) - db(100 + 64) > 60        # first null of the CIC at fs / R = 64 bins
    assert db(100) - db(300) > 50


def test_saturation_sets_the_flag():
    pat = ifpath.make_pattern(64, [(8, 32767.0)])
    word, sat = ifpath.if_power_ref(pat, ifpath.inc_for(8 / 64, 1.0), 4, 0, 4, 2)
    assert sat


def test_negative_frequency_and_wrapping_increment():
    assert ifpath.inc_for(-0.25, 1.0) == 0xC000_0000 and ifpath.inc_for(0.25, 1.0) == 0x4000_0000


def model_with_pattern(pat, mode_if=True):
    m = PlModel()
    w = lambda name, v: m.write(OFFSET[name], v)  # noqa: E731
    w("GEN_ADDR", 0)
    for v in pat:
        w("GEN_DATA", v & 0xFFFF)
    g = REGS["GEN_CFG"].fields
    w("GEN_CFG", g["enable"].put(1) | g["sync"].put(1) | g["len_m1"].put(len(pat) - 1) | 1)
    d = REGS["DET_CFG"].fields
    w("DET_CFG", (d["mode"].put(1) if mode_if else d["src"].put(2)) | d["stream"].put(1))
    w("CTRL", REGS["CTRL"].fields["pin_owner"].put(1))
    return m, w


def run_points(m, w, n):
    w("TABLE_ADDR", 0)
    for _ in range(n):
        w("TABLE_W0", 0)
        w("TABLE_W1", 0xC00)
    w("N_ENTRIES", n)
    w("CTRL", REGS["CTRL"].fields["pin_owner"].put(1) | 1)
    w("RESULT_ADDR", 0)
    return [m.read(OFFSET["RESULT_DATA"]) for _ in range(n)]


def test_model_if_sweep_steps_the_nco():
    pat = ifpath.make_pattern(256, [(40, 20000.0)])
    m, w = model_with_pattern(pat)
    inc0, step = ifpath.inc_for(30 / 256, 1.0), ifpath.inc_for(5 / 256, 1.0)
    w("IF_NCO", inc0)
    w("IF_NCO_STEP", step)
    w("N_AVG", 4)
    c = REGS["IF_CIC"].fields
    w("IF_CIC", c["r"].put(8) | c["shift"].put(ifpath.shift_for(8)) | c["skip"].put(4))
    res = run_points(m, w, 5)
    want = [ifpath.if_power_ref(pat, inc0 + k * step, 8, ifpath.shift_for(8), 4, 4)[0] for k in range(5)]
    assert res == want and max(range(5), key=lambda k: ifpath.decode(res[k])[0]) == 2
    assert run_points(m, w, 5) == want                      # a new sweep starts at the base increment again


def test_model_video_path_from_the_generator_clamps_negative_samples():
    m, w = model_with_pattern([100, -5, 7, -32768, 9], mode_if=False)
    w("N_AVG", 7)
    assert run_points(m, w, 1) == [100 + 7 + 9 + 100 + 0]


def test_model_waits_without_a_stream():
    m, w = model_with_pattern([1, 2, 3])
    w("GEN_CFG", 0)
    w("N_AVG", 1)
    w("TABLE_ADDR", 0)
    w("TABLE_W0", 0)
    w("TABLE_W1", 0xC00)
    w("N_ENTRIES", 1)
    w("CTRL", REGS["CTRL"].fields["pin_owner"].put(1) | 1)
    st = REGS["STATUS"].fields
    assert st["busy"].get(m.read(OFFSET["STATUS"])) == 1 and st["wait_sample"].get(m.read(OFFSET["STATUS"])) == 1
