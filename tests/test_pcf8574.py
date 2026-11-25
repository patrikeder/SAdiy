"""The PCF8574 behind which the PE4302 sits: port mapping, one-write make-before-break, the line view of it."""
import pytest

from sadiy.drivers import pcf8574
from sadiy.drivers.pcf8574 import Pcf8574, levels_of, port_byte
from sadiy.drivers.pe4302 import PE4302, PE4302Pcf8574
from sadiy.hal.fake import FakePcf8574


def attenuation(byte, active_high=True):
    on = 1 if active_high else 0
    levels = levels_of(byte)
    return sum(w for i, w in enumerate((0.5, 1, 2, 4, 8, 16)) if (levels >> i) & 1 == on)


def make(**kw):
    chip = FakePcf8574()
    return PE4302Pcf8574(Pcf8574(chip), **kw), chip


def test_port_mapping_is_the_users_wiring():
    """V1..V3 on P0..P2, V4..V6 on P4..P6, P3 the backlight, P7 spare."""
    for i, bit in enumerate((0, 1, 2, 4, 5, 6)):
        assert port_byte(1 << i, p3=0, p7=0) == 1 << bit
    assert port_byte(0, p3=1, p7=0) == 0x08 and port_byte(0, p3=0, p7=1) == 0x80
    assert port_byte(0x3F) == 0xFF
    for levels in range(64):
        assert levels_of(port_byte(levels, 0, 0)) == levels and levels_of(port_byte(levels)) == levels


def test_starts_at_maximum_attenuation_with_the_backlight_on():
    dev, chip = make()
    assert chip.writes == [b"\xff"] and dev.attenuation_db == 31.5


@pytest.mark.parametrize("active_high", [True, False])
def test_every_change_is_one_write_that_never_goes_below_old_and_new(active_high):
    dev, chip = make(active_high=active_high)
    for old in range(64):
        for new in range(64):
            dev.set_attenuation(old * 0.5)
            del chip.writes[:]
            dev.set_attenuation(new * 0.5)
            assert len(chip.writes) == 1 and 1 <= len(chip.writes[0]) <= 2
            seen = [attenuation(b, active_high) for b in chip.writes[0]]
            assert min(seen) >= min(old, new) * 0.5 and seen[-1] == new * 0.5
            assert (len(chip.writes[0]) == 1) == (old & new == old)      # one byte when stages only switch in
            assert all(b & 0x88 == 0x88 for b in chip.writes[0])         # backlight and P7 stay


def test_apply_lines_keeps_the_others_and_makes_before_it_breaks():
    dev, chip = make()
    dev.set_attenuation(15.5)
    del chip.writes[:]
    dev.apply_lines({5: 1, 0: 0})                    # V6 in, V1 out
    assert chip.writes == [bytes([0xFF, port_byte(0x3E)])] and dev.attenuation_db == 31.0
    del chip.writes[:]
    dev.apply_lines({5: 1})                          # nothing changes: nothing sent
    assert chip.writes == [] and dev.last_bytes == []


def test_raw_levels_and_readback():
    dev, chip = make()
    dev.set_levels(0b100000)
    assert dev.last_bytes == [port_byte(0x20)] and dev.attenuation_db == 16.0 and dev.readback_matches()
    chip.port = port_byte(0x01)                      # somebody else
    assert not dev.readback_matches() and dev.sync_from_lines() == 0.5
    dev.set_attenuation(2.0)
    dev.write_current()
    assert chip.port == port_byte(0x04)


def test_the_plain_driver_works_on_the_expander_lines_too():
    """tools/bringup.py pe4302-walk and the PL backend use six lines."""
    chip = FakePcf8574()
    port = Pcf8574(chip)
    dev = PE4302(pcf8574.lines(port))
    dev.set_attenuation(5.0)
    assert attenuation(chip.port) == 5.0 and [ln.read() for ln in pcf8574.lines(port)] == [0, 1, 0, 1, 0, 0]
    line = pcf8574.lines(port)[0]
    line.set_direction(False)                        # released = written high
    assert line.read() == 1 and line.direction() == "out"


def test_no_acknowledge_and_empty_write():
    chip = FakePcf8574()
    chip.present = False
    with pytest.raises(OSError):
        PE4302Pcf8574(Pcf8574(chip))
    with pytest.raises(ValueError):
        Pcf8574(FakePcf8574()).write()
