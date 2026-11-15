"""EBAZ4205 pin map: the DATA1, DATA2 and DATA3 connectors (2 x 10, 2.0 mm) as the SAdiy adapter uses them.

Same role as `pinmap.py` for the BeagleBone Black, and the same Pin / PinMap types, so the daemon's bench mode,
the GUI and `tools/gen_diagrams.py` read both the same way. No hardware access, no Qt.

Which net sits on which DATA2 pin comes from `NETS` in `pinmap.py` (column `ebaz`). The FPGA balls and the signal
names are copied from `zynq-ebaz/rtl/vivado/pins.toml`, the master list of the PCB and the XDC;
`tests/test_pinmap_ebaz.py` fails when the two disagree.

Pins are PL IOs. Only the DATA2 signals of the Phase 1 design (EMIO SPI0, I2C0 and GPIO) exist in the bitstream:
everything else is display-only. SPI and I2C are hardware controllers in the PS, wired to their pins in the
bitstream, so those pins can not be turned into GPIO (the backend has no pin mux, `can_mux` is False).
GPIO numbers are offsets on the Zynq gpiochip: EMIO line n is 54 + n (V1..V6 = 54..59, CE = 60, LD = 61).
"""
from __future__ import annotations

from typing import Dict, Optional, Tuple

from .pinmap import (BoardBlock, DISPLAY, Layout, NETS, Pin, PinMap, _access, _category, _short,
                     ATT_NETS)

HEADERS = ("DATA1", "DATA2", "DATA3")

# FPGA ball of every usable connector pin (14 per connector; 1 and 2 supply, 3 4 12 ground, 10 NC).
BALLS: Dict[str, Dict[int, str]] = {
    "DATA1": {5: "A20", 6: "H16", 7: "B19", 8: "B20", 9: "C20", 11: "H17", 13: "D20", 14: "D18", 15: "H18",
              16: "D19", 17: "F20", 18: "E19", 19: "F19", 20: "K17"},
    "DATA2": {5: "G20", 6: "J18", 7: "G19", 8: "H20", 9: "J19", 11: "K18", 13: "K19", 14: "J20", 15: "L16",
              16: "L19", 17: "M18", 18: "L20", 19: "M20", 20: "L17"},
    "DATA3": {5: "M19", 6: "N20", 7: "P18", 8: "M17", 9: "N17", 11: "P20", 13: "R18", 14: "R19", 15: "P19",
              16: "T20", 17: "U20", 18: "T19", 19: "V20", 20: "U19"},
}

# Port names of the Phase 1 design (pins.toml) by DATA2 pin number.
DATA2_SIGNALS: Dict[int, str] = {
    5: "adf4351_clk", 7: "adf4351_dat", 8: "adf4351_le", 9: "adf4351_ld", 13: "adf4351_ce",
    14: "pe4302_v[0]", 15: "pe4302_v[1]", 16: "pe4302_v[2]", 17: "pe4302_v[3]", 18: "pe4302_v[4]",
    19: "pe4302_v[5]", 20: "i2c_scl", 11: "i2c_sda",
}

# DATA1 is reserved for the AD9226 module (Phase 4, not in the bitstream yet), except the three balls that the
# HelloFPGA adapter's LEDs use (pins.toml: led[0..2]; the LEDs can be freed only with a different adapter PCB).
DATA1_ROLES: Dict[int, str] = {
    5: "adc_d[0]", 6: "adc_otr", 7: "adc_d[1]", 8: "adc_d[2]", 9: "adc_d[3]", 11: "adc_d[11]", 13: "adc_d[4]",
    14: "adc_d[5]", 15: "led[0]", 16: "adc_d[6]", 17: "adc_d[7]", 18: "led[2]", 19: "adc_d[9]", 20: "led[1]",
}

# DATA3 pins that the adapter's display and keys occupy (Linux: PS SPI1 and EMIO GPIO), by pin number.
DATA3_ADAPTER: Dict[int, str] = {
    9: "lcd_res", 11: "lcd_sda", 13: "lcd_dc", 14: "lcd_scl", 15: "keys[1]", 16: "lcd_cs", 17: "keys[2]",
    18: "keys[0]", 19: "keys[4]", 20: "keys[3]",
}

SUPPLY = {1: ("VCC in (5 to 12 V)", "power"), 2: ("VCC in (5 to 12 V)", "power"), 3: ("GND", "gnd"),
          4: ("GND", "gnd"), 10: ("NC", "special"), 12: ("GND", "gnd")}

# EMIO line n of the Zynq gpiochip is 54 + n. LD is input only; V1..V6 and CE are outputs (tri-stated at boot).
EMIO_GPIO = {"ATT_V1": 54, "ATT_V2": 55, "ATT_V3": 56, "ATT_V4": 57, "ATT_V5": 58, "ATT_V6": 59,
             "SYN_CE": 60, "SYN_LD": 61}

PIN_NOTES = {
    "DATA2.9": "pulled down inside the FPGA, so a missing cable reads unlocked",
    "DATA2.11": "pulled up inside the FPGA",
    "DATA2.20": "pulled up inside the FPGA",
    "DATA2.13": "tri-stated until software drives it; the adapter jumper holds CE high",
}
for _n in range(14, 20):
    PIN_NOTES[f"DATA2.{_n}"] = "tri-stated at boot, the adapter's 2.2k pull-ups give 31.5 dB"


def _net_by_pin() -> Dict[str, dict]:
    return {n["ebaz"]: n for n in NETS if n.get("ebaz")}


def _build() -> Dict[str, Pin]:
    by_pin = _net_by_pin()
    out: Dict[str, Pin] = {}
    for header in HEADERS:
        for number in range(1, 21):
            pid = f"{header}.{number}"
            net = by_pin.get(pid)
            if number in SUPPLY:
                name, kind = SUPPLY[number]
            else:
                ball = BALLS[header][number]
                if header == "DATA2" and number in DATA2_SIGNALS:
                    name, kind = f"{ball}  {DATA2_SIGNALS[number]}", "free"
                elif header == "DATA1":
                    role = DATA1_ROLES[number]
                    what = "adapter LED" if role.startswith("led") else "AD9226, later"
                    name, kind = f"{ball}  {role} ({what})", "special"
                elif header == "DATA3" and number in DATA3_ADAPTER:
                    name, kind = f"{ball}  {DATA3_ADAPTER[number]} (adapter, Linux)", "special"
                elif header == "DATA2":
                    name, kind = f"{ball}  spare", "special"
                else:
                    name, kind = f"{ball}  PL IO, spare", "special"
            if net is not None:
                access, category = _access(kind, net), _category(kind, net)
            else:
                access, category = DISPLAY, {"power": "power", "gnd": "gnd"}.get(kind, "reserved")
            out[pid] = Pin(
                id=pid, header=header, number=number, name=name, kind=kind, access=access, category=category,
                short=_short(name, net) if net is not None else name.split("  ")[-1].split(" (")[0],
                gpio=EMIO_GPIO.get(net["id"]) if net else None, ain=None,
                net=net["id"] if net else None, board=net["dev"] if net else None,
                board_pin=net["dpin"] if net else None, direction=net["dir"] if net else None, mux=None,
                note=" ".join(x for x in ((net.get("note_ebaz", net["note"]) if net else ""), PIN_NOTES.get(pid, "")) if x),
            )
    return out


PINS: Dict[str, Pin] = _build()
BY_NET: Dict[str, Pin] = {p.net: p for p in PINS.values() if p.net}

BOARDS: Tuple[BoardBlock, ...] = (
    BoardBlock("PE4302", "attenuator, parallel only", ATT_NETS,
               ("VDD on two pads, 3.3 V", "2.2k pull-ups: open = 31.5 dB", "weights and polarity: verify")),
    BoardBlock("ADF4351", "LO, 25 MHz reference", ("SYN_LE", "SYN_DATA", "SYN_CLK", "SYN_LD", "SYN_CE"),
               ("PDR: tied high (JP5)", "CE: adapter jumper picks 3V3 or DATA2-13", "5 V jack; never feed 3V3 pin")),
    BoardBlock("ADS1115", "main ADC, I2C0 at 0x48", ("I2C_SCL", "I2C_SDA"),
               ("A0 from detector; GND: board GND",)),
)

_LEGEND = (
    ("spi", "SPI (PS SPI0)"), ("pe4302", "PE4302"), ("lock", "Lock detect"), ("synth", "ADF4351 CE"),
    ("i2c", "I2C (ADS1115)"), ("power", "Power in"), ("gnd", "Ground"),
    ("reserved", "AD9226 later / NC / spare"),
)

# DATA2 leftmost: every wire runs left to the boards, none crosses another connector.
EBAZ = PinMap(
    name="ebaz", label="EBAZ4205", pins=PINS, by_net=BY_NET, boards=BOARDS,
    layout=Layout(
        headers=(("DATA2", 270.0, 58.0), ("DATA1", 460.0, 58.0), ("DATA3", 650.0, 58.0)), rows=10,
        board_rect=(232.0, 8.0, 600.0, 58.0 + 10 * 23.0 - 2), board_title="EBAZ4205",
        canvas=(850.0, 700.0),
        blocks=(("PE4302", 8, 60, 214, True), ("ADF4351", 8, 300, 214, True), ("ADS1115", 8, 516, 214, True)),
        legend=_LEGEND,
    ),
)
