"""ADC front end (register map 1.3) in the PL model: registers, tie-off, traffic generator, pins, through the IF path.

The expected numbers are the ones of the RTL testbench tb_if.sv (`FE tie-off` / `FE tone`), so model and RTL agree.
"""
import pytest
from sadiy_ebaz.ebaz_pl_model import FE_TICK, PlModel
from sadiy_ebaz.ifpath import if_power_ref
from sadiy_ebaz.platform import TableEntry
from sadiy_ebaz.reg_offload import RegOffload
from sadiy_ebaz.regmap_toml import OFFSET, REGS

FE = REGS["FE_CFG"].fields
TONE_INC = 0x36C8B439
SRC_STREAM = 2


class Rig:
    def __init__(self):
        self.model = PlModel()
        self.model.ld_now = True
        self.off = RegOffload(self.model.read, self.model.write, poll_s=0.0)
        self.off.upload([TableEntry(word=0, measure=True, skip_lock=True)])

    def wr(self, name, value):
        self.model.write(OFFSET[name], value)

    def rd(self, name):
        return self.model.read(OFFSET[name])

    def fe(self, *, enable=1, src=0, twos=0, tg_mode=0, div=2, phase=1):
        self.wr("FE_CFG", FE["enable"].put(enable) | FE["src"].put(src) | FE["twos"].put(twos)
                | FE["tg_mode"].put(tg_mode) | FE["div"].put(div) | FE["phase"].put(phase))

    def if_point(self, r=4, shift=5, skip=4, n_avg=1, inc=0):
        d = REGS["DET_CFG"].fields
        self.wr("DET_CFG", d["mode"].put(1) | d["src"].put(SRC_STREAM))          # stream 0: not the generator
        self.wr("IF_NCO", inc)
        self.wr("IF_NCO_STEP", 0)
        self.wr("IF_CIC", (skip << 24) | (shift << 16) | r)
        self.off.run(n_avg)
        return self.result_word()

    def result_word(self):
        self.wr("RESULT_ADDR", 0)
        return self.rd("RESULT_DATA")


def test_reset_values_and_version():
    rig = Rig()
    assert rig.rd("VERSION") == 0x00020000
    assert rig.rd("FE_CFG") == 0x0001_0200                     # div 2 = 50 MS/s, phase 1, everything else off
    assert rig.rd("FE_TIE") == 0x0000_0800
    assert rig.rd("FE_TG_INC") == TONE_INC
    assert rig.rd("FE_STAT") == 0


def test_clear_bit_reads_zero_and_other_fields_are_stored():
    rig = Rig()
    rig.wr("FE_CFG", 0xFFFF_FFFF)
    assert rig.rd("FE_CFG") == 0x00FF_FF3F                     # bit 6 (clear) reads 0
    rig.wr("FE_TIE", 0xFFFF_FFFF)
    assert rig.rd("FE_TIE") == 0x0001_0FFF


def test_tie_off_is_a_constant_stream_and_the_result_is_bit_exact():
    rig = Rig()
    rig.wr("FE_TIE", 0xC00)                                    # (0xC00 - 0x800) << 4 = 16384
    rig.fe(src=0)
    word = rig.if_point()
    want, ovr = if_power_ref([16384], 0, 4, 5, 4, 1)
    assert not ovr
    assert word & 0x0FFF_FFFF == want and not word >> 30 & 1
    assert word & 0x0FFF_FFFF == (8 << 22) | (0x3FFE0004 >> 8)      # the constant tb_if.sv checks


def test_tie_off_otr_marks_the_result():
    rig = Rig()
    rig.wr("FE_TIE", 0x1_0C00)
    rig.fe(src=0)
    assert rig.if_point() >> 30 & 1


def test_the_front_end_is_only_the_stream_when_enabled():
    rig = Rig()
    rig.wr("FE_TIE", 0xC00)
    rig.fe(enable=0, src=0)
    rig.model.ext_stream = [4096]                              # another adapter on the det_ext port
    off = rig.if_point()
    rig.fe(enable=1, src=0)
    on = rig.if_point()
    assert off != on and on & 0x0FFF_FFFF == (8 << 22) | (0x3FFE0004 >> 8)


def test_traffic_generator_tone_gives_the_level_of_the_testbench():
    rig = Rig()
    rig.fe(src=1, tg_mode=2)
    word = rig.if_point(r=64, shift=16, skip=4, inc=TONE_INC)
    exp = word >> 22 & 0x3F
    assert 9 <= exp <= 11 and not word >> 30 & 1               # about 2^32, as tb_if.sv expects


def test_tone_at_another_frequency_is_rejected_by_the_filter():
    rig = Rig()
    rig.fe(src=1, tg_mode=2)
    on = rig.if_point(r=64, shift=16, skip=4, inc=TONE_INC)
    off = rig.if_point(r=64, shift=16, skip=4, inc=TONE_INC + (1 << 27))   # two filter nulls (fs / R) away
    assert (off >> 22 & 0x3F) < (on >> 22 & 0x3F) - 8


def test_two_complement_strap_changes_the_conversion():
    rig = Rig()
    rig.wr("FE_TIE", 0x400)                                    # offset binary: -1024 << 4; two's complement: +1024 << 4
    rig.fe(src=0, twos=0)
    a = rig.if_point()
    rig.fe(src=0, twos=1)
    b = rig.if_point()
    want_a, _ = if_power_ref([-16384], 0, 4, 5, 4, 1)
    want_b, _ = if_power_ref([16384], 0, 4, 5, 4, 1)
    assert a & 0x0FFF_FFFF == want_a and b & 0x0FFF_FFFF == want_b


def test_pins_default_to_nothing_wired_and_follow_a_module_model():
    rig = Rig()
    rig.fe(src=2)
    assert rig.if_point() & 0x0FFF_FFFF == if_power_ref([0], 0, 4, 5, 4, 1)[0]       # tied to mid scale = 0
    rig.model.fe_pins = lambda n: (0xC00, False)
    assert rig.if_point() & 0x0FFF_FFFF == (8 << 22) | (0x3FFE0004 >> 8)
    rig.fe(src=3)                                              # 3 is the same as 2
    assert rig.if_point() & 0x0FFF_FFFF == (8 << 22) | (0x3FFE0004 >> 8)


def test_generator_stream_of_the_sample_generator_has_priority():
    rig = Rig()
    rig.fe(src=0)
    rig.wr("FE_TIE", 0xC00)
    rig.wr("GEN_CFG", (1 << 31) | (1 << 30) | (0 << 16) | 2)    # one-sample pattern, stream 1 via DET_CFG below
    rig.wr("GEN_ADDR", 0)
    rig.wr("GEN_DATA", 0)                                      # a zero pattern
    d = REGS["DET_CFG"].fields
    rig.wr("DET_CFG", d["mode"].put(1) | d["stream"].put(1) | d["src"].put(SRC_STREAM))
    rig.off.run(1)
    word = rig.result_word()
    assert word & 0x0FFF_FFFF == 0                             # the generator's zeros, not the tie-off constant


def test_status_counts_only_while_enabled_and_clear_resets():
    rig = Rig()
    assert rig.rd("FE_STAT") >> 16 == 0
    rig.fe(enable=0)
    rig.rd("FE_STAT")
    assert rig.rd("FE_STAT") >> 16 == 0
    rig.wr("FE_TIE", 0x234)
    rig.fe(enable=1, src=0)
    first = rig.rd("FE_STAT")
    second = rig.rd("FE_STAT")
    assert (first >> 16) == FE_TICK and (second >> 16) == 2 * FE_TICK
    assert first & 0xFFF == 0x234 and not first >> 12 & 1
    rig.wr("FE_CFG", rig.rd("FE_CFG") | 1 << 6)
    assert rig.rd("FE_STAT") >> 16 == FE_TICK                  # counted again from zero (the read itself ticks)


def test_otr_seen_is_sticky_until_cleared_ramp_reaches_it():
    rig = Rig()
    rig.fe(src=1, tg_mode=0)                                   # ramp: OTR high on code 4095
    seen = 0
    for _ in range(4096 // FE_TICK + 2):
        seen = rig.rd("FE_STAT") >> 13 & 1
    assert seen == 1
    rig.fe(src=0)
    assert rig.rd("FE_STAT") >> 13 & 1 == 1                    # sticky
    rig.wr("FE_CFG", rig.rd("FE_CFG") | 1 << 6)
    assert rig.rd("FE_STAT") >> 13 & 1 == 0


def test_walking_one_and_ramp_codes_are_what_the_testbench_expects():
    rig = Rig()
    rig.fe(src=1, tg_mode=1)
    assert [rig.model._fe_sample(n)[0] for n in range(14)] == [1 << (n % 12) for n in range(14)]
    rig.fe(src=1, tg_mode=0)
    assert [rig.model._fe_sample(n)[0] for n in (0, 1, 4095, 4096)] == [0, 1, 4095, 0]
    assert rig.model._fe_sample(4095)[1] and not rig.model._fe_sample(4094)[1]
    rig.wr("FE_TIE", 0x5A5)
    rig.fe(src=1, tg_mode=3)
    assert rig.model._fe_sample(77) == (0x5A5, False)


def test_a_small_core_and_large_r_do_not_blow_up():
    rig = Rig()
    rig.fe(src=1, tg_mode=2)
    word = rig.if_point(r=65535, shift=40, skip=3, n_avg=1, inc=TONE_INC)
    assert word >= 0                                           # built from a capped stream, still answers
