"""BeagleBone Black pin map: the one place that says which pin does what.

`tools/gen_diagrams.py` (netlist and diagrams), `server/bench.py` (what may be driven) and the GUI
(the clickable board) all read this module, so they cannot disagree. No hardware access, no Qt.

The map is a proposal until it is verified on a real image (overlays, `config-pin`). Pin names come
from the BBB system reference. GPIO number = bank * 32 + bit (GPIO1_28 = 60). That is not always the number
sysfs uses: `hal/linux.py` translates it for the running kernel.
"""
from __future__ import annotations

import re
from dataclasses import dataclass
from typing import Dict, Optional, Tuple

# One entry per SBC-to-board signal. bbb is a P9 pin number or a string like "P8.7"; rpi is the physical
# pin (None = not used there). mux is the `config-pin` mode of a bus pin, restored when it stops being a GPIO.
NETS = [
    dict(id="SYN_CLK", dev="ADF4351", dpin="CLK", kind="spi", dir="SBC to board", bbb=22, rpi=23, mux="spi_sclk",
         note="SPI mode 0, MSB first"),
    dict(id="SYN_DATA", dev="ADF4351", dpin="DAT", kind="spi", dir="SBC to board", bbb=18, rpi=19, mux="spi",
         note="32-bit words"),
    dict(id="SYN_LE", dev="ADF4351", dpin="LE", kind="spi", dir="SBC to board", bbb=17, rpi=24, mux="spi_cs",
         note="used as SPI chip select; data latches on the rising edge at the end of a transfer"),
    dict(id="SYN_LD", dev="ADF4351", dpin="LD", kind="gpio", dir="board to SBC", bbb=23, rpi=35,
         note="digital lock detect output (Lock_Flag LED on the board), GPIO input; the MUX pin stays unused"),
    dict(id="SYN_CE", dev="ADF4351", dpin="CE", kind="reserved", dir="SBC to board", bbb=27, rpi=36,
         note="optional; tie the CE header pin to 3V3 until needed"),
    dict(id="ATT_V1", dev="PE4302", dpin="V1 (0.5 dB)", kind="gpio", dir="SBC to board", bbb="P8.7", rpi=29,
         note="assumed weight; verify order and polarity with pe4302-walk"),
    dict(id="ATT_V2", dev="PE4302", dpin="V2 (1 dB)", kind="gpio", dir="SBC to board", bbb="P8.8", rpi=31,
         note="assumed 1 dB stage"),
    dict(id="ATT_V3", dev="PE4302", dpin="V3 (2 dB)", kind="gpio", dir="SBC to board", bbb="P8.9", rpi=32,
         note="assumed 2 dB stage"),
    dict(id="ATT_V4", dev="PE4302", dpin="V4 (4 dB)", kind="gpio", dir="SBC to board", bbb="P8.10", rpi=33,
         note="assumed 4 dB stage"),
    dict(id="ATT_V5", dev="PE4302", dpin="V5 (8 dB)", kind="gpio", dir="SBC to board", bbb="P8.11", rpi=38,
         note="assumed 8 dB stage"),
    dict(id="ATT_V6", dev="PE4302", dpin="V6 (16 dB)", kind="gpio", dir="SBC to board", bbb="P8.12", rpi=40,
         note="assumed 16 dB stage"),
    dict(id="DET_ADC", dev="Detector", dpin="VOUT via divider", kind="analog", dir="board to SBC", bbb=39,
         rpi=None, note="BBB: AIN0 through the divider, a cross-check only (the ADS1115 is the main ADC); 0 to 1.8 V absolute maximum. RPi: ADS1115 only"),
    dict(id="ADC_GND", dev="Detector", dpin="GND", kind="gnd", dir="return", bbb=34, rpi=None,
         note="optional, AIN0 cross-check only"),
    dict(id="I2C_SDA", dev="ADS1115", dpin="SDA", kind="i2c", dir="bidirectional", bbb=20, rpi=3, mux="i2c",
         note="main ADC on both platforms. BBB: I2C2 on the adapter board, which already has pull-ups (4.7k on the adapter not fitted)"),
    dict(id="I2C_SCL", dev="ADS1115", dpin="SCL", kind="i2c", dir="SBC to board", bbb=19, rpi=5, mux="i2c",
         note="main ADC on both platforms. BBB: I2C2 on the adapter board"),
]

BBB_P9 = {
    1: ("GND", "gnd"), 2: ("GND", "gnd"), 3: ("DC_3.3V", "power"), 4: ("DC_3.3V", "power"),
    5: ("VDD_5V", "power"), 6: ("VDD_5V", "power"), 7: ("SYS_5V", "power"), 8: ("SYS_5V", "power"),
    9: ("PWR_BUT", "special"), 10: ("SYS_RESETn", "special"),
    11: ("GPIO0_30 / UART4_RX", "free"), 12: ("GPIO1_28", "free"), 13: ("GPIO0_31 / UART4_TX", "free"),
    14: ("GPIO1_18 / EHRPWM1A", "free"), 15: ("GPIO1_16", "free"), 16: ("GPIO1_19 / EHRPWM1B", "free"),
    17: ("SPI0_CS0 / GPIO0_5", "free"), 18: ("SPI0_D1 (MOSI) / GPIO0_4", "free"),
    19: ("I2C2_SCL / GPIO0_13", "free"), 20: ("I2C2_SDA / GPIO0_12", "free"),
    21: ("SPI0_D0 (MISO) / GPIO0_3", "free"), 22: ("SPI0_SCLK / GPIO0_2", "free"), 23: ("GPIO1_17", "free"),
    24: ("UART1_TX / GPIO0_15", "free"), 25: ("GPIO3_21", "free"), 26: ("UART1_RX / GPIO0_14", "free"),
    27: ("GPIO3_19", "free"), 28: ("SPI1_CS0 / GPIO3_17", "free"), 29: ("SPI1_D0 / GPIO3_15", "free"),
    30: ("SPI1_D1 / GPIO3_16", "free"), 31: ("SPI1_SCLK / GPIO3_14", "free"),
    32: ("VDD_ADC (1.8 V ref)", "power"), 33: ("AIN4", "analog"), 34: ("GNDA_ADC", "gnd"),
    35: ("AIN6", "analog"), 36: ("AIN5", "analog"), 37: ("AIN2", "analog"), 38: ("AIN3", "analog"),
    39: ("AIN0", "analog"), 40: ("AIN1", "analog"), 41: ("GPIO0_20 / CLKOUT2", "free"),
    42: ("GPIO0_7 / ECAPPWM0", "free"), 43: ("GND", "gnd"), 44: ("GND", "gnd"), 45: ("GND", "gnd"),
    46: ("GND", "gnd"),
}

BBB_P8 = {
    1: ("GND", "gnd"), 2: ("GND", "gnd"),
    3: ("GPIO1_6 (eMMC)", "special"), 4: ("GPIO1_7 (eMMC)", "special"), 5: ("GPIO1_2 (eMMC)", "special"),
    6: ("GPIO1_3 (eMMC)", "special"),
    7: ("GPIO2_2 / TIMER4", "free"), 8: ("GPIO2_3 / TIMER7", "free"), 9: ("GPIO2_5 / TIMER5", "free"),
    10: ("GPIO2_4 / TIMER6", "free"), 11: ("GPIO1_13 / PRU0 R30_15", "free"), 12: ("GPIO1_12 / PRU0 R30_14", "free"),
    13: ("GPIO0_23 / EHRPWM2B", "free"), 14: ("GPIO0_26", "free"), 15: ("GPIO1_15 / PRU0 R31_15", "free"),
    16: ("GPIO1_14 / PRU0 R31_14", "free"), 17: ("GPIO0_27", "free"), 18: ("GPIO2_1", "free"),
    19: ("GPIO0_22 / EHRPWM2A", "free"),
    20: ("GPIO1_31 (eMMC cmd)", "special"), 21: ("GPIO1_30 (eMMC clk)", "special"), 22: ("GPIO1_5 (eMMC)", "special"),
    23: ("GPIO1_4 (eMMC)", "special"), 24: ("GPIO1_1 (eMMC)", "special"), 25: ("GPIO1_0 (eMMC)", "special"),
    26: ("GPIO1_29", "free"),
    27: ("GPIO2_22 (HDMI/LCD)", "special"), 28: ("GPIO2_24 (HDMI/LCD)", "special"), 29: ("GPIO2_23 (HDMI/LCD)", "special"),
    30: ("GPIO2_25 (HDMI/LCD)", "special"), 31: ("GPIO0_10 (HDMI/LCD)", "special"), 32: ("GPIO0_11 (HDMI/LCD)", "special"),
    33: ("GPIO0_9 (HDMI/LCD)", "special"), 34: ("GPIO2_17 (HDMI/LCD)", "special"), 35: ("GPIO0_8 (HDMI/LCD)", "special"),
    36: ("GPIO2_16 (HDMI/LCD)", "special"), 37: ("GPIO2_14 (HDMI/LCD)", "special"), 38: ("GPIO2_15 (HDMI/LCD)", "special"),
    39: ("GPIO2_12 (HDMI/LCD)", "special"), 40: ("GPIO2_13 (HDMI/LCD)", "special"), 41: ("GPIO2_10 (HDMI/LCD)", "special"),
    42: ("GPIO2_11 (HDMI/LCD)", "special"), 43: ("GPIO2_8 (HDMI/LCD)", "special"), 44: ("GPIO2_9 (HDMI/LCD)", "special"),
    45: ("GPIO2_6 (HDMI/LCD)", "special"), 46: ("GPIO2_7 (HDMI/LCD)", "special"),
}

# ----------------------------------------------------------------------------- what a pin may do
WIRED = "wired_output"   # goes to a board input: may be driven, after a confirm step
INPUT_ONLY = "input"     # a board drives it (lock detect): read only
ANALOG = "analog"        # ADC input: read through the ADC only, never a GPIO
EXPERT = "expert"        # free GPIO, not wired to anything of ours: locked behind the expert switch
DISPLAY = "display"      # power, ground, eMMC, HDMI, reset: shown, never touched

# Things worth knowing about a pin that are not in the name. From the BBB system reference, VERIFY.
PIN_NOTES = {
    "P9.19": "I2C2 is also the bus the BBB uses to probe cape EEPROMs",
    "P9.20": "I2C2 is also the bus the BBB uses to probe cape EEPROMs",
    "P9.25": "used by HDMI audio when HDMI is enabled",
    "P9.28": "used by HDMI audio when HDMI is enabled",
    "P9.29": "used by HDMI audio when HDMI is enabled",
    "P9.31": "used by HDMI audio when HDMI is enabled",
    "P9.41": "two SoC balls share this pin (GPIO0_20 and GPIO3_20): check the other is an input",
    "P9.42": "two SoC balls share this pin (GPIO0_7 and GPIO3_18): check the other is an input",
    "P9.32": "1.8 V ADC reference: do not load it",
}


@dataclass(frozen=True)
class Pin:
    id: str                       # "P9.22"
    header: str                   # "P8" or "P9"
    number: int                   # 1..46
    name: str                     # "SPI0_SCLK / GPIO0_2"
    kind: str                     # the column of BBB_P8 / BBB_P9: free, gnd, power, special, analog
    access: str                   # WIRED, INPUT_ONLY, ANALOG, EXPERT or DISPLAY
    category: str                 # colour on the clickable board: spi, pe4302, lock, synth, adc, i2c, gnd, power, reserved, free
    short: str                    # label next to the pin
    gpio: Optional[int] = None    # bank * 32 + bit
    ain: Optional[int] = None     # AIN channel
    net: Optional[str] = None
    board: Optional[str] = None
    board_pin: Optional[str] = None
    direction: Optional[str] = None
    mux: Optional[str] = None     # `config-pin` mode when it is not a GPIO
    note: str = ""

    @property
    def config_pin_name(self) -> str:
        return f"{self.header}_{self.number:02d}"

    @property
    def signal(self) -> str:
        """Name in patterns and CSV files: the net, or the pin id for a pin without a net."""
        return self.net or self.id


def pin_id(bbb) -> str:
    """P9 pin number (int) or a string like 'P8.7' -> 'P8.7'."""
    return bbb if isinstance(bbb, str) else f"P9.{bbb}"


def _kernel_gpio(name: str) -> Optional[int]:
    m = re.search(r"GPIO(\d)_(\d+)", name)
    return int(m.group(1)) * 32 + int(m.group(2)) if m else None


def _ain_channel(name: str) -> Optional[int]:
    m = re.fullmatch(r"AIN(\d)", name)
    return int(m.group(1)) if m else None


def _access(kind: str, net: Optional[dict]) -> str:
    if kind == "analog":
        return ANALOG
    if kind in ("gnd", "power", "special"):
        return DISPLAY
    if net is None:
        return EXPERT
    return INPUT_ONLY if net["dir"] == "board to SBC" else WIRED


def _category(kind: str, net: Optional[dict]) -> str:
    if net is not None:
        if net["dev"] == "PE4302":
            return "pe4302"
        if net["id"] == "SYN_LD":
            return "lock"
        if net["id"] == "SYN_CE":
            return "synth"
        if net["kind"] in ("spi", "i2c"):
            return net["kind"]
        if net["id"] == "DET_ADC":
            return "adc"
    return {"analog": "adc", "gnd": "gnd", "power": "power", "special": "reserved"}.get(kind, "free")


def _short(name: str, net: Optional[dict]) -> str:
    if net is not None:
        return net["id"]
    for tag in ("eMMC", "HDMI"):
        if tag in name:
            return tag
    return name.split(" / ")[0].split(" (")[0]


def _build() -> Dict[str, Pin]:
    by_pin = {pin_id(n["bbb"]): n for n in NETS if n["bbb"]}
    out: Dict[str, Pin] = {}
    for header, table in (("P8", BBB_P8), ("P9", BBB_P9)):
        for number, (name, kind) in table.items():
            pid = f"{header}.{number}"
            net = by_pin.get(pid)
            out[pid] = Pin(
                id=pid, header=header, number=number, name=name, kind=kind,
                access=_access(kind, net), category=_category(kind, net), short=_short(name, net),
                gpio=_kernel_gpio(name), ain=_ain_channel(name),
                net=net["id"] if net else None, board=net["dev"] if net else None,
                board_pin=net["dpin"] if net else None, direction=net["dir"] if net else None,
                mux=net.get("mux") if net else None,
                note=" ".join(x for x in (net["note"] if net else "", PIN_NOTES.get(pid, "")) if x),
            )
    return out


PINS: Dict[str, Pin] = _build()
BY_NET: Dict[str, Pin] = {p.net: p for p in PINS.values() if p.net}

ATT_NETS: Tuple[str, ...] = tuple(f"ATT_V{i}" for i in range(1, 7))
SPI_NETS: Tuple[str, ...] = ("SYN_CLK", "SYN_DATA", "SYN_LE")
I2C_NETS: Tuple[str, ...] = ("I2C_SCL", "I2C_SDA")
LOCK_NET = "SYN_LD"
CE_NET = "SYN_CE"


def find(name: str) -> Pin:
    """Look a pin up by id ("P8.7") or by net ("ATT_V1"). KeyError when there is no such pin."""
    pin = PINS.get(name) or BY_NET.get(name)
    if pin is None:
        raise KeyError(f"no pin or net called {name!r}")
    return pin


@dataclass(frozen=True)
class BoardBlock:
    """One controllable board as drawn next to the BBB: the nets it has and its static straps."""

    title: str
    subtitle: str
    nets: Tuple[str, ...]
    straps: Tuple[str, ...] = ()


BOARDS: Tuple[BoardBlock, ...] = (
    BoardBlock("PE4302", "attenuator, parallel only", ATT_NETS,
               ("VDD on two pads, 3.3 V", "2.2k pull-ups: open = 31.5 dB", "weights and polarity: verify")),
    BoardBlock("ADF4351", "LO, 25 MHz reference", ("SYN_LE", "SYN_DATA", "SYN_CLK", "SYN_LD", "SYN_CE"),
               ("PDR: tied high (JP5)", "CE: J12 jumper picks 3V3 or P9.27", "5 V jack; never feed 3V3 pin")),
    BoardBlock("ADS1115", "main ADC, I2C2 at 0x48", ("I2C_SCL", "I2C_SDA"),
               ("A0 from detector; GND: board GND",)),
    BoardBlock("AIN0", "optional on-chip cross-check", ("ADC_GND", "DET_ADC"),
               ("Detector via divider 0.751",)),
)
