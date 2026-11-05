import pytest

from sadiy.drivers.adc import Ads1115
from sadiy.hal.fake import FakeAds1115


def make(volts=(1.0, 0.5, 0.0, -0.25), **kw):
    fake = FakeAds1115(volts)
    return Ads1115(fake, sleep=lambda s: None, **kw), fake


def test_config_word_single_shot_on_channel_comparator_off():
    dev, _ = make()
    word = dev.config_word(0)
    assert word >> 15 == 1                 # start
    assert (word >> 12) & 7 == 0b100       # AIN0 to GND
    assert (word >> 9) & 7 == 0b001        # +-4.096 V
    assert (word >> 8) & 1 == 1            # single shot
    assert (word >> 5) & 7 == 0b100        # 128 SPS
    assert word & 0b11 == 0b11             # comparator off
    assert (dev.config_word(3) >> 12) & 7 == 0b111


def test_conversion_to_volts():
    dev, _ = make()
    assert dev.read_volts() == pytest.approx(1.0, abs=2e-4)
    assert dev.to_volts(dev.convert(1)) == pytest.approx(0.5, abs=2e-4)
    assert dev.convert(2) == 0


def test_negative_codes_are_signed():
    dev, _ = make()
    assert dev.convert(3) < 0
    assert dev.to_volts(dev.convert(3)) == pytest.approx(-0.25, abs=2e-4)


def test_register_access_is_big_endian_with_pointer_first():
    dev, fake = make()
    dev.write_register(Ads1115.REG_CONFIG, 0x1234)
    assert fake.writes[-1] == bytes([1, 0x12, 0x34])
    assert dev.read_register(Ads1115.REG_CONFIG) == 0x1234
    assert fake.writes[-1] == bytes([1])


def test_power_on_config_register():
    dev, _ = make()
    assert dev.read_register(Ads1115.REG_CONFIG) == 0x8583


def test_full_scale_and_rate_are_checked():
    fake = FakeAds1115()
    with pytest.raises(ValueError):
        Ads1115(fake, full_scale_v=3.3)
    with pytest.raises(ValueError):
        Ads1115(fake, sps=100)
    with pytest.raises(ValueError):
        Ads1115(fake).config_word(4)


def test_timeout_when_never_ready():
    class Stuck(FakeAds1115):
        def read(self, count):
            return b"\x00\x00"

    with pytest.raises(TimeoutError):
        Ads1115(Stuck(), sleep=lambda s: None).convert(0)
