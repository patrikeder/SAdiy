import re

import pytest

from sadiy import config, pinmap


def test_all_pins_present():
    assert len(pinmap.PINS) == 92
    assert {p.header for p in pinmap.PINS.values()} == {"P8", "P9"}


@pytest.mark.parametrize("net, pin, gpio", [
    ("ATT_V1", "P8.7", 66), ("ATT_V2", "P8.8", 67), ("ATT_V3", "P8.9", 69), ("ATT_V4", "P8.10", 68),
    ("ATT_V5", "P8.11", 45), ("ATT_V6", "P8.12", 44), ("SYN_LD", "P9.23", 49), ("SYN_CE", "P9.27", 115),
    ("SYN_CLK", "P9.22", 2), ("SYN_DATA", "P9.18", 4), ("SYN_LE", "P9.17", 5),
    ("I2C_SCL", "P9.19", 13), ("I2C_SDA", "P9.20", 12),
])
def test_nets_and_kernel_numbers(net, pin, gpio):
    p = pinmap.BY_NET[net]
    assert (p.id, p.gpio) == (pin, gpio)
    assert pinmap.find(net) is p and pinmap.find(pin) is p


def test_config_gpio_list_matches_the_pin_map():
    assert config.load()["attenuator"]["gpio_bbb"] == [pinmap.BY_NET[n].gpio for n in pinmap.ATT_NETS]


def test_access_rules():
    assert pinmap.PINS["P8.7"].access == pinmap.WIRED
    assert pinmap.PINS["P9.22"].access == pinmap.WIRED
    assert pinmap.PINS["P9.23"].access == pinmap.INPUT_ONLY
    assert pinmap.PINS["P9.39"].access == pinmap.ANALOG
    assert pinmap.PINS["P9.33"].access == pinmap.ANALOG
    assert pinmap.PINS["P9.15"].access == pinmap.EXPERT
    for display in ("P8.1", "P8.3", "P8.20", "P8.27", "P9.3", "P9.5", "P9.9", "P9.32", "P9.34", "P9.46"):
        assert pinmap.PINS[display].access == pinmap.DISPLAY


def test_no_free_pin_lost_its_gpio_number():
    for pin in pinmap.PINS.values():
        if pin.access in (pinmap.WIRED, pinmap.EXPERT, pinmap.INPUT_ONLY):
            assert pin.gpio is not None, pin.id


def test_config_pin_name():
    assert pinmap.PINS["P8.7"].config_pin_name == "P8_07"
    assert pinmap.PINS["P9.22"].config_pin_name == "P9_22"


def test_bus_pins_know_their_mux_mode():
    assert [pinmap.BY_NET[n].mux for n in pinmap.SPI_NETS] == ["spi_sclk", "spi", "spi_cs"]
    assert [pinmap.BY_NET[n].mux for n in pinmap.I2C_NETS] == ["i2c", "i2c"]


def test_boards_cover_every_bbb_net():
    drawn = {n for b in pinmap.BOARDS for n in b.nets}
    assert drawn == {n["id"] for n in pinmap.NETS if n["bbb"]}


def test_netlist_is_generated_from_this_map():
    from pathlib import Path

    text = (Path(__file__).resolve().parents[1] / "hw" / "netlist.md").read_text()
    for pin in pinmap.BY_NET.values():
        row = re.search(rf"^\| {pin.net} \|.*$", text, re.M)
        assert row and f"{pin.id} " in row.group(0)


def test_gnda_adc_belongs_to_the_ain0_cross_check_only():
    assert pinmap.BY_NET["ADC_GND"].note == "optional, AIN0 cross-check only"
    by = {b.title: b for b in pinmap.BOARDS}
    assert by["ADS1115"].nets == ("I2C_SCL", "I2C_SDA")
    assert set(by["AIN0"].nets) == {"DET_ADC", "ADC_GND"}


def test_i2c_nets_are_not_described_as_rpi_only():
    for net in pinmap.I2C_NETS:
        assert "RPi only" not in pinmap.BY_NET[net].note
