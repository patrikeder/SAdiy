#!/usr/bin/env python3
"""Generate the KiCad project for the SAdiy SBC adapter board.

Writes (into the output folder given as argv[1]):
  sa_sbc_adapter.kicad_sch   schematic, KiCad 8 file format (opens in 8, 9, 10)
  sa_sbc_adapter.kicad_pro   minimal project file
  sadiy.kicad_sym            project symbol library (same symbols as embedded)
  sym-lib-table              registers the project library
  preview.svg                generator preview of the geometry (NOT a KiCad render)

Pure standard library. Edit this script, not the generated files.

    python3 gen_schematic.py            # writes next to the script
    python3 check_schematic.py sa_sbc_adapter.kicad_sch
"""
import json
import os
import sys
import uuid
from xml.sax.saxutils import escape

NS = uuid.UUID("6f1c1d8e-5a52-4a53-9b53-5ad1f0a0c0de")
PROJECT = "sa_sbc_adapter"
LIB = "sadiy"
ROOT_UUID = str(uuid.uuid5(NS, "root-sheet"))
_cnt = [0]


def uid():
    _cnt[0] += 1
    return str(uuid.uuid5(NS, "item-%d" % _cnt[0]))


def g(v):
    """Snap to the 1.27 mm schematic grid."""
    return round(round(v / 1.27) * 1.27, 4)


def n(v):
    s = ("%.4f" % v).rstrip("0").rstrip(".")
    return "0" if s in ("-0", "") else s


FONT = "(font (size 1.27 1.27))"


def effects(hide=False, justify=None):
    s = "(effects " + FONT
    if justify:
        s += " (justify %s)" % justify
    if hide:
        s += " hide"
    return s + ")"


# --------------------------------------------------------------------------
# Symbols
# --------------------------------------------------------------------------
class Sym:
    def __init__(self, name, prims, pins, ref="U", desc="", power=False,
                 hide_names=False, hide_numbers=False, name_offset=1.016,
                 ref_off=(0, -2.54), val_off=(0, 2.54), ref_just=None, val_just=None,
                 footprint=""):
        self.name = name
        self.prims = prims      # ('rect',x1,y1,x2,y2,filled) ('poly',[pts]) ('circle',cx,cy,r)
        self.pins = pins        # dicts: num,name,x,y,angle,length,etype,hide
        self.ref = ref
        self.desc = desc
        self.power = power
        self.hide_names = hide_names
        self.hide_numbers = hide_numbers
        self.name_offset = name_offset
        self.ref_off = ref_off
        self.val_off = val_off
        self.ref_just = ref_just
        self.val_just = val_just
        self.footprint = footprint

    def pin_xy(self, num):
        for p in self.pins:
            if p["num"] == str(num):
                return p["x"], p["y"]
        raise KeyError(num)

    def lib_sexp(self, prefix):
        full = (prefix + ":" if prefix else "") + self.name
        o = ['(symbol "%s"' % full]
        if self.power:
            o.append("(power)")
        if self.hide_numbers:
            o.append("(pin_numbers hide)")
        o.append("(pin_names (offset %s)%s)" % (n(self.name_offset), " hide" if self.hide_names else ""))
        o.append("(exclude_from_sim no) (in_bom yes) (on_board yes)")
        o.append('(property "Reference" "%s" (at 0 0 0) %s)' % (self.ref, effects()))
        o.append('(property "Value" "%s" (at 0 0 0) %s)' % (self.name, effects()))
        o.append('(property "Footprint" "%s" (at 0 0 0) %s)' % (self.footprint, effects(hide=True)))
        o.append('(property "Datasheet" "~" (at 0 0 0) %s)' % effects(hide=True))
        o.append('(property "Description" "%s" (at 0 0 0) %s)' % (self.desc, effects(hide=True)))
        o.append('(symbol "%s_0_1"' % self.name)
        for p in self.prims:
            if p[0] == "rect":
                o.append("(rectangle (start %s %s) (end %s %s) (stroke (width 0.254) (type default)) (fill (type %s)))"
                         % (n(p[1]), n(p[2]), n(p[3]), n(p[4]), "background" if p[5] else "none"))
            elif p[0] == "poly":
                pts = " ".join("(xy %s %s)" % (n(x), n(y)) for x, y in p[1])
                o.append("(polyline (pts %s) (stroke (width 0.254) (type default)) (fill (type none)))" % pts)
            elif p[0] == "circle":
                o.append("(circle (center %s %s) (radius %s) (stroke (width 0.254) (type default)) (fill (type none)))"
                         % (n(p[1]), n(p[2]), n(p[3])))
        o.append(")")
        o.append('(symbol "%s_1_1"' % self.name)
        for p in self.pins:
            o.append('(pin %s line (at %s %s %s) (length %s)%s (name "%s" %s) (number "%s" %s))'
                     % (p["etype"], n(p["x"]), n(p["y"]), n(p["angle"]), n(p["length"]),
                        " hide" if p.get("hide") else "", p["name"], effects(), p["num"], effects()))
        o.append(")")
        o.append(")")
        return "\n".join(o)


def pin(num, name, x, y, angle, length, etype="passive", hide=False):
    return dict(num=str(num), name=name, x=x, y=y, angle=angle, length=length, etype=etype, hide=hide)


def make_r_h():
    return Sym("R_H", [("rect", -2.54, -1.016, 2.54, 1.016, False)],
               [pin(1, "~", -3.81, 0, 0, 1.27), pin(2, "~", 3.81, 0, 180, 1.27)],
               ref="R", desc="Resistor, horizontal", hide_names=True, hide_numbers=True, name_offset=0,
               ref_off=(0, -2.286), val_off=(0, 2.286), footprint="Resistor_SMD:R_0603_1608Metric")


def make_fb_h():
    return Sym("FB_H", [("rect", -2.54, -1.016, 2.54, 1.016, True), ("poly", [(-1.27, -1.016), (-1.27, 1.016)])],
               [pin(1, "~", -3.81, 0, 0, 1.27), pin(2, "~", 3.81, 0, 180, 1.27)],
               ref="FB", desc="Ferrite bead, horizontal", hide_names=True, hide_numbers=True, name_offset=0,
               ref_off=(0, -2.286), val_off=(0, 2.286), footprint="Inductor_SMD:L_0805_2012Metric")


def make_f_h():
    return Sym("F_H", [("rect", -2.54, -1.016, 2.54, 1.016, False), ("poly", [(-2.54, 0), (2.54, 0)])],
               [pin(1, "~", -3.81, 0, 0, 1.27), pin(2, "~", 3.81, 0, 180, 1.27)],
               ref="F", desc="Resettable fuse, horizontal", hide_names=True, hide_numbers=True, name_offset=0,
               ref_off=(0, -2.286), val_off=(0, 2.286), footprint="Fuse:Fuse_1812_4532Metric")


def make_c_v():
    return Sym("C_V", [("poly", [(-2.032, 0.508), (2.032, 0.508)]), ("poly", [(-2.032, -0.508), (2.032, -0.508)])],
               [pin(1, "~", 0, 3.81, 270, 3.302), pin(2, "~", 0, -3.81, 90, 3.302)],
               ref="C", desc="Capacitor, vertical", hide_names=True, hide_numbers=True, name_offset=0,
               ref_off=(2.54, -0.508), val_off=(2.54, 1.27), ref_just="left", val_just="left",
               footprint="Capacitor_SMD:C_0603_1608Metric")


def make_r_v():
    return Sym("R_V", [("rect", -1.016, -2.54, 1.016, 2.54, False)],
               [pin(1, "~", 0, 3.81, 270, 1.27), pin(2, "~", 0, -3.81, 90, 1.27)],
               ref="R", desc="Resistor, vertical", hide_names=True, hide_numbers=True, name_offset=0,
               ref_off=(2.54, -0.508), val_off=(2.54, 1.27), ref_just="left", val_just="left",
               footprint="Resistor_SMD:R_0603_1608Metric")


def make_bat54s():
    prims = [
        ("poly", [(-5.08, 0), (5.08, 0)]),
        ("poly", [(-3.81, 1.016), (-3.81, -1.016), (-1.27, 0), (-3.81, 1.016)]),
        ("poly", [(-1.27, 1.016), (-1.27, -1.016)]),
        ("poly", [(1.27, 1.016), (1.27, -1.016), (3.81, 0), (1.27, 1.016)]),
        ("poly", [(3.81, 1.016), (3.81, -1.016)]),
        ("poly", [(0, 0), (0, -2.54)]),
    ]
    pins = [pin(1, "A1", -7.62, 0, 0, 2.54), pin(2, "K2", 7.62, 0, 180, 2.54), pin(3, "K1/A2", 0, -5.08, 90, 2.54)]
    return Sym("BAT54S", prims, pins, ref="D", desc="Dual series Schottky diode, SOT-23 (A1=1, K2=2, common=3)",
               hide_names=True, name_offset=0, ref_off=(0, -3.0), val_off=(0, 3.0),
               footprint="Package_TO_SOT_SMD:SOT-23")


def make_tp():
    return Sym("TestPoint", [("circle", 1.27, 0, 1.016)], [pin(1, "1", 0, 0, 0, 2.54)],
               ref="TP", desc="Test point", hide_names=True, hide_numbers=True, name_offset=0,
               ref_off=(1.27, -2.2), val_off=(1.27, 2.4), footprint="TestPoint:TestPoint_Pad_D1.5mm")


def make_pwr_flag():
    return Sym("PWR_FLAG", [("poly", [(0, 0), (0, 1.27), (-1.016, 1.905), (0, 2.54), (1.016, 1.905), (0, 1.27)])],
               [pin(1, "pwr", 0, 0, 90, 0, "power_out", True)], ref="#FLG", desc="Power flag", power=True,
               hide_names=True, hide_numbers=True, name_offset=0, ref_off=(0, 3.5), val_off=(0, 5.0))


def make_gnd():
    return Sym("GND", [("poly", [(0, 0), (0, -1.27), (1.27, -1.27), (0, -2.54), (-1.27, -1.27), (0, -1.27)])],
               [pin(1, "GND", 0, 0, 270, 0, "power_in", True)], ref="#PWR", desc="Ground", power=True,
               hide_names=True, hide_numbers=True, name_offset=0, ref_off=(0, 3.0), val_off=(0, -3.8))


def make_pwr(name):
    return Sym(name, [("poly", [(-0.762, 1.27), (0, 2.54), (0.762, 1.27)]), ("poly", [(0, 0), (0, 2.54)])],
               [pin(1, name, 0, 0, 90, 0, "power_in", True)], ref="#PWR", desc=name + " rail", power=True,
               hide_names=True, hide_numbers=True, name_offset=0, ref_off=(0, -3.0), val_off=(0, 4.2))


def make_conn1(name, names, fp, desc):
    """Single row, pins on the left (connection point x=0), body to the right."""
    nn = len(names)
    w = g(max(len(s) for s in names) * 1.15 + 3.0)
    top, bot = 1.27, -2.54 * (nn - 1) - 1.27
    pins = [pin(i + 1, s, 0, -2.54 * i, 0, 3.81) for i, s in enumerate(names)]
    return Sym(name, [("rect", 3.81, top, 3.81 + w, bot, True)], pins, ref="J", desc=desc,
               ref_off=(3.81 + w / 2, -3.0), val_off=(3.81 + w / 2, -bot + 3.0 - 2.54 * 0), footprint=fp)


def make_conn2(name, lnames, rnames, fp, desc, w):
    """Odd/even two-row connector: odd pins left, even pins right."""
    rows = len(lnames)
    top, bot = 1.27, -2.54 * (rows - 1) - 1.27
    pins = []
    for i in range(rows):
        pins.append(pin(2 * i + 1, lnames[i], 0, -2.54 * i, 0, 3.81))
        pins.append(pin(2 * i + 2, rnames[i], 3.81 + w + 3.81, -2.54 * i, 180, 3.81))
    return Sym(name, [("rect", 3.81, top, 3.81 + w, bot, True)], pins, ref="J", desc=desc,
               ref_off=(3.81 + w / 2, -3.0), val_off=(3.81 + w / 2, -bot + 3.0), footprint=fp)


# BBB header pin names (used pins from hw/netlist.md; the rest from the BBB system reference, verify)
P9 = {1: "GND", 2: "GND", 3: "VDD_3V3", 4: "VDD_3V3", 5: "VDD_5V", 6: "VDD_5V", 7: "SYS_5V", 8: "SYS_5V",
      9: "PWR_BUT", 10: "SYS_RESETn", 11: "GPIO0_30", 12: "GPIO1_28", 13: "GPIO0_31", 14: "GPIO1_18",
      15: "GPIO1_16", 16: "GPIO1_19", 17: "SPI0_CS0 GPIO0_5", 18: "SPI0_D1 GPIO0_4", 19: "I2C2_SCL",
      20: "I2C2_SDA", 21: "SPI0_D0 GPIO0_3", 22: "SPI0_SCLK GPIO0_2", 23: "GPIO1_17", 24: "UART1_TXD",
      25: "GPIO3_21", 26: "UART1_RXD", 27: "GPIO3_19", 28: "SPI1_CS0 GPIO3_17", 29: "SPI1_D0 GPIO3_15",
      30: "GPIO3_16", 31: "SPI1_SCLK GPIO3_14", 32: "VDD_ADC", 33: "AIN4", 34: "GNDA_ADC", 35: "AIN6",
      36: "AIN5", 37: "AIN2", 38: "AIN3", 39: "AIN0", 40: "AIN1", 41: "GPIO0_20", 42: "GPIO0_7",
      43: "GND", 44: "GND", 45: "GND", 46: "GND"}
P8 = {1: "GND", 2: "GND", 3: "GPIO1_6 (eMMC)", 4: "GPIO1_7 (eMMC)", 5: "GPIO1_2 (eMMC)", 6: "GPIO1_3 (eMMC)",
      7: "GPIO2_2", 8: "GPIO2_3", 9: "GPIO2_5", 10: "GPIO2_4", 11: "GPIO1_13", 12: "GPIO1_12",
      13: "GPIO0_23", 14: "GPIO0_26", 15: "GPIO1_15", 16: "GPIO1_14", 17: "GPIO0_27", 18: "GPIO2_1",
      19: "GPIO0_22", 20: "GPIO1_31 (eMMC)", 21: "GPIO1_30 (eMMC)", 22: "GPIO1_5 (eMMC)",
      23: "GPIO1_4 (eMMC)", 24: "GPIO1_1 (eMMC)", 25: "GPIO1_0 (eMMC)", 26: "GPIO1_29"}
for _p in range(27, 47):
    P8[_p] = "LCD/HDMI"
RPI = {1: "3V3", 2: "5V", 3: "GPIO2 SDA1", 4: "5V", 5: "GPIO3 SCL1", 6: "GND", 7: "GPIO4", 8: "GPIO14 TXD",
       9: "GND", 10: "GPIO15 RXD", 11: "GPIO17", 12: "GPIO18", 13: "GPIO27", 14: "GND", 15: "GPIO22",
       16: "GPIO23", 17: "3V3", 18: "GPIO24", 19: "GPIO10 MOSI", 20: "GND", 21: "GPIO9 MISO", 22: "GPIO25",
       23: "GPIO11 SCLK", 24: "GPIO8 CE0", 25: "GND", 26: "GPIO7 CE1", 27: "ID_SD", 28: "ID_SC",
       29: "GPIO5", 30: "GND", 31: "GPIO6", 32: "GPIO12 PWM0", 33: "GPIO13 PWM1", 34: "GND",
       35: "GPIO19", 36: "GPIO16", 37: "GPIO26", 38: "GPIO20", 39: "GND", 40: "GPIO21"}


def two_col(names):
    keys = sorted(names)
    return [names[k] for k in keys if k % 2 == 1], [names[k] for k in keys if k % 2 == 0]


SYMS = {}
for s in (make_r_h(), make_fb_h(), make_f_h(), make_c_v(), make_r_v(), make_bat54s(), make_tp(),
          make_pwr_flag(), make_gnd(), make_pwr("+3V3"), make_pwr("+5V")):
    SYMS[s.name] = s
SYMS["Conn_BBB_P9"] = make_conn2("Conn_BBB_P9", *two_col(P9), "sadiy:BBB_Header_2x23_Male_Bottom",
                                 "BeagleBone Black header P9 (male pins, mounted on the bottom side)", 50.8)
SYMS["Conn_BBB_P8"] = make_conn2("Conn_BBB_P8", *two_col(P8), "sadiy:BBB_Header_2x23_Male_Bottom",
                                 "BeagleBone Black header P8 (male pins, mounted on the bottom side)", 50.8)
SYMS["Conn_RPi_40"] = make_conn2("Conn_RPi_40", *two_col(RPI), "Connector_IDC:IDC-Header_2x20_P2.54mm_Vertical",
                                 "Raspberry Pi 40-pin GPIO via ribbon cable (pin n to pin n)", 50.8)
SYMS["Conn_ATT_PE4302"] = make_conn1("Conn_ATT_PE4302", ["GND", "V1", "V2", "V3", "V4", "V5", "V6"],
                                     "Connector_PinHeader_2.54mm:PinHeader_1x07_P2.54mm_Vertical", "PE4302 module 7-pin control header")
SYMS["Conn_ADF4351"] = make_conn2("Conn_ADF4351", ["GND", "CE", "LE", "CLK", "LD"], ["3V3 (NC)", "GND", "DAT", "MUX", "PDR"],
                                  "Connector_PinHeader_2.54mm:PinHeader_2x05_P2.54mm_Vertical", "ADF4351 board 2x5 control header", 15.24)
SYMS["Conn_ADS1115"] = make_conn1("Conn_ADS1115", ["VDD", "GND", "SCL", "SDA", "ADDR", "ALRT", "A0", "A1", "A2", "A3"],
                                  "Connector_PinHeader_2.54mm:PinHeader_1x10_P2.54mm_Vertical", "ADS1115 breakout module header")
SYMS["Conn_1x02"] = make_conn1("Conn_1x02", ["1", "2"], "Connector_PinHeader_2.54mm:PinHeader_1x02_P2.54mm_Vertical", "2-pin header")
SYMS["Conn_1x03"] = make_conn1("Conn_1x03", ["1", "2", "3"], "Connector_PinHeader_2.54mm:PinHeader_1x03_P2.54mm_Vertical", "3-pin header")


# --------------------------------------------------------------------------
# Document
# --------------------------------------------------------------------------
class Doc:
    def __init__(self):
        self.items = []        # schematic s-expression strings
        self.svg = []          # preview elements
        self.used = []         # symbol names used (order)
        self.refs = {}
        self.pins_at = {}      # (ref,num) -> (x,y)
        self.placed = []       # dicts for checks
        self.wires = []

    def next_ref(self, prefix):
        self.refs[prefix] = self.refs.get(prefix, 0) + 1
        return "%s%d" % (prefix, self.refs[prefix])

    def place(self, symname, ref, value, x, y, fp=None, dnp=False, hide_ref=False, hide_val=False):
        s = SYMS[symname]
        if symname not in self.used:
            self.used.append(symname)
        x, y = g(x), g(y)
        hide_ref = hide_ref or ref.startswith("#")
        fp = fp if fp is not None else s.footprint
        rx, ry = s.ref_off
        vx, vy = s.val_off
        o = ['(symbol (lib_id "%s:%s") (at %s %s 0) (unit 1) (exclude_from_sim no) (in_bom yes) (on_board yes) (dnp %s)'
             % (LIB, symname, n(x), n(y), "yes" if dnp else "no")]
        o.append("(uuid \"%s\")" % uid())
        o.append('(property "Reference" "%s" (at %s %s 0) %s)'
                 % (ref, n(x + rx), n(y + ry), effects(hide=hide_ref, justify=s.ref_just)))
        o.append('(property "Value" "%s" (at %s %s 0) %s)'
                 % (value, n(x + vx), n(y + vy), effects(hide=hide_val, justify=s.val_just)))
        o.append('(property "Footprint" "%s" (at %s %s 0) %s)' % (fp, n(x), n(y), effects(hide=True)))
        o.append('(property "Datasheet" "~" (at %s %s 0) %s)' % (n(x), n(y), effects(hide=True)))
        o.append('(property "Description" "" (at %s %s 0) %s)' % (n(x), n(y), effects(hide=True)))
        res = {}
        for p in s.pins:
            o.append('(pin "%s" (uuid "%s"))' % (p["num"], uid()))
            res[p["num"]] = (round(x + p["x"], 4), round(y - p["y"], 4))
            self.pins_at[(ref, p["num"])] = res[p["num"]]
        o.append('(instances (project "%s" (path "/%s" (reference "%s") (unit 1))))' % (PROJECT, ROOT_UUID, ref))
        o.append(")")
        self.items.append("\n".join(o))
        self.placed.append(dict(ref=ref, sym=symname, value=value, x=x, y=y, dnp=dnp, pins=res))
        self._svg_symbol(s, ref, value, x, y, dnp)
        return res

    # ---- primitives
    def wire(self, p1, p2):
        p1, p2 = (g(p1[0]), g(p1[1])), (g(p2[0]), g(p2[1]))
        self.items.append('(wire (pts (xy %s %s) (xy %s %s)) (stroke (width 0) (type default)) (uuid "%s"))'
                          % (n(p1[0]), n(p1[1]), n(p2[0]), n(p2[1]), uid()))
        self.wires.append((tuple(p1), tuple(p2)))
        self.svg.append('<line x1="%s" y1="%s" x2="%s" y2="%s" class="w"/>' % (n(p1[0]), n(p1[1]), n(p2[0]), n(p2[1])))

    def label(self, name, pt, angle=0):
        pt = (g(pt[0]), g(pt[1]))
        just = "right bottom" if angle == 180 else "left bottom"
        self.items.append('(label "%s" (at %s %s %s) (effects %s (justify %s)) (uuid "%s"))'
                          % (name, n(pt[0]), n(pt[1]), n(angle), FONT, just, uid()))
        anchor = "end" if angle == 180 else "start"
        self.svg.append('<text x="%s" y="%s" text-anchor="%s" class="lb">%s</text>'
                        % (n(pt[0] + (-0.5 if angle == 180 else 0.5)), n(pt[1] - 0.4), anchor, escape(name)))

    def nc(self, pt):
        pt = (g(pt[0]), g(pt[1]))
        self.items.append('(no_connect (at %s %s) (uuid "%s"))' % (n(pt[0]), n(pt[1]), uid()))
        x, y = pt
        self.svg.append('<path d="M%s %sL%s %sM%s %sL%s %s" class="nc"/>'
                        % (n(x - 0.8), n(y - 0.8), n(x + 0.8), n(y + 0.8), n(x - 0.8), n(y + 0.8), n(x + 0.8), n(y - 0.8)))

    def text(self, s, x, y, size=1.27):
        esc = s.replace('"', "'").replace("\n", "\\n")
        self.items.append('(text "%s" (exclude_from_sim no) (at %s %s 0) (effects (font (size %s %s)) (justify left bottom)) (uuid "%s"))'
                          % (esc, n(x), n(y), n(size), n(size), uid()))
        for i, line in enumerate(s.split("\n")):
            self.svg.append('<text x="%s" y="%s" class="tx" style="font-size:%spx">%s</text>'
                            % (n(x), n(y + i * size * 1.5), n(size * 0.95), escape(line)))

    def frame(self, x1, y1, x2, y2, title):
        self.items.append('(rectangle (start %s %s) (end %s %s) (stroke (width 0.254) (type dash)) (fill (type none)) (uuid "%s"))'
                          % (n(x1), n(y1), n(x2), n(y2), uid()))
        self.svg.append('<rect x="%s" y="%s" width="%s" height="%s" class="fr"/>' % (n(x1), n(y1), n(x2 - x1), n(y2 - y1)))
        self.text(title, x1 + 2.54, y1 + 4.5, 2.0)

    # ---- helpers
    def stub(self, pt, side, name, length=2.54):
        """Wire from a pin out to a net label. side: L R U D."""
        x, y = pt
        if side == "L":
            e = (round(x - length, 4), y)
            self.wire(pt, e)
            self.label(name, e, 180)
        elif side == "R":
            e = (round(x + length, 4), y)
            self.wire(pt, e)
            self.label(name, e, 0)
        elif side == "U":
            e = (x, round(y - length, 4))
            self.wire(pt, e)
            self.label(name, e, 0)
        else:
            e = (x, round(y + length, 4))
            self.wire(pt, e)
            self.label(name, e, 0)

    def power(self, symname, pt, ref):
        self.place(symname, ref, symname, pt[0], pt[1])

    # ---- svg
    def _svg_symbol(self, s, ref, value, x, y, dnp):
        out = []
        for p in s.prims:
            if p[0] == "rect":
                x1, y1, x2, y2 = p[1], p[2], p[3], p[4]
                out.append('<rect x="%s" y="%s" width="%s" height="%s" class="sb"/>'
                           % (n(x + min(x1, x2)), n(y - max(y1, y2)), n(abs(x2 - x1)), n(abs(y2 - y1))))
            elif p[0] == "poly":
                pts = " ".join("%s,%s" % (n(x + a), n(y - b)) for a, b in p[1])
                out.append('<polyline points="%s" class="sp"/>' % pts)
            elif p[0] == "circle":
                out.append('<circle cx="%s" cy="%s" r="%s" class="sp"/>' % (n(x + p[1]), n(y - p[2]), n(p[3])))
        for p in s.pins:
            px, py = x + p["x"], y - p["y"]
            import math
            a = math.radians(p["angle"])
            qx, qy = px + p["length"] * math.cos(a), py - p["length"] * math.sin(a)
            if not p.get("hide"):
                out.append('<line x1="%s" y1="%s" x2="%s" y2="%s" class="pn"/>' % (n(px), n(py), n(qx), n(qy)))
                if p["name"] not in ("~",) and not s.hide_names:
                    anchor = "start" if p["angle"] == 0 else "end"
                    out.append('<text x="%s" y="%s" text-anchor="%s" class="pt">%s</text>'
                               % (n(qx + (1 if anchor == "start" else -1)), n(qy + 0.4), anchor, escape(p["name"])))
        if not s.power or s.name in ("+3V3", "+5V", "GND"):
            pass
        rx, ry = s.ref_off
        vx, vy = s.val_off
        anch = "start" if s.ref_just == "left" else "middle"
        if not ref.startswith("#"):
            out.append('<text x="%s" y="%s" text-anchor="%s" class="rf">%s</text>' % (n(x + rx), n(y + ry), anch, escape(ref)))
            out.append('<text x="%s" y="%s" text-anchor="%s" class="vl">%s%s</text>'
                       % (n(x + vx), n(y + vy), "start" if s.val_just == "left" else "middle", escape(value), " (DNP)" if dnp else ""))
        self.svg.append("\n".join(out))


# --------------------------------------------------------------------------
# The design
# --------------------------------------------------------------------------
SERIES_R = "220"
D = Doc()

# signal rows: net, BBB (header, pin), RPi pin
ROWS = [
    ("SYN_CLK", ("P9", 22), 23), ("SYN_DATA", ("P9", 18), 19), ("SYN_LE", ("P9", 17), 24),
    ("SYN_LD", ("P9", 23), 35), ("SYN_CE", ("P9", 27), 36),
    ("ATT_V1", ("P8", 7), 29), ("ATT_V2", ("P8", 8), 31), ("ATT_V3", ("P8", 9), 32),
    ("ATT_V4", ("P8", 10), 33), ("ATT_V5", ("P8", 11), 38), ("ATT_V6", ("P8", 12), 40),
    ("I2C_SDA", ("P9", 20), 3), ("I2C_SCL", ("P9", 19), 5),
]

BBB_NETS = {"P9": {1: "GND", 2: "GND", 43: "GND", 44: "GND", 45: "GND", 46: "GND", 3: "BBB_3V3", 4: "BBB_3V3",
                   5: "BBB_5V", 6: "BBB_5V", 32: "BBB_VDD_ADC", 34: "AGND", 39: "BBB_AIN0"},
            "P8": {1: "GND", 2: "GND"}}
RPI_NETS = {1: "RPI_3V3", 17: "RPI_3V3", 2: "RPI_5V", 4: "RPI_5V"}
for p in (6, 9, 14, 20, 25, 30, 34, 39):
    RPI_NETS[p] = "GND"
for net, (hdr, pn), rp in ROWS:
    BBB_NETS[hdr][pn] = "BBB_" + net
    RPI_NETS[rp] = "RPI_" + net

D.text("SAdiy SBC adapter: BeagleBone Black cape OR Raspberry Pi ribbon cable to the module boards", 20, 18, 3.0)
D.text("Use ONE SBC at a time. Every SBC signal has a %s ohm series resistor on each side, so a mistake with both attached "
       "limits the contention current." % SERIES_R, 20, 25, 1.5)

# ---- SBC connectors
J1_X, J1_Y = 50.8, 50.8
J2_X, J2_Y = 50.8, 137.16
J3_X, J3_Y = 330.2, 50.8
D.frame(12, 32, 160, 200, "BeagleBone Black headers (male pins on the BOTTOM side of the PCB)")
D.frame(305, 32, 430, 112, "Raspberry Pi 40-pin (IDC box header, ribbon cable)")


def wire_header(symname, ref, value, x, y, nets, names):
    pins = D.place(symname, ref, value, x, y)
    rows = len(names)
    for pn in sorted(names):
        pt = pins[str(pn)]
        side = "L" if pn % 2 == 1 else "R"
        if pn in nets:
            D.stub(pt, side, nets[pn])
        else:
            D.nc(pt)
    return pins


J1 = wire_header("Conn_BBB_P9", "J1", "BBB P9", J1_X, J1_Y, BBB_NETS["P9"], P9)
J2 = wire_header("Conn_BBB_P8", "J2", "BBB P8", J2_X, J2_Y, BBB_NETS["P8"], P8)
J3 = wire_header("Conn_RPi_40", "J3", "RPi 40-pin", J3_X, J3_Y, RPI_NETS, RPI)

# P8 pins 7..12 and P9 signal pins are named above; P8 rows in the dictionary
for net, (hdr, pn), rp in ROWS:
    pass

# ---- series resistor rows
D.frame(165, 32, 300, 160, "Signal rows: BBB side - %s ohm - common net - %s ohm - RPi side" % (SERIES_R, SERIES_R))
ROW_Y0 = 50.8
for i, (net, (hdr, pn), rp) in enumerate(ROWS):
    y = g(ROW_Y0 + i * 7.62)
    lab_l = (190.5, y)
    r1 = D.place("R_H", D.next_ref("R"), SERIES_R, 199.39, y)
    r2 = D.place("R_H", D.next_ref("R"), SERIES_R, 237.49, y)
    D.wire(lab_l, r1["1"])
    D.label("BBB_" + net, lab_l, 180)
    D.wire(r1["2"], r2["1"])
    D.label(net, (g(216), y), 0)
    D.wire(r2["2"], (246.38, y))
    D.label("RPI_" + net, (246.38, y), 0)

# ---- Module section: PE4302
PU_REFS = []
D.frame(12, 205, 205, 300, "PE4302 attenuator (parallel control, header GND V1..V6)")
for k in range(6):
    y = g(222 + k * 7.62)
    pu_ref = D.next_ref("R")
    PU_REFS.append(pu_ref)
    r = D.place("R_H", pu_ref, "2.2k", 63.5, y)
    D.wire((55.88, y), r["1"])
    D.label("+3V3", (55.88, y), 180)
    D.wire(r["2"], (76.2, y))
    D.label("ATT_V%d" % (k + 1), (76.2, y), 0)
D.text("Pull-ups %s..%s: with the module's 10k pull-downs the boot default is about 2.7 V = 31.5 dB.\nRemove them if you want 0 dB when the SBC is off." % (PU_REFS[0], PU_REFS[-1]), 17, 276, 1.1)
j4 = D.place("Conn_ATT_PE4302", "J4", "PE4302 ctl", 130, 222)
D.stub(j4["1"], "L", "GND")
for k in range(6):
    D.stub(j4[str(k + 2)], "L", "ATT_V%d" % (k + 1))
j5 = D.place("Conn_1x02", "J5", "PE4302 VDD pads", 130, 262)
D.stub(j5["1"], "L", "+3V3_ATT")
D.stub(j5["2"], "L", "GND")
D.text("J5: red lead = VDD (3.3 V), black = GND. Measure the pads before connecting.", 17, 294, 1.1)

# ---- ADF4351
D.frame(212, 205, 430, 300, "ADF4351 board (SPI + lock detect, 5 V on its DC jack)")
j6 = D.place("Conn_ADF4351", "J6", "ADF4351 hdr", 250, 222)
D.stub(j6["1"], "L", "GND")
D.stub(j6["3"], "L", "SYN_CE_M")
D.stub(j6["5"], "L", "SYN_LE")
D.stub(j6["7"], "L", "SYN_CLK")
D.stub(j6["9"], "L", "SYN_LD")
D.nc(j6["2"])
D.stub(j6["4"], "R", "GND")
D.stub(j6["6"], "R", "SYN_DATA")
D.stub(j6["8"], "R", "SYN_MUX")
D.stub(j6["10"], "R", "SYN_PDR")
D.text("J6 pin 2 (board 3V3) stays open: it is the AMS1117 output.\nPin order assumed from hw/netlist.md; check against the board silkscreen.", 217, 252, 1.1)
j12 = D.place("Conn_1x03", "J12", "CE select", 340, 222)
D.stub(j12["1"], "L", "+3V3")
D.stub(j12["2"], "L", "SYN_CE_M")
D.stub(j12["3"], "L", "SYN_CE")
D.text("CE: jumper 1-2 = tied high (default), 2-3 = SBC pin", 316, 237, 1.1)
jp5 = D.place("Conn_1x02", "JP5", "PDR high", 340, 246)
D.stub(jp5["1"], "L", "+3V3")
D.stub(jp5["2"], "L", "SYN_PDR")
D.text("JP5 fitted = PDR high (RF on). Remove if the board already pulls it up.", 316, 260, 1.1)
j7 = D.place("Conn_1x02", "J7", "ADF4351 5V jack", 340, 270)
D.stub(j7["1"], "L", "+5V_SYN")
D.stub(j7["2"], "L", "GND")
D.text("J7: check the polarity marking at the DC jack before connecting.", 316, 284, 1.1)

# ---- Detector + ADC front end
D.frame(437, 205, 655, 345, "Detector and ADC front end")
j8 = D.place("Conn_1x02", "J8", "Detector OUT", 466, 222)
D.stub(j8["1"], "L", "DET_OUT")
D.stub(j8["2"], "L", "AGND")
D.text("J8: find which header pin is OUT with a DMM first, then match pin 1.", 442, 233, 1.1)
j9 = D.place("Conn_1x02", "J9", "Detector VCC", 466, 242)
D.stub(j9["1"], "L", "+5V_DET")
D.stub(j9["2"], "L", "GND")

D.text("BBB path (AIN0, 1.8 V max): ratio 0.75, RC and clamp. Fit JP6 only for the BBB.", 442, 262, 1.1)
jp6 = D.place("Conn_1x02", "JP6", "BBB ADC path", 466, 268)
D.stub(jp6["1"], "L", "DET_OUT")
D.stub(jp6["2"], "L", "DET_DIV")
REF_RT = D.next_ref("R")
rt = D.place("R_H", REF_RT, "1k", 520, 268)
D.wire((511.11, 268), rt["1"])
D.label("DET_DIV", (511.11, 268), 180)
D.wire(rt["2"], (536, 268))
D.label("BBB_AIN0", (536, 268), 0)
REF_RB = D.next_ref("R")
rb = D.place("R_V", REF_RB, "3.01k", 560, 278)
D.stub(rb["1"], "U", "BBB_AIN0")
D.stub(rb["2"], "D", "AGND")
REF_CB = D.next_ref("C")
cb = D.place("C_V", REF_CB, "100n", 585, 278)
D.stub(cb["1"], "U", "BBB_AIN0")
D.stub(cb["2"], "D", "AGND")
REF_D1 = D.next_ref("D")
d1 = D.place("BAT54S", REF_D1, "BAT54S", 618, 276)
D.stub(d1["1"], "L", "AGND")
D.stub(d1["2"], "R", "BBB_VDD_ADC")
D.stub(d1["3"], "D", "BBB_AIN0")

D.text("RPi / ADS1115 path (A0): 1k, 100n, clamp to 3V3 and ground.", 442, 312, 1.1)
ra = D.place("R_H", D.next_ref("R"), "1k", 520, 322)
D.wire((511.11, 322), ra["1"])
D.label("DET_OUT", (511.11, 322), 180)
D.wire(ra["2"], (536, 322))
D.label("ADS_A0", (536, 322), 0)
ca = D.place("C_V", D.next_ref("C"), "100n", 560, 330)
D.stub(ca["1"], "U", "ADS_A0")
D.stub(ca["2"], "D", "AGND")
d2 = D.place("BAT54S", D.next_ref("D"), "BAT54S", 618, 326)
D.stub(d2["1"], "L", "AGND")
D.stub(d2["2"], "R", "+3V3")
D.stub(d2["3"], "D", "ADS_A0")

# ---- ADS1115
D.frame(662, 205, 832, 300, "ADS1115 breakout (address 0x48)")
j10 = D.place("Conn_ADS1115", "J10", "ADS1115", 700, 222)
D.stub(j10["1"], "L", "+3V3")
D.stub(j10["2"], "L", "GND")
D.stub(j10["3"], "L", "I2C_SCL")
D.stub(j10["4"], "L", "I2C_SDA")
D.stub(j10["5"], "L", "GND")
D.stub(j10["6"], "L", "ADS_ALRT")
D.stub(j10["7"], "L", "ADS_A0")
for p in ("8", "9", "10"):
    D.stub(j10[p], "L", "AGND")
for k, nm in enumerate(("I2C_SCL", "I2C_SDA")):
    y = g(262 + k * 7.62)
    r = D.place("R_H", D.next_ref("R"), "4.7k", 750, y, dnp=True)
    D.wire((742.38, y), r["1"])
    D.label("+3V3", (742.38, y), 180)
    D.wire(r["2"], (762, y))
    D.label(nm, (762, y), 0)
D.text("DNP I2C pull-ups: the Pi has 1.8k on SDA1/SCL1,\nthe BBB has them on I2C2.", 667, 285, 1.1)

# ---- Power
D.frame(437, 32, 832, 200, "Power: external 5 V and/or SBC, 3.3 V from the SBC")
j11 = D.place("Conn_1x02", "J11", "5V in", 470, 45)
D.stub(j11["1"], "L", "5V_EXT")
D.stub(j11["2"], "L", "GND")
f1 = D.place("F_H", D.next_ref("F"), "PTC 2A", 520, 45)
D.wire((511.11, 45), f1["1"])
D.label("5V_EXT", (511.11, 45), 180)
D.wire(f1["2"], (534, 45))
D.label("+5V", (534, 45), 0)
jp1 = D.place("Conn_1x02", "JP1", "5V BBB", 610, 45)
D.stub(jp1["1"], "L", "+5V")
D.stub(jp1["2"], "L", "BBB_5V")
jp2 = D.place("Conn_1x02", "JP2", "5V RPi", 610, 58)
D.stub(jp2["1"], "L", "+5V")
D.stub(jp2["2"], "L", "RPI_5V")
jp3 = D.place("Conn_1x02", "JP3", "3V3 BBB", 610, 71)
D.stub(jp3["1"], "L", "+3V3")
D.stub(jp3["2"], "L", "BBB_3V3")
jp4 = D.place("Conn_1x02", "JP4", "3V3 RPi", 610, 84)
D.stub(jp4["1"], "L", "+3V3")
D.stub(jp4["2"], "L", "RPI_3V3")
D.text("5V rail (+5V):\n"
       "  JP1 fitted: BBB VDD_5V (P9.5/6) joins the rail\n"
       "  JP2 fitted: RPi 5V (pins 2/4) joins the rail\n"
       "  A) external 5V on J11 powers the SBC: fit that SBC's jumper,\n"
       "     and do NOT plug the SBC's own supply\n"
       "  B) SBC powers the modules: fit its jumper, leave J11 empty\n"
       "  (a BBB on USB only has no VDD_5V)\n"
       "3V3 rail (+3V3), from the SBC only:\n"
       "  JP3 fitted for the BBB, JP4 for the RPi, never both", 650, 42, 1.1)

for i, (a, b) in enumerate((("+5V", "+5V_SYN"), ("+5V", "+5V_DET"), ("+3V3", "+3V3_ATT"))):
    y = g(96 + i * 7.62)
    fb = D.place("FB_H", D.next_ref("FB"), "BLM21 2A", 480, y)
    D.wire((472.11, y), fb["1"])
    D.label(a, (472.11, y), 180)
    D.wire(fb["2"], (494, y))
    D.label(b, (494, y), 0)
D.text("Ferrite beads isolate the module supplies from the SBC rails.", 442, 115, 1.1)

caps = [("+5V", "10u", 460, True), ("+5V", "100n", 475, True), ("+3V3", "10u", 490, True), ("+3V3", "100n", 505, True),
        ("+5V_SYN", "10u", 530, False), ("+5V_DET", "10u", 550, False), ("+5V_DET", "100n", 565, False),
        ("+3V3_ATT", "100n", 585, False)]
for net, val, x, sym in caps:
    c = D.place("C_V", D.next_ref("C"), val, x, 135, fp=("Capacitor_SMD:C_0805_2012Metric" if val == "10u" else None))
    if sym:
        D.power(net, c["1"], D.next_ref("#PWR"))
    else:
        D.stub(c["1"], "U", net)
    D.power("GND", c["2"], D.next_ref("#PWR"))

REF_RS = D.next_ref("R")
rs = D.place("R_H", REF_RS, "0R star", 520, 170)
D.wire((512, 170), rs["1"])
D.label("AGND", (512, 170), 180)
D.wire(rs["2"], (534, 170))
D.label("GND", (534, 170), 0)
D.text("%s joins AGND (detector return, BBB GNDA_ADC) to GND at one point." % REF_RS, 442, 180, 1.1)
for k, nm in enumerate(("+5V", "+3V3", "GND", "AGND")):
    fl = D.place("PWR_FLAG", D.next_ref("#FLG"), "PWR_FLAG", 640 + k * 15, 165)
    D.label(nm, fl["1"], 0)

# ---- Test points
D.frame(12, 350, 832, 420, "Test points (names follow hw/test-points.md)")
TPS = [("TP_GND1", "GND"), ("TP_GND2", "GND"), ("TP_AGND", "AGND"), ("TP_5V", "+5V_DET"), ("TP_5V_RAIL", "+5V"),
       ("TP_5V_SYN", "+5V_SYN"), ("TP_3V3", "+3V3"), ("TP_3V3_ATT", "+3V3_ATT"),
       ("TP_PE_V1", "ATT_V1"), ("TP_PE_V2", "ATT_V2"), ("TP_PE_V3", "ATT_V3"), ("TP_PE_V4", "ATT_V4"),
       ("TP_PE_V5", "ATT_V5"), ("TP_PE_V6", "ATT_V6"),
       ("TP_SYN_CLK", "SYN_CLK"), ("TP_SYN_DAT", "SYN_DATA"), ("TP_SYN_LE", "SYN_LE"), ("TP_SYN_LD", "SYN_LD"),
       ("TP_SYN_MUX", "SYN_MUX"), ("TP_DET_OUT", "DET_OUT"), ("TP_ADC_IN", "BBB_AIN0"), ("TP_ADS_A0", "ADS_A0"),
       ("TP_ADS_ALRT", "ADS_ALRT")]
for i, (val, net) in enumerate(TPS):
    col, row = i % 8, i // 8
    x = g(40 + col * 98)
    y = g(372 + row * 15)
    tp = D.place("TestPoint", D.next_ref("TP"), val, x, y)
    D.label(net, tp["1"], 180)

# ---- Notes
D.frame(12, 428, 832, 490, "Notes for the PCB")
D.text(
    "PLACEMENT (the SBC and the modules are on opposite sides of the board)\n"
    "  J1, J2: BBB headers, 2x23 male pins, bodies on the BOTTOM side, long pins down into the BBB sockets. Pin 1 of P8/P9 as on the BBB.\n"
    "  J3: 2x20 shrouded IDC header, TOP side, at the board edge, for a straight 1:1 ribbon to the Pi (pin n to pin n).\n"
    "  J4..J12, jumpers, test points, ferrites, caps: TOP side. Keep ~25 mm clear above the BBB Ethernet/USB/HDMI area.\n"
    "  Put the analog front end (%s, %s, %s, %s, D2, %s) next to J8 and P9.34/P9.39. One star point for GND/AGND (%s).\n"
    "SIGNALS\n"
    "  SYN_CLK/SYN_DATA/SYN_LE: SPI0 mode 0, MSB first, 32-bit words. SYN_LD is an input to the SBC. SYN_CE and SYN_PDR are static.\n"
    "  ATT_V1..V6 = 0.5, 1, 2, 4, 8, 16 dB (assumed, high = stage in). Verify with tools/bringup.py pe4302-walk.\n"
    "  BBB I2C2 (P9.19/20) and RPi I2C1 (pins 3/5) share I2C_SCL/I2C_SDA for the ADS1115.\n"
    "OPEN POINTS: PE4302 and ADF4351 header pin order, detector OUT pin, DC jack polarity, ferrite and fuse values: confirm with a DMM.\n"
    "Unused BBB/RPi pins carry no connection (X). Names of unused BBB pins come from the BBB system reference, not from the repo."
    % (REF_RT, REF_RB, REF_CB, REF_D1, REF_RS, REF_RS),
    17, 437, 1.15)

# --------------------------------------------------------------------------
# Output
# --------------------------------------------------------------------------
def schematic_text():
    o = ["(kicad_sch",
         "(version 20231120)",
         '(generator "eeschema")',
         '(generator_version "8.0")',
         '(uuid "%s")' % ROOT_UUID,
         '(paper "A1")',
         '(title_block (title "SAdiy SBC adapter") (date "2026-11-01") (rev "A") (company "SAdiy") '
         '(comment 1 "BeagleBone Black cape or Raspberry Pi ribbon, pin map from hw/netlist.md") '
         '(comment 2 "Generated by hw/boards/sbc-adapter/gen_schematic.py: edit the script, not this file"))',
         "(lib_symbols"]
    for name in D.used:
        o.append(SYMS[name].lib_sexp(LIB))
    o.append(")")
    o.extend(D.items)
    o.append('(sheet_instances (path "/" (page "1")))')
    o.append(")")
    return "\n".join(o) + "\n"


def symlib_text():
    o = ["(kicad_symbol_lib", "(version 20231120)", '(generator "kicad_symbol_editor")', '(generator_version "8.0")']
    for name in D.used:
        o.append(SYMS[name].lib_sexp(""))
    o.append(")")
    return "\n".join(o) + "\n"


def svg_text():
    css = ("<style>.w{stroke:#117a2a;stroke-width:.25}.sb{fill:#fff7d6;stroke:#8a1c1c;stroke-width:.25}"
           ".sp{fill:none;stroke:#8a1c1c;stroke-width:.25}.pn{stroke:#8a1c1c;stroke-width:.25}"
           ".lb{font:1.25px monospace;fill:#1f3fb5}.pt{font:1.05px monospace;fill:#155}.rf{font:1.25px monospace;fill:#066}"
           ".vl{font:1.2px monospace;fill:#066}.tx{font-family:monospace;fill:#333}.fr{fill:none;stroke:#999;stroke-width:.3;stroke-dasharray:2 1}"
           ".nc{stroke:#1f3fb5;stroke-width:.2;fill:none}</style>")
    return ('<svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 841 594" width="3364" height="2376">%s'
            '<rect width="841" height="594" fill="#fff"/>%s</svg>' % (css, "\n".join(D.svg)))


def main(out):
    os.makedirs(out, exist_ok=True)
    with open(os.path.join(out, PROJECT + ".kicad_sch"), "w") as f:
        f.write(schematic_text())
    with open(os.path.join(out, LIB + ".kicad_sym"), "w") as f:
        f.write(symlib_text())
    with open(os.path.join(out, "sym-lib-table"), "w") as f:
        f.write('(sym_lib_table\n  (version 7)\n  (lib (name "%s")(type "KiCad")(uri "${KIPRJMOD}/%s.kicad_sym")(options "")(descr "SAdiy adapter symbols"))\n)\n'
                % (LIB, LIB))
    pro = {"meta": {"filename": PROJECT + ".kicad_pro", "version": 1}, "sheets": [[ROOT_UUID, "Root"]],
           "text_variables": {}}
    with open(os.path.join(out, PROJECT + ".kicad_pro"), "w") as f:
        json.dump(pro, f, indent=2)
        f.write("\n")
    with open(os.path.join(out, "preview.svg"), "w") as f:
        f.write(svg_text())
    print("wrote", out, "items:", len(D.items))


if __name__ == "__main__":
    main(sys.argv[1] if len(sys.argv) > 1 else os.path.dirname(os.path.abspath(__file__)))
