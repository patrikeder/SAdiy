import pytest

from sadiy import config
from sadiy.core.freqplan import DIVIDERS
from sadiy.drivers.adf4351 import AUX, MAIN, Adf4351, Output, Outputs, default_band_select_div, pack_r4
from sadiy.hal.fake import FakeSpi

MAIN_EN, AUX_EN = 1 << 5, 1 << 8


def words(spi):
    return [int.from_bytes(b, "big") for b in spi.sent]


def make():
    spi = FakeSpi()
    return Adf4351(spi, 25e6), spi


def test_everything_is_off_by_default():
    assert Outputs() == Outputs(Output(False), Output(False))
    assert pack_r4(1, Outputs(), 200) & (MAIN_EN | AUX_EN) == 0


def test_constructor_writes_one_r4_word_with_both_outputs_off():
    dev, spi = make()
    w = words(spi)
    assert len(w) == 1
    assert w[0] & 0b111 == 0b100                      # register 4
    assert w[0] & (MAIN_EN | AUX_EN) == 0
    assert w[0] == 0x008C8004                         # fundamental feedback, /1, band select div 200, off
    assert dev.outputs == Outputs()


def test_known_word_matches_the_usual_adi_r4():
    # main output on at +5 dBm, divider 1, band select divider 200 (25 MHz PFD): the R4 value
    # 0x008C803C as I recall it from ADI's evaluation software (VERIFY).
    assert pack_r4(1, Outputs(main=Output(True, 5)), 200) == 0x008C803C


def test_field_positions():
    assert pack_r4(2, Outputs(), 80) == 0x00950004
    # divider code is log2(rf_div) in bits 22:20, one code per allowed divider
    for i, div in enumerate(DIVIDERS):
        assert (pack_r4(div, Outputs(), 200) >> 20) & 0b111 == i
    # band select divider in bits 19:12
    assert (pack_r4(1, Outputs(), 77) >> 12) & 0xFF == 77
    # aux: enable bit 8, power code in bits 7:6
    assert pack_r4(1, Outputs(aux=Output(True, -1)), 200) == 0x008C8004 | AUX_EN | (1 << 6)
    # main: enable bit 5, power code in bits 4:3
    assert pack_r4(1, Outputs(main=Output(True, 2)), 200) == 0x008C8004 | MAIN_EN | (2 << 3)


def test_outputs_are_independent():
    dev, spi = make()
    dev.enable_output(MAIN, 5)
    assert dev.outputs.main.enabled and not dev.outputs.aux.enabled
    assert words(spi)[-1] & MAIN_EN and not words(spi)[-1] & AUX_EN
    dev.enable_output(AUX, -4)
    assert words(spi)[-1] & MAIN_EN and words(spi)[-1] & AUX_EN
    dev.disable_output(MAIN)
    assert not words(spi)[-1] & MAIN_EN and words(spi)[-1] & AUX_EN
    dev.disable_outputs()
    assert words(spi)[-1] & (MAIN_EN | AUX_EN) == 0
    assert dev.outputs == Outputs()


def test_each_change_is_one_r4_write():
    dev, spi = make()
    n = len(spi.sent)
    dev.enable_output(MAIN, -1)
    dev.disable_output(MAIN)
    assert len(spi.sent) == n + 2
    assert all(w & 0b111 == 0b100 for w in words(spi))


def test_r4_follows_the_last_divider_and_keeps_the_output_state():
    dev, spi = make()
    dev.enable_output(MAIN, 5)
    dev._rf_div = 8                                   # as tune() does once register packing exists
    assert dev.r4_word() == pack_r4(8, Outputs(main=Output(True, 5)), dev.band_select_div)
    assert dev.r4_word() & MAIN_EN


def test_validation():
    dev, _ = make()
    with pytest.raises(ValueError):
        Output(True, 0)                               # not a power step
    with pytest.raises(ValueError):
        dev.enable_output("aux2")
    with pytest.raises(ValueError):
        pack_r4(3, Outputs(), 200)                    # not a divider
    with pytest.raises(ValueError):
        pack_r4(1, Outputs(), 0)
    with pytest.raises(ValueError):
        default_band_select_div(40e6)                 # would need a divider above 255


def test_default_band_select_divider_for_25_mhz():
    assert default_band_select_div(25e6) == 200       # 125 kHz


def test_config_missing_keys_mean_off():
    assert Outputs.from_config({}) == Outputs()
    assert Outputs.from_config({"out_power_dbm": 5}) == Outputs(main=Output(False, 5))


def test_default_config_enables_only_the_main_output():
    o = Outputs.from_config(config.load()["synth"])
    assert o.main.enabled and o.main.power_dbm == -4
    assert not o.aux.enabled


def test_a_construction_from_config_does_not_enable_anything():
    # the requested outputs are only applied by an explicit call, never by constructing the driver
    spi = FakeSpi()
    dev = Adf4351(spi, config.load()["synth"]["pfd_hz"])
    assert dev.outputs == Outputs()
    assert words(spi)[-1] & (MAIN_EN | AUX_EN) == 0
    dev.set_outputs(Outputs.from_config(config.load()["synth"]))
    assert words(spi)[-1] & MAIN_EN and not words(spi)[-1] & AUX_EN
