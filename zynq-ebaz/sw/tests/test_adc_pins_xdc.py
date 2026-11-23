"""The prepared AD9226 pad constraints (rtl/fpga/constraints/adc_pins.xdc) follow pins.toml, and the board top has the ports."""
import re
import tomllib
from pathlib import Path

EBAZ = Path(__file__).resolve().parents[2]
XDC = EBAZ / "rtl" / "fpga" / "constraints" / "adc_pins.xdc"
TOP = EBAZ / "rtl" / "fpga" / "ebaz_sadiy_top.sv"
PINS = EBAZ / "rtl" / "vivado" / "pins.toml"


def _xdc_balls():
    out = {}
    for m in re.finditer(r"^set_property -dict \{PACKAGE_PIN (\w+) IOSTANDARD LVCMOS33[^}]*\} \[get_ports \{?([\w\[\]]+)\}?\]", XDC.read_text(), re.M):
        out[m.group(2)] = m.group(1)
    return out


def test_every_adc_signal_has_the_ball_of_pins_toml():
    toml = {s["name"]: s["ball"] for s in tomllib.loads(PINS.read_text())["signal"] if s["name"].startswith("adc_")}
    xdc = _xdc_balls()
    assert set(xdc) == {f"adc_d[{i}]" for i in range(12)} | {"adc_otr", "adc_clk"}
    for name, ball in xdc.items():
        if name in toml:
            assert toml[name] == ball, name
    # adc_d[8], adc_d[10] and adc_clk are LED balls on the first adapter and carry other names in pins.toml
    leds = {s["ball"]: s["name"] for s in tomllib.loads(PINS.read_text())["signal"]}
    for name in ("adc_d[8]", "adc_d[10]", "adc_clk"):
        assert xdc[name] in leds


def test_no_ball_is_used_twice():
    xdc = _xdc_balls()
    assert len(set(xdc.values())) == len(xdc)


def test_the_ports_exist_only_in_an_adc_pads_build():
    text = TOP.read_text()
    block = text[text.index("`ifdef ADC_PADS"):text.index("`endif")]
    for port in ("adc_clk", "adc_d", "adc_otr"):
        assert port in block
    assert "12'h800" in text and "fe_pad_d" in text            # the default build ties the data lines to mid scale
