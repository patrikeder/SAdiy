#!/usr/bin/env python3
"""Generate the wiring diagrams (SVG + PNG) and hw/netlist.md from one pin map.

    python tools/gen_diagrams.py            # SVG + PNG (PNG needs rsvg-convert or cairosvg)
    python tools/gen_diagrams.py --no-png   # SVG and netlist only

Edit src/sadiy/pinmap.py (NETS, BBB_P8, BBB_P9) or STRAPS below when the wiring changes, then regenerate.
Do not edit the output files.
"""
from __future__ import annotations

import argparse
import shutil
import subprocess
import sys
from pathlib import Path
from xml.sax.saxutils import escape

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "src"))

from sadiy.pinmap import BBB_P8, BBB_P9, NETS  # noqa: E402

HW = ROOT / "hw"
OUT = HW / "diagrams"
FONT = "DejaVu Sans, Arial, Helvetica, sans-serif"

# ----------------------------------------------------------------------------- pin map
# NETS, BBB_P8 and BBB_P9 live in src/sadiy/pinmap.py, shared with the daemon and the GUI.

# Static straps on the boards (no SBC pin involved). Verify against each PCB.
STRAPS = [
    ("PE4302", "V1 ... V6", "module: 10k pull-downs",
     "open inputs = 0 dB attenuation (the unsafe state). Optional 2.2k pull-ups to 3V3 give about 2.7 V at the pin, above the 2.3 V threshold, so the default becomes maximum attenuation"),
    ("PE4302", "VDD pad", "3V3 (SBC pin)",
     "the module has no regulator and is meant for 3.3 V (Silicon Chip). Two separate pads next to the chip, not on the 7-pin header (GND, V1 ... V6)"),
    ("ADF4351", "DC jack", "5 V",
     "on-board AMS1117-3.3 supplies the chip; check the polarity marking next to the jack. The 3V3 header pin is the regulator output: do not feed it"),
    ("ADF4351", "CE", "3V3",
     "header pin, chip enable (or an SBC pin, see SYN_CE); measure whether the board already pulls it up"),
    ("ADF4351", "PDR", "3V3",
     "RF power-down pin (PDBRF): high = RF outputs on; measure whether the board already pulls it up"),
    ("ADF4351", "AOUT- / AOUT+", "50 ohm on the unused output",
     "differential outputs, use one for the LO and terminate the other; MCLK is the external reference input (25 MHz oscillator fitted)"),
    ("ADS1115", "ADDR", "GND", "I2C address 0x48"),
    ("ADS1115", "VDD", "3V3 (SBC pin)", "2.0 to 5.5 V"),
    ("Detector", "VCC pad", "5 V (verify)",
     "about 68 mA at 5 V per the listing; the board has its own regulator (SOT-223), read its marking for the allowed input range"),
    ("Detector", "OUT header", "check with a DMM", "2-pin header: find which pin is OUT and which is GND before connecting"),
]

RPI_40 = {
    1: ("3V3", "power"), 2: ("5V", "power"), 3: ("GPIO2 / SDA1", "free"), 4: ("5V", "power"),
    5: ("GPIO3 / SCL1", "free"), 6: ("GND", "gnd"), 7: ("GPIO4 / GPCLK0", "free"),
    8: ("GPIO14 / TXD0", "free"), 9: ("GND", "gnd"), 10: ("GPIO15 / RXD0", "free"),
    11: ("GPIO17", "free"), 12: ("GPIO18 / PCM_CLK", "free"), 13: ("GPIO27", "free"), 14: ("GND", "gnd"),
    15: ("GPIO22", "free"), 16: ("GPIO23", "free"), 17: ("3V3", "power"), 18: ("GPIO24", "free"),
    19: ("GPIO10 / SPI0 MOSI", "free"), 20: ("GND", "gnd"), 21: ("GPIO9 / SPI0 MISO", "free"),
    22: ("GPIO25", "free"), 23: ("GPIO11 / SPI0 SCLK", "free"), 24: ("GPIO8 / SPI0 CE0", "free"),
    25: ("GND", "gnd"), 26: ("GPIO7 / SPI0 CE1", "free"), 27: ("GPIO0 / ID_SD", "special"),
    28: ("GPIO1 / ID_SC", "special"), 29: ("GPIO5", "free"), 30: ("GND", "gnd"), 31: ("GPIO6", "free"),
    32: ("GPIO12 / PWM0", "free"), 33: ("GPIO13 / PWM1", "free"), 34: ("GND", "gnd"),
    35: ("GPIO19 / PCM_FS", "free"), 36: ("GPIO16", "free"), 37: ("GPIO26", "free"),
    38: ("GPIO20 / PCM_DIN", "free"),
    39: ("GND", "gnd"), 40: ("GPIO21 / PCM_DOUT", "free"),
}

# ----------------------------------------------------------------------------- palette
# name: (strong colour, tint)
PAL = {
    "spi": ("#1971c2", "#d0ebff"),
    "gpio": ("#2b8a3e", "#d3f9d8"),
    "analog": ("#9c36b5", "#f3d9fa"),
    "i2c": ("#0b7285", "#c5f6fa"),
    "gnd": ("#495057", "#e9ecef"),
    "power": ("#e8590c", "#fff0e6"),
    "reserved": ("#e67700", "#fff3bf"),
    "special": ("#868e96", "#f1f3f5"),
    "free": ("#adb5bd", "#ffffff"),
    "net": ("#495057", "#f1f3f5"),
    "v5": ("#e8590c", "#fff0e6"),
    "v10": ("#c92a2a", "#ffe3e3"),
    "v33": ("#1971c2", "#e7f5ff"),
}
INK = "#212529"
MUTED = "#6c757d"
BOARD = "#343a40"


def tw(s: str, size: float) -> float:
    return len(s) * size * 0.6


class Svg:
    def __init__(self, w: int, h: int, title: str, subtitle: str = "") -> None:
        self.w, self.h = w, h
        self.items: list[str] = []
        self.markers: set[str] = set()
        self.text(24, 34, title, size=22, weight="bold")
        if subtitle:
            self.text(24, 58, subtitle, size=13, fill=MUTED)

    def add(self, s: str) -> None:
        self.items.append(s)

    def rect(self, x, y, w, h, fill="#fff", stroke=BOARD, sw=1.5, rx=6, dash=None) -> None:
        d = f' stroke-dasharray="{dash}"' if dash else ""
        self.add(f'<rect x="{x:.1f}" y="{y:.1f}" width="{w:.1f}" height="{h:.1f}" rx="{rx}" '
                 f'fill="{fill}" stroke="{stroke}" stroke-width="{sw}"{d}/>')

    def text(self, x, y, s, size=12, anchor="start", weight="normal", fill=INK, italic=False) -> None:
        st = ' font-style="italic"' if italic else ""
        self.add(f'<text x="{x:.1f}" y="{y:.1f}" font-family="{FONT}" font-size="{size}" '
                 f'text-anchor="{anchor}" font-weight="{weight}" fill="{fill}"{st}>{escape(s)}</text>')

    def marker(self, color: str) -> str:
        mid = "a" + color.strip("#")
        self.markers.add(color)
        return mid

    def path(self, d, color, sw=2.2, dash=None, arrow_end=False, arrow_start=False) -> None:
        extra = ""
        if arrow_end:
            extra += f' marker-end="url(#{self.marker(color)})"'
        if arrow_start:
            extra += f' marker-start="url(#{self.marker(color)})"'
        da = f' stroke-dasharray="{dash}"' if dash else ""
        self.add(f'<path d="{d}" fill="none" stroke="{color}" stroke-width="{sw}"{da}{extra} '
                 f'stroke-linecap="round" stroke-linejoin="round"/>')

    def dot(self, x, y, color, r=5) -> None:
        self.add(f'<circle cx="{x:.1f}" cy="{y:.1f}" r="{r}" fill="#fff" stroke="{color}" stroke-width="2.2"/>')

    def label(self, x, y, s, color=INK, size=11) -> None:
        w = tw(s, size) + 10
        self.rect(x - w / 2, y - 9, w, 18, fill="#ffffff", stroke=color, sw=1, rx=4)
        self.text(x, y + 4, s, size=size, anchor="middle", fill=color)

    def badge(self, x, y, s, key) -> float:
        strong, _ = PAL[key]
        w = tw(s, 10.5) + 12
        self.rect(x, y, w, 18, fill=strong, stroke="none", rx=9)
        self.text(x + w / 2, y + 13, s, size=10.5, anchor="middle", weight="bold", fill="#ffffff")
        return w

    def save(self, path: Path) -> None:
        defs = "".join(
            f'<marker id="{self.marker(c)}" viewBox="0 0 10 10" refX="9" refY="5" markerWidth="7" '
            f'markerHeight="7" orient="auto-start-reverse"><path d="M0,0 L10,5 L0,10 z" fill="{c}"/></marker>'
            for c in sorted(self.markers))
        bg = f'<rect x="0" y="0" width="{self.w}" height="{self.h}" fill="#ffffff"/>'
        body = bg + "\n" + "\n".join(self.items)
        path.write_text(
            f'<svg xmlns="http://www.w3.org/2000/svg" width="{self.w}" height="{self.h}" '
            f'viewBox="0 0 {self.w} {self.h}"><defs>{defs}</defs>\n{body}\n</svg>\n')


def wire(svg: Svg, p1, p2, color, label=None, arrow_end=True, arrow_start=False, dash=None, sw=2.2,
         label_color=None) -> None:
    (x1, y1), (x2, y2) = p1, p2
    xm = (x1 + x2) / 2
    svg.path(f"M{x1:.1f},{y1:.1f} C{xm:.1f},{y1:.1f} {xm:.1f},{y2:.1f} {x2:.1f},{y2:.1f}", color, sw, dash,
             arrow_end, arrow_start)
    if label:
        svg.label(xm, (y1 + y2) / 2, label, color=label_color or color)


# ----------------------------------------------------------------------------- generic cards
def card(svg: Svg, x, y, w, title, subtitle, rows, fill="#f8f9fa", stroke=BOARD, dash=None, row_h=28):
    """rows: dicts with t (group|sig|strap|pwr), label, note, kind, side (L|R|None), key.
    Returns (ports, bottom_y). ports[key] = (x, y) of the connection dot."""
    h = 52 + sum(22 if r["t"] == "group" else row_h for r in rows) + 8
    svg.rect(x, y, w, h, fill=fill, stroke=stroke, sw=2, rx=10, dash=dash)
    svg.text(x + 14, y + 24, title, size=15, weight="bold")
    if subtitle:
        svg.text(x + 14, y + 42, subtitle, size=11, fill=MUTED)
    ports = {}
    cy = y + 52
    for r in rows:
        if r["t"] == "group":
            svg.text(x + 14, cy + 15, r["label"], size=11, weight="bold", fill=MUTED)
            cy += 22
            continue
        kind = r.get("kind", "net")
        strong, tint = PAL[kind]
        rx0, rw = x + 8, w - 16
        if r["t"] == "sig":
            svg.rect(rx0, cy, rw, row_h - 4, fill=tint, stroke=strong, sw=1.5, rx=5)
        elif r["t"] == "pwr":
            svg.rect(rx0, cy, rw, row_h - 4, fill=PAL[kind][1], stroke=strong, sw=1.2, rx=5)
        else:
            svg.rect(rx0, cy, rw, row_h - 4, fill="#ffffff", stroke="#adb5bd", sw=1.2, rx=5, dash="4 3")
        svg.text(rx0 + 10, cy + 17, r["label"], size=12, weight="bold" if r["t"] == "sig" else "normal")
        if r.get("note"):
            svg.text(rx0 + rw - 10, cy + 17, r["note"], size=10.5, anchor="end", fill=MUTED)
        if r.get("side") and r.get("key"):
            px = x if r["side"] == "L" else x + w
            ports[r["key"]] = (px, cy + (row_h - 4) / 2)
        cy += row_h
    return ports, y + h


def dots(svg: Svg, ports: dict, colors: dict) -> None:
    for k, (px, py) in ports.items():
        svg.dot(px, py, colors.get(k, BOARD))


def legend(svg: Svg, x, y, keys) -> None:
    names = {"spi": "SPI", "gpio": "GPIO", "analog": "analog", "i2c": "I2C", "gnd": "ground",
             "power": "power", "reserved": "reserved / optional", "special": "special", "free": "unused",
             "v5": "5 V", "v10": "10 V", "v33": "3.3 V"}
    for k in keys:
        strong, tint = PAL[k]
        svg.rect(x, y, 16, 16, fill=tint, stroke=strong, sw=1.8, rx=4)
        svg.text(x + 22, y + 13, names[k], size=11.5)
        x += 22 + tw(names[k], 11.5) + 22


# ----------------------------------------------------------------------------- pinout diagrams
def bbb_split(v):
    """P9 pin number (int) or a string like 'P8.7' -> ('P9', 9) / ('P8', 7)."""
    if isinstance(v, str):
        h, p = v.split(".")
        return h, int(p)
    return "P9", v


def bbb_table(header: str) -> dict:
    return BBB_P8 if header == "P8" else BBB_P9


def bbb_label(v) -> str:
    h, p = bbb_split(v)
    return f"{h}.{p} {bbb_table(h)[p][0]}"


def usage(sbc: str, header: str = "P9") -> dict:
    out = {}
    for n in NETS:
        pin = n[sbc]
        if not pin:
            continue
        if sbc == "bbb":
            h, p = bbb_split(pin)
            if h != header:
                continue
            out[p] = n
        else:
            out[pin] = n
    return out


def pinout(path: Path, title, subtitle, pins: dict, sbc: str, notes: list[str], hdr_label: str, header: str = "P9") -> None:
    rows = (len(pins) + 1) // 2
    rh = 25
    w, top = 920, 120
    h = top + rows * rh + 40 + 18 * len(notes) + 30
    svg = Svg(w, h, title, subtitle)
    legend(svg, 24, 76, ["spi", "gpio", "analog", "i2c", "gnd", "power", "reserved", "special", "free"])
    use = usage(sbc, header)
    svg.text(w / 2, top - 12, hdr_label, size=12, anchor="middle", weight="bold", fill=MUTED)
    cx = w / 2
    for r in range(rows):
        y = top + r * rh
        for side, pin in (("L", 2 * r + 1), ("R", 2 * r + 2)):
            if pin not in pins:
                continue
            name, kind = pins[pin]
            u = use.get(pin)
            if u:
                kind = u["kind"]
            strong, tint = PAL[kind]
            txt = name
            if u:
                txt = f"{name}   >   {u['dev']} {u['dpin']}"
            numx = cx - 44 if side == "L" else cx + 8
            svg.rect(numx, y, 36, rh - 3, fill=strong if kind != "free" else "#e9ecef", stroke=strong, sw=1.2, rx=4)
            svg.text(numx + 18, y + 16, str(pin), size=12, anchor="middle", weight="bold",
                     fill="#ffffff" if kind != "free" else INK)
            lx = 30 if side == "L" else cx + 52
            lw = cx - 52 - 30
            svg.rect(lx, y, lw, rh - 3, fill=tint, stroke=strong, sw=1.2 if u else 0.8, rx=4)
            svg.text(lx + lw - 8 if side == "L" else lx + 8, y + 16, txt, size=11.5,
                     anchor="end" if side == "L" else "start", weight="bold" if u else "normal")
    ny = top + rows * rh + 24
    for line in notes:
        svg.text(24, ny, line, size=11.5, fill=MUTED)
        ny += 18
    svg.save(path)


# ----------------------------------------------------------------------------- wiring diagrams
def sbc_rows_bbb():
    def r(pin, key, side, note=""):
        h, p = bbb_split(pin)
        name = bbb_table(h)[p][0]
        return dict(t="sig", label=f"{h}.{p}  {name}", note=note, kind=usage("bbb", h)[p]["kind"], side=side, key=key)

    return [
        dict(t="group", label="SPI0 to ADF4351 board"),
        r(22, "clk", "L"), r(18, "data", "L"), r(17, "le", "L"), r(23, "ld", "L", "input"),
        dict(t="group", label="GPIO to PE4302 board (V1..V6 on P8.7-P8.12)"),
        r("P8.7", "v1", "L"), r("P8.8", "v2", "L"), r("P8.9", "v3", "L"), r("P8.10", "v4", "L"), r("P8.11", "v5", "L"), r("P8.12", "v6", "L"),
        dict(t="group", label="I2C2 to ADS1115 (main ADC)"),
        r(20, "sda", "R"), r(19, "scl", "R"),
        dict(t="group", label="Analog input from detector (cross-check)"),
        r(39, "ain", "R", "max 1.8 V"), r(34, "agnd", "R"),
        dict(t="group", label="Ground"),
        dict(t="sig", label="P9.1 / P9.2 / P9.43-46 / P8.1 / P8.2  GND", note="star point", kind="gnd", side=None, key=None),
    ]


def sbc_rows_rpi():
    def r(pin, key, side, note=""):
        name = RPI_40[pin][0]
        return dict(t="sig", label=f"pin {pin}  {name}", note=note, kind=usage("rpi")[pin]["kind"], side=side, key=key)

    return [
        dict(t="group", label="SPI0 to ADF4351 board"),
        r(23, "clk", "L"), r(19, "data", "L"), r(24, "le", "L"), r(35, "ld", "L", "input"),
        dict(t="group", label="GPIO to PE4302 board (V1..V6)"),
        r(29, "v1", "L"), r(31, "v2", "L"), r(32, "v3", "L"), r(33, "v4", "L"), r(38, "v5", "L"), r(40, "v6", "L"),
        dict(t="group", label="I2C to ADS1115 (external ADC)"),
        r(3, "sda", "R"), r(5, "scl", "R"),
        dict(t="group", label="Ground"),
        dict(t="sig", label="pins 6, 9, 14, 20, 25, 30, 34, 39  GND", note="star point", kind="gnd", side=None,
             key=None),
    ]


def left_devices(svg: Svg, x: int, y: int):
    p1, b1 = card(svg, x, y, 340, "ADF4351 board (LO)", "eval board 2019_1_v1.4, 25 MHz oscillator, 3-wire SPI", [
        dict(t="sig", label="CLK", kind="spi", side="R", key="clk"),
        dict(t="sig", label="DAT", kind="spi", side="R", key="data"),
        dict(t="sig", label="LE", kind="spi", side="R", key="le"),
        dict(t="sig", label="LD", note="output, Lock_Flag LED", kind="gpio", side="R", key="ld"),
        dict(t="strap", label="CE", note="tie to 3V3 (optional SBC pin)"),
        dict(t="strap", label="PDR", note="tie to 3V3 (RF out enable)"),
        dict(t="strap", label="MUX", note="unused"),
        dict(t="pwr", label="DC jack", note="5 V (AMS1117-3.3 on board)", kind="v5"),
        dict(t="sig", label="GND", kind="gnd", side="L", key="gnd"),
    ])
    p2, b2 = card(svg, x, b1 + 24, 340, "PE4302 board (attenuator)", "parallel control only: 6 GPIO inputs", [
        dict(t="sig", label="V1  (0.5 dB)", note="assumed, verify", kind="gpio", side="R", key="v1"),
        dict(t="sig", label="V2  (1 dB)", kind="gpio", side="R", key="v2"),
        dict(t="sig", label="V3  (2 dB)", kind="gpio", side="R", key="v3"),
        dict(t="sig", label="V4  (4 dB)", kind="gpio", side="R", key="v4"),
        dict(t="sig", label="V5  (8 dB)", kind="gpio", side="R", key="v5"),
        dict(t="sig", label="V6  (16 dB)", kind="gpio", side="R", key="v6"),
        dict(t="strap", label="V1..V6", note="module 10k pull-downs: open = 0 dB"),
        dict(t="pwr", label="VDD pad", note="3V3 from the SBC pin", kind="v33"),
        dict(t="sig", label="GND", kind="gnd", side="L", key="gnd"),
    ])
    return p1, p2, b2


def ground_bus(svg: Svg, bus_x_left, bus_x_right, y_bar, stubs_left, stubs_right, sbc_x, sbc_bottom):
    g = PAL["gnd"][0]
    for (px, py) in stubs_left:
        svg.path(f"M{px:.1f},{py:.1f} L{bus_x_left},{py:.1f}", g, 2.5)
    for (px, py) in stubs_right:
        svg.path(f"M{px:.1f},{py:.1f} L{bus_x_right},{py:.1f}", g, 2.5)
    ys = [py for _, py in stubs_left] or [y_bar]
    bar_end = max(bus_x_right, sbc_x)
    svg.path(f"M{bus_x_left},{min(ys):.1f} L{bus_x_left},{y_bar} L{bar_end},{y_bar}", g, 4)
    if stubs_right:
        svg.path(f"M{bus_x_right},{min(py for _, py in stubs_right):.1f} L{bus_x_right},{y_bar}", g, 4)
    svg.path(f"M{sbc_x},{sbc_bottom:.1f} L{sbc_x},{y_bar}", g, 4)
    svg.dot(sbc_x, y_bar, g, 6)
    svg.text(sbc_x + 14, y_bar - 8, "GND star point (one place, near the SBC)", size=11.5, weight="bold", fill=g)


def draw_left_wires(svg: Svg, sbc_ports, p1, p2):
    pairs = [("clk", p1, "clk", "SYN_CLK", "spi", True), ("data", p1, "data", "SYN_DATA", "spi", True),
             ("le", p1, "le", "SYN_LE", "spi", True), ("ld", p1, "ld", "SYN_LD", "gpio", False),
             ] + [(f"v{i}", p2, f"v{i}", f"ATT_V{i}", "gpio", True) for i in range(1, 7)]
    for sk, dev_ports, dk, net, kind, to_dev in pairs:
        c = PAL[kind][0]
        a, b = dev_ports[dk], sbc_ports[sk]
        if to_dev:
            wire(svg, b, a, c, net, arrow_end=True)
        else:
            wire(svg, a, b, c, net, arrow_end=True)


def wiring_bbb(path: Path) -> None:
    W, H = 1560, 960
    svg = Svg(W, H, "BeagleBone Black wiring (proposed)",
              "3.3 V logic on all control lines. AIN0 is 0 to 1.8 V absolute maximum. Pin names: BBB system reference, verify on your image.")
    legend(svg, 24, 76, ["spi", "gpio", "i2c", "analog", "gnd", "v33"])
    top = 110
    p1, p2, bl = left_devices(svg, 40, top)
    sbc_x, sbc_w = 560, 380
    sp, sb = card(svg, sbc_x, top, sbc_w, "BeagleBone Black", "headers P8 + P9, sweepd runs here", sbc_rows_bbb(),
                  fill="#e7f5ff", stroke="#1864ab")
    draw_left_wires(svg, sp, p1, p2)
    # right side: divider and detector
    ay = sp["ain"][1]
    dv_x, dv_w = 1040, 170
    svg.rect(dv_x, ay - 26, dv_w, 38, fill="#fff9db", stroke="#e67700", sw=2, rx=8, dash="6 4")
    svg.text(dv_x + dv_w / 2, ay - 9, "divider + RC + clamp", size=11.5, anchor="middle", weight="bold")
    svg.text(dv_x + dv_w / 2, ay + 6, "TODO part, Vadc <= 1.8 V", size=10.5, anchor="middle", fill=MUTED)
    det_x = 1280
    dp, db = card(svg, det_x, ay - 52 - 14, 250, "Detector board", "AD8318 class, -24.5 mV/dB", [
        dict(t="sig", label="VOUT", kind="analog", side="L", key="vout"),
        dict(t="sig", label="GND", kind="gnd", side="L", key="gnd"),
        dict(t="pwr", label="VCC", note="5 V", kind="v5"),
        dict(t="strap", label="RF in", note="from IF amp"),
    ])
    pa = PAL["analog"][0]
    ads, _ = card(svg, det_x, sp["sda"][1] - 180, 250, "ADS1115 breakout (main ADC)", "address 0x48, A0 from the detector", [
        dict(t="sig", label="SDA", kind="i2c", side="L", key="sda"),
        dict(t="sig", label="SCL", kind="i2c", side="L", key="scl"),
        dict(t="pwr", label="VDD", note="3V3", kind="v33"),
        dict(t="sig", label="GND", note="board GND", kind="gnd", side=None, key=None),
    ])
    wire(svg, sp["sda"], ads["sda"], PAL["i2c"][0], "I2C_SDA", arrow_end=True, arrow_start=True)
    wire(svg, sp["scl"], ads["scl"], PAL["i2c"][0], "I2C_SCL", arrow_end=True)
    wire(svg, dp["vout"], (dv_x + dv_w, ay), pa, "VOUT", arrow_end=True)
    wire(svg, (dv_x, ay), sp["ain"], pa, "DET_ADC", arrow_end=True)
    wire(svg, sp["agnd"], dp["gnd"], PAL["gnd"][0], "ADC_GND", arrow_end=False, arrow_start=False)
    # ground bus
    y_bar = max(bl, sb) + 50
    stubs_left = [p1["gnd"], p2["gnd"]]
    ground_bus(svg, 20, 20, y_bar, stubs_left, [], sbc_x + sbc_w / 2, sb)
    svg.text(24, y_bar + 40, "Supplies are not wired from the SBC: see power-tree.svg. Boards share ground through the star point and the RF coax shields.",
             size=11.5, fill=MUTED)
    svg.h = int(y_bar + 70)
    svg.save(path)


def wiring_rpi(path: Path) -> None:
    W, H = 1560, 900
    svg = Svg(W, H, "Raspberry Pi 3 / 4 / 400 wiring (proposed)",
              "3.3 V logic. The Pi has no analog input: an ADS1115 (I2C) reads the detector. Never put more than 3.3 V on any GPIO.")
    legend(svg, 24, 76, ["spi", "gpio", "analog", "i2c", "gnd", "v33"])
    top = 110
    p1, p2, bl = left_devices(svg, 40, top)
    sbc_x, sbc_w = 560, 380
    sp, sb = card(svg, sbc_x, top, sbc_w, "Raspberry Pi", "40-pin header, sweepd runs here",
                  sbc_rows_rpi(), fill="#e7f5ff", stroke="#1864ab")
    draw_left_wires(svg, sp, p1, p2)
    ax = 1120
    ap, ab = card(svg, ax, top, 340, "ADS1115 board (ADC)", "16-bit, I2C 0x48, up to 860 SPS", [
        dict(t="sig", label="SDA", kind="i2c", side="L", key="sda"),
        dict(t="sig", label="SCL", kind="i2c", side="L", key="scl"),
        dict(t="strap", label="ADDR", note="tie to GND = 0x48"),
        dict(t="pwr", label="VDD", note="3V3 clean", kind="v33"),
        dict(t="sig", label="GND", kind="gnd", side="R", key="gnd"),
        dict(t="sig", label="A0 (from divider)", note="max VDD", kind="analog", side="R", key="a0"),
    ])
    wire(svg, sp["sda"], ap["sda"], PAL["i2c"][0], "I2C_SDA", arrow_end=True, arrow_start=True)
    wire(svg, sp["scl"], ap["scl"], PAL["i2c"][0], "I2C_SCL", arrow_end=True)
    # divider + detector stacked below, flowing upward into A0
    cx = ax + 170
    dv_y = ab + 50
    svg.rect(ax + 40, dv_y, 260, 48, fill="#fff9db", stroke="#e67700", sw=2, rx=8, dash="6 4")
    svg.text(cx, dv_y + 20, "divider + RC + clamp", size=11.5, anchor="middle", weight="bold")
    svg.text(cx, dv_y + 36, "TODO part, Vadc <= VDD of the ADS1115", size=10.5, anchor="middle", fill=MUTED)
    det_y = dv_y + 48 + 50
    dp, db = card(svg, ax, det_y, 340, "Detector board", "AD8318 class, -24.5 mV/dB", [
        dict(t="sig", label="VOUT", kind="analog", side=None, key=None),
        dict(t="sig", label="GND", kind="gnd", side="R", key="gnd"),
        dict(t="pwr", label="VCC", note="5 V", kind="v5"),
        dict(t="strap", label="RF in", note="from IF amp"),
    ])
    pa = PAL["analog"][0]
    svg.path(f"M{cx},{det_y} L{cx},{dv_y + 48}", pa, 2.4, arrow_end=True)
    svg.text(cx + 10, det_y - 8, "VOUT", size=11, fill=pa, weight="bold")
    a0 = ap["a0"]
    route_x = a0[0] + 34
    svg.path(f"M{ax + 300},{dv_y} L{ax + 300},{ab + 22} L{route_x},{ab + 22} L{route_x},{a0[1]} L{a0[0]},{a0[1]}",
             pa, 2.4, arrow_end=True)
    svg.text(ax + 310, ab + 40, "DET_ADC to A0", size=11, fill=pa, weight="bold")
    # ground
    y_bar = max(bl, sb, db) + 50
    g = PAL["gnd"][0]
    stubs_left = [p1["gnd"], p2["gnd"]]
    right_x = 1530
    stubs_right = [ap["gnd"], dp["gnd"]]
    ground_bus(svg, 20, right_x, y_bar, stubs_left, stubs_right, sbc_x + sbc_w / 2, sb)
    svg.dot(ap["gnd"][0], ap["gnd"][1], g)
    svg.dot(dp["gnd"][0], dp["gnd"][1], g)
    svg.text(24, y_bar + 40, "Supplies are not wired from the SBC: see power-tree.svg. Boards share ground through the star point and the RF coax shields.",
             size=11.5, fill=MUTED)
    svg.h = int(y_bar + 70)
    dots(svg, {k: v for k, v in sp.items()}, {k: PAL[kd][0] for k, kd in
         {"clk": "spi", "data": "spi", "le": "spi", "ld": "gpio", **{f"v{i}": "gpio" for i in range(1, 7)},
          "sda": "i2c", "scl": "i2c"}.items()})
    svg.save(path)


# ----------------------------------------------------------------------------- hierarchy, RF chain, power
def box(svg: Svg, x, y, w, h, title, sub="", todo=False, fill="#f8f9fa", stroke=BOARD, size=13, badge=None):
    if todo:
        svg.rect(x, y, w, h, fill="#fff9db", stroke="#e67700", sw=2, rx=8, dash="6 4")
    else:
        svg.rect(x, y, w, h, fill=fill, stroke=stroke, sw=2, rx=8)
    svg.text(x + w / 2, y + (24 if sub else h / 2 + 5), title, size=size, anchor="middle", weight="bold")
    if sub:
        for i, line in enumerate(sub.split("\n")):
            svg.text(x + w / 2, y + 42 + 15 * i, line, size=10.5, anchor="middle", fill=MUTED)
    if badge:
        svg.badge(x + 10, y - 9, badge[0], badge[1])


def hierarchy(path: Path) -> None:
    svg = Svg(1400, 790, "Board hierarchy",
              "Control hierarchy (who talks to whom) with the supply rail of each board (badges, see power-tree.svg). Dashed orange = still to build or buy.")
    legend(svg, 24, 76, ["spi", "gpio", "analog", "v5", "v10", "v33"])
    box(svg, 560, 110, 280, 56, "Viewer PC", "qt_client / cli_client")
    box(svg, 500, 250, 400, 84, "SBC: BeagleBone Black or Raspberry Pi",
        "sweepd (real-time acquisition process)\nGPIO + SPI + ADC, runs headless", fill="#e7f5ff", stroke="#1864ab",
        badge=("5 V", "v5"))
    n = PAL["net"][0]
    svg.path("M700,250 L700,166", n, 2.4, arrow_end=True, arrow_start=True)
    svg.label(700, 208, "Ethernet / ZeroMQ: PUB 5556, REP 5557", color=n)
    cy, ch, cw = 450, 84, 300
    kids = [
        (110, "PE4302 board", "6-bit attenuator, parallel control\n6 GPIO lines V1..V6", "gpio", "GPIO x6", "v33", "3.3 V"),
        (550, "ADF4351 board", "LO synthesizer (eval board, 25 MHz osc.)\nSPI + lock-detect GPIO", "spi", "SPI + LD", "v5", "5 V jack"),
        (990, "Detector board", "log detector, analog out\nvia divider (TODO) to ADC", "analog", "analog in", "v5", "5 V"),
    ]
    for x, t, s_, kind, lab, rail, rtxt in kids:
        box(svg, x, cy, cw, ch, t, s_, badge=(rtxt, rail))
        c = PAL[kind][0]
        wire(svg, (700, 334), (x + cw / 2, cy), c, lab, arrow_end=(kind != "analog"), arrow_start=(kind == "analog"))
    svg.text(24, 568, "ADF4351 board: 5 V on its DC jack, regulated to 3.3 V on the board (AMS1117-3.3). Check the polarity marking next to the jack.",
             size=11, fill=MUTED)
    svg.rect(40, 600, 1320, 160, fill="#f8f9fa", stroke="#adb5bd", sw=1.5, rx=10, dash="2 4")
    svg.text(56, 624, "RF-only boards: no link to the SBC (signal chain in rf-chain.svg)", size=13, weight="bold", fill=MUTED)
    items = [("30 dB amp", "module", False, ("6-12 V", "v10")), ("AD831 mixer", "module", False, ("9-11 V", "v10")),
             ("500 MHz LPF", "TODO", True, None), ("LO LPF + pad", "TODO", True, None),
             ("10.7 MHz IF filter", "TODO", True, None), ("IF amp", "TODO", True, ("TBD", "v10"))]
    x = 56
    for t, s_, todo, bd in items:
        box(svg, x, 652, 200, 80, t, s_, todo=todo, badge=bd)
        x += 215
    svg.save(path)


def rf_chain(path: Path) -> None:
    svg = Svg(1480, 640, "RF signal chain",
              "Nominal gains are estimates; amp figures are seller claims. Levels in dBm refer to the analyzer input.")
    n = PAL["net"][0]
    bw, bh, gap = 170, 72, 46
    x0 = 40

    def bx(i):
        return x0 + i * (bw + gap)

    ly = 100
    box(svg, bx(3), ly, bw, bh, "ADF4351", "LO 35.7-499.7 MHz\n-4..+5 dBm, SPI", badge=("SPI", "spi"))
    box(svg, bx(4), ly, bw, bh, "LO LPF + pad", "harmonics only -10..-20 dBc\ndrive about -10 dBm", todo=True)
    svg.path(f"M{bx(3) + bw},{ly + 40} L{bx(4)},{ly + 40}", PAL["spi"][0], 2.4, arrow_end=True)
    ry = 240
    names = [("RF in", "SMA, 25-489 MHz", False, None), ("DC block + ESD", "limiter / protection", True, None),
             ("PE4302", "0 .. -31.5 dB, 0.5 dB steps", False, ("GPIO", "gpio")),
             ("500 MHz LPF", "-1.5 dB, stops FM/GSM/LTE", True, None),
             ("30 dB amp", "+31 dB, P1dB +10 dBm\nNF 1.9 dB (claims)", False, None),
             ("AD831 mixer", "RF/LO to 500 MHz\nP1dB +10 dBm, NF 10-14 dB", False, None)]
    for i, (t, s_, todo, bd) in enumerate(names):
        box(svg, bx(i), ry, bw, bh + 8, t, s_, todo=todo, badge=bd)
        if i < len(names) - 1:
            svg.path(f"M{bx(i) + bw},{ry + 40} L{bx(i + 1)},{ry + 40}", n, 2.4, arrow_end=True)
    wire(svg, (bx(4) + bw / 2, ly + bh), (bx(5) + bw / 2, ry), PAL["spi"][0], "LO", arrow_end=True)
    iy = 430
    chain = [("10.7 MHz IF filter", "ceramic 150-280 kHz\n(sets RBW), -6 dB", True, None),
             ("IF amp", "+15..20 dB, variable", True, None),
             ("Detector", "-58..-1 dBm window\n-24.5 mV/dB", False, None),
             ("divider + RC + clamp", "Vadc <= 1.8 V (BBB)", True, None),
             ("SBC ADC", "BBB AIN0 / RPi ADS1115", False, ("analog", "analog"))]
    for i, (t, s_, todo, bd) in enumerate(chain):
        box(svg, bx(i), iy, bw, bh + 8, t, s_, todo=todo, badge=bd)
        if i < len(chain) - 1:
            svg.path(f"M{bx(i) + bw},{iy + 40} L{bx(i + 1)},{iy + 40}", PAL["analog"][0] if i >= 2 else n, 2.4,
                     arrow_end=True)
    mx = bx(5) + bw / 2
    svg.path(f"M{mx},{ry + bh + 8} L{mx},{iy - 40} L{bx(0) + bw / 2},{iy - 40} L{bx(0) + bw / 2},{iy}", n, 2.4,
             arrow_end=True)
    svg.label(mx - 330, iy - 40, "IF = 10.7 MHz (LO = RF + 10.7 MHz)", color=n)
    svg.text(24, 580, "Gain budget at 0 dB attenuation: -1.5 (PE4302) -1.5 (LPF) +31 (amp) 0 (mixer) -6 (IF filter) = about 22 dB to the detector, before the IF amp.", size=11.5, fill=MUTED)
    svg.text(24, 600, "Low IF gives an image 21.4 MHz above each RF; every tone appears twice. The amp compresses near -19.5 dBm at the input with 0 dB attenuation.", size=11.5, fill=MUTED)
    svg.save(path)


def power_tree(path: Path) -> None:
    svg = Svg(1400, 640, "Power tree (proposed)",
              "Currents are datasheet or listing figures; measure the amp, the mixer module and the ADF4351 board. Ferrite or LC between rails.")
    box(svg, 40, 280, 210, 90, "12 V DC input", "wall supply, 2 A\nfuse + reverse protection (TODO)", todo=True)
    ys = {"v5": 110, "v33": 270, "v10": 430}
    rails = [
        ("v5", "5 V buck", "feeds SBC, ADF4351 board, detector\nBBB up to 2 A", "12V", True,
         [("SBC (BBB or RPi)", "5 V / 2-3 A"),
          ("ADF4351 board (DC jack)", "5 V, ~200 mA (AMS1117-3.3 on board)"),
          ("Detector board (VCC pad)", "~68 mA, check its regulator")]),
        ("v33", "SBC 3.3 V output pin", "BBB P9.3 / P9.4, RPi pin 1 / 17\ntiny loads only", "5V", False,
         [("PE4302 board (VDD pad)", "3.3 V required, tiny"),
          ("ADS1115", "tiny"),
          ("optional pull-ups on V1..V6", "few mA")]),
        ("v10", "10 V low-noise LDO", "from 12 V (2 V dropout)\nAD831 100-125 mA + amp (measure)", "12V", True,
         [("AD831 mixer module (VCC pad)", "9-11 V, ~100-125 mA"),
          ("30 dB amp (VCC pad)", "6-12 V, current TBD"),
          ("IF amp (TODO)", "TBD")]),
    ]
    rx, rw = 360, 320
    for key, t, s_, src, todo, loads in rails:
        y = ys[key]
        col = PAL[key][0]
        box(svg, rx, y, rw, 90, t, s_, todo=todo, badge=({"v5": "5 V", "v10": "10 V", "v33": "3.3 V"}[key], key))
        if src == "12V":
            wire(svg, (250, 325), (rx, y + 45), PAL["gnd"][0], None, arrow_end=True, sw=2.6)
        else:
            svg.path(f"M{rx + rw / 2},{ys['v5'] + 90} L{rx + rw / 2},{y}", PAL["v5"][0], 2.6, arrow_end=True)
        lx, lw = 800, 520
        for i, (lt, ls) in enumerate(loads):
            ly = y + 45 - 17 + (i - (len(loads) - 1) / 2) * 40
            svg.rect(lx, ly, lw, 34, fill="#f8f9fa", stroke=BOARD, sw=2, rx=8)
            svg.text(lx + 14, ly + 22, lt, size=12.5, weight="bold")
            svg.text(lx + lw - 14, ly + 22, ls, size=11, anchor="end", fill=MUTED)
            wire(svg, (rx + rw, y + 45), (lx, ly + 17), col, None, arrow_end=True, sw=2.2)
    svg.text(24, 580, "The ADF4351 eval board regulates its 5 V jack to 3.3 V itself. The PE4302 module has no regulator and wants 3.3 V: take it from the SBC pin, which is also the GPIO level.", size=11.5, fill=MUTED)
    svg.text(24, 600, "The rail voltage on the shared lever connector in the photos is not known yet: confirm it before connecting the PE4302 pads (3.3 V) and the AD831 (9 to 11 V).", size=11.5, fill=MUTED)
    svg.text(24, 620, "Grounds meet at one star point near the SBC. GNDA_ADC (P9.34) is only for the optional BBB AIN0 cross-check.", size=11.5, fill=MUTED)
    svg.save(path)


# ----------------------------------------------------------------------------- netlist markdown
def netlist_md() -> str:
    L = ["# Netlist", "", "Generated by `tools/gen_diagrams.py` from the pin map in `src/sadiy/pinmap.py`. Do not edit by hand.", "",
         "BBB = BeagleBone Black headers P8 and P9. RPi = 40-pin header (physical pin numbers). Verify every pin on your image.", "",
         "## SBC to board signals", "",
         "| Net | Board | Board pin | Direction | BBB | RPi | Notes |", "|---|---|---|---|---|---|---|"]
    for n in NETS:
        bbb = bbb_label(n["bbb"]) if n["bbb"] else "n/a"
        rpi = f"pin {n['rpi']} {RPI_40[n['rpi']][0]}" if n["rpi"] else "n/a"
        L.append(f"| {n['id']} | {n['dev']} | {n['dpin']} | {n['dir']} | {bbb} | {rpi} | {n['note']} |")
    L += ["", "## Static straps on the boards (no SBC pin)", "", "| Board | Pin | Tie to | Why |", "|---|---|---|---|"]
    for dev, pin, tie, why in STRAPS:
        L.append(f"| {dev} | {pin} | {tie} | {why} |")
    L += ["", "## Pins left free for later", "",
          "- BBB: P9.11-P9.16, P8.13 to P8.19 and P8.26 (GPIO), SPI1 (P9.28-31), AIN1-AIN6, UART1 (P9.24/26).",
          "- RPi: SPI0 CE1 (pin 26), GPIO 17/27/22/23/24/25, UART (pins 8/10).", "",
          "## Ground and supply pins", "",
          "- BBB: GND P9.1, P9.2, P9.43-46 and P8.1, P8.2; GNDA_ADC P9.34 (optional, AIN0 cross-check only); ADC reference VDD_ADC P9.32 (1.8 V, do not load).",
          "- RPi: GND pins 6, 9, 14, 20, 25, 30, 34, 39.",
          "- Board supplies come from the power tree, not from SBC pins (`power-tree.svg`).", ""]
    return "\n".join(L)


# ----------------------------------------------------------------------------- main
def render_png(svg: Path) -> bool:
    png = svg.with_suffix(".png")
    if shutil.which("rsvg-convert"):
        subprocess.run(["rsvg-convert", "-z", "1.6", "-o", str(png), str(svg)], check=True)
        return True
    try:
        import cairosvg
        cairosvg.svg2png(url=str(svg), write_to=str(png), scale=1.6)
        return True
    except ImportError:
        return render_png_qt(svg, png)


def render_png_qt(svg: Path, png: Path, scale: float = 1.6) -> bool:
    """Fallback for a machine with the GUI dependencies but no SVG tools."""
    import os
    os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")
    try:
        from PyQt5 import QtCore, QtGui, QtSvg
    except ImportError:
        return False
    _app = QtGui.QGuiApplication.instance() or QtGui.QGuiApplication([])
    renderer = QtSvg.QSvgRenderer(str(svg))
    size = renderer.defaultSize()
    image = QtGui.QImage(round(size.width() * scale), round(size.height() * scale), QtGui.QImage.Format_ARGB32)
    image.fill(QtCore.Qt.white)
    painter = QtGui.QPainter(image)
    renderer.render(painter)
    painter.end()
    return image.save(str(png))


def main() -> None:
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--no-png", action="store_true")
    args = ap.parse_args()
    OUT.mkdir(parents=True, exist_ok=True)
    pinout(OUT / "bbb-p9-pinout.svg", "BeagleBone Black header P9: pinout and use",
           "Highlighted pins are used by SAdiy. Pins 1 and 2 are at the top (the end nearest the 5 V DC jack; confirm with the board silkscreen).",
           BBB_P9, "bbb",
           ["AIN pins: 0 to 1.8 V absolute maximum. VDD_ADC (P9.32) is a 1.8 V reference output, do not load it.",
            "P9.17, P9.18 and P9.22 are SPI0 (ADF4351), P9.19 and P9.20 are I2C2 (ADS1115). The PE4302 inputs V1..V6 are on P8.7-P8.12; P9.11-P9.16 stay free.",
            "Check config-pin / show-pins. SPI0 is the only hardware SPI used; the PE4302 is plain GPIO.",
            "P9.34 (GNDA_ADC) and P9.39 (AIN0) are optional, for the AIN0 cross-check only. The ADS1115 needs just I2C2 and board GND."],
           "P9 header (odd pins left, even pins right)")
    pinout(OUT / "rpi-gpio-pinout.svg", "Raspberry Pi 40-pin header: pinout and use",
           "Highlighted pins are used by SAdiy. Pin 1 is the corner nearest the SD card slot; odd pins are on the inner row.",
           RPI_40, "rpi",
           ["All GPIO are 3.3 V and not 5 V tolerant. The Pi has no analog input: an external ADC (ADS1115) is required.",
            "SPI0 (ADF4351) via raspi-config; I2C for the ADS1115. Pins 29, 31, 32, 33, 38, 40 drive the PE4302 inputs V1..V6.",
            "The PE4302 module has 10k pull-downs on V1..V6 (open = 0 dB); optional 2.2k pull-ups to 3V3 make the default maximum attenuation."],
           "40-pin header (odd pins left, even pins right)")
    pinout(OUT / "bbb-p8-pinout.svg", "BeagleBone Black header P8: pinout and use",
           "Highlighted pins are used by SAdiy. P8.1 and P8.2 are the only ground pins on P8. Confirm the orientation with the silkscreen.",
           BBB_P8, "bbb",
           ["P8.7 to P8.19 and P8.26 are plain GPIO on a stock image. P8.3-6 and P8.20-25 are the eMMC, P8.27-46 the HDMI/LCD (free them only by disabling HDMI).",
            "The PE4302 inputs V1..V6 use P8.7 to P8.12 (kernel GPIO 66, 67, 69, 68, 45, 44).",
            "There is no SPI on P8. P8.11 and P8.12 can be PRU0 outputs, P8.15 and P8.16 PRU0 inputs.",
            "The PE4302 module has 10k pull-downs on V1..V6 (open = 0 dB); optional 2.2k pull-ups to 3V3 make the default maximum attenuation.",
            "Do not drive any pin before SYS_RESETn is high. Check config-pin / show-pins."],
           "P8 header (odd pins left, even pins right)", header="P8")
    wiring_bbb(OUT / "bbb-wiring.svg")
    wiring_rpi(OUT / "rpi-wiring.svg")
    hierarchy(OUT / "board-hierarchy.svg")
    rf_chain(OUT / "rf-chain.svg")
    power_tree(OUT / "power-tree.svg")
    (HW / "netlist.md").write_text(netlist_md())
    made = sorted(OUT.glob("*.svg"))
    if not args.no_png:
        for s in made:
            if not render_png(s):
                print("no PNG renderer found (install librsvg2-bin or cairosvg, or PyQt5); SVGs written")
                break
    print("wrote", ", ".join(p.name for p in made), "and hw/netlist.md")


if __name__ == "__main__":
    main()
