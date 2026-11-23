#!/usr/bin/env python3
"""Generate docs/blockdiagram.svg: block diagram of the whole EBAZ_SAdiy design with the Verilog hierarchy.

Left to right: devices outside the FPGA, pads and I/O buffers (with FPGA pin locations and Linux EMIO line
numbers), the engine u_engine : sadiy_top with its instances, the block design u_bd (PS7, AXI protocol
converter, reset). Dashed frames are the Verilog hierarchy; dashed boxes are logic written inline in a parent.
Every wire has a short name and a colour by kind (legend at the bottom).

The drawing is hand-laid-out (coordinates below); the facts come from rtl/fpga/ebaz_sadiy_top.sv,
rtl/src/sadiy_top.sv, rtl/fpga/bd_ebaz_sadiy.tcl and the constraints (pin locations, docs/pinmap.md).
When ports, pins, EMIO lines or engine modules change, edit this file and regenerate:
    python3 rtl/scripts/gen_blockdiagram.py          # write docs/blockdiagram.svg
    python3 rtl/scripts/gen_blockdiagram.py --check  # exit 1 if the file is out of date
"""
import sys
from pathlib import Path
from xml.sax.saxutils import escape

OUT = Path(__file__).resolve().parents[2] / "docs" / "blockdiagram.svg"

OX, OY = 290, 60          # offset of the local drawing coordinates (pads start at local x 20)
W, H = 2370, 1430

frames, wires, boxes, texts, dots, top = [], [], [], [], [], []


def esc(s):
    return escape(s)


def X(x):
    return x + OX


def Y(y):
    return y + OY


def frame(x, y, w, h, inst, mod, src, cls):
    frames.append(f'<rect class="fr {cls}" x="{X(x)}" y="{Y(y)}" width="{w}" height="{h}" rx="10"/>')
    frames.append(f'<text class="frl {cls}" x="{X(x)+12}" y="{Y(y)+19}"><tspan class="fi">{esc(inst)}</tspan>'
                  f'<tspan> : {esc(mod)}</tspan><tspan class="fs" dx="10">{esc(src)}</tspan></text>')


def box(x, y, w, h, inst, mod, lines=(), cls="blk", tcls="bt"):
    boxes.append(f'<rect class="{cls}" x="{X(x)}" y="{Y(y)}" width="{w}" height="{h}" rx="5"/>')
    ty = y + 18
    if inst:
        boxes.append(f'<text class="bi" x="{X(x)+9}" y="{Y(ty)}">{esc(inst)}</text>')
        ty += 14
    if mod:
        boxes.append(f'<text class="bm" x="{X(x)+9}" y="{Y(ty)}">{esc(mod)}</text>')
        ty += 17
    pre = ' xml:space="preserve"' if "mono" in tcls else ""
    for ln in lines:
        boxes.append(f'<text class="{tcls}" x="{X(x)+9}" y="{Y(ty)}"{pre}>{esc(ln)}</text>')
        ty += 13


def device(x, y, w, h, title, lines):
    boxes.append(f'<rect class="dev" x="{X(x)}" y="{Y(y)}" width="{w}" height="{h}" rx="6"/>')
    boxes.append(f'<text class="dt" x="{X(x)+9}" y="{Y(y)+18}">{esc(title)}</text>')
    for i, ln in enumerate(lines):
        boxes.append(f'<text class="bt dim" x="{X(x)+9}" y="{Y(y)+32+13*i}">{esc(ln)}</text>')


def inline(x, y, w, h, title, note):
    boxes.append(f'<rect class="inl" x="{X(x)}" y="{Y(y)}" width="{w}" height="{h}" rx="5"/>')
    boxes.append(f'<text class="st" x="{X(x+w/2)}" y="{Y(y+h/2-2)}" text-anchor="middle">{esc(title)}</text>')
    boxes.append(f'<text class="bt dim" x="{X(x+w/2)}" y="{Y(y+h/2+12)}" text-anchor="middle">{esc(note)}</text>')


def sub(x, y, w, h, title, lines=(), cls="sub"):
    boxes.append(f'<rect class="{cls}" x="{X(x)}" y="{Y(y)}" width="{w}" height="{h}" rx="4"/>')
    boxes.append(f'<text class="st" x="{X(x+w/2)}" y="{Y(y+16)}" text-anchor="middle">{esc(title)}</text>')
    for i, ln in enumerate(lines):
        boxes.append(f'<text class="bt dim" x="{X(x+w/2)}" y="{Y(y+30+12*i)}" text-anchor="middle">{esc(ln)}</text>')


def mux(x, y, w, h, label, sel):
    pts = f"{X(x)},{Y(y)} {X(x+w)},{Y(y+10)} {X(x+w)},{Y(y+h-10)} {X(x)},{Y(y+h)}"
    boxes.append(f'<polygon class="inl" points="{pts}"/>')
    boxes.append(f'<text class="st" x="{X(x+w/2)}" y="{Y(y+h/2-2)}" text-anchor="middle">{esc(label)}</text>')
    if sel:
        boxes.append(f'<text class="bt dim" x="{X(x+w/2)}" y="{Y(y+h/2+11)}" text-anchor="middle">{esc(sel)}</text>')


PADW = 145


def pad(cy, name, kind, balls, dashed=False):
    """Pad cell centred on wire height cy: net name, buffer and EMIO line, FPGA pin locations."""
    x, y = 20, cy - 22
    cls = "pad dash" if dashed else "pad"
    boxes.append(f'<rect class="{cls}" x="{X(x)}" y="{Y(y)}" width="{PADW}" height="44" rx="3"/>')
    boxes.append(f'<text class="pn" x="{X(x)+7}" y="{Y(y)+13}">{esc(name)}</text>')
    boxes.append(f'<text class="bt dim" x="{X(x)+7}" y="{Y(y)+26}">{esc(kind)}</text>')
    boxes.append(f'<text class="ball" x="{X(x)+7}" y="{Y(y)+39}">{esc(balls)}</text>')


def wire(pts, cls, label=None, at=None, anchor="middle", start=False, end=True, rot=False):
    d = "M" + " L".join(f"{X(x)},{Y(y)}" for x, y in pts)
    me = f' marker-end="url(#a-{cls})"' if end else ""
    ms = f' marker-start="url(#s-{cls})"' if start else ""
    wires.append(f'<path class="halo{" hb" if cls == "bus" else ""}" d="{d}"/>')
    wires.append(f'<path class="w w-{cls}" d="{d}"{me}{ms}/>')
    if label:
        lx, ly = X(at[0]), Y(at[1])
        tr = f' transform="rotate(-90 {lx} {ly})"' if rot else ""
        texts.append(f'<text class="wl l-{cls}" x="{lx}" y="{ly}" text-anchor="{anchor}"{tr}>{esc(label)}</text>')


def dot(x, y, cls):
    dots.append(f'<circle class="d-{cls}" cx="{X(x)}" cy="{Y(y)}" r="3.8"/>')


def note(x, y, s, cls="bt", anchor="start", rot=False):
    tr = f' transform="rotate(-90 {X(x)} {Y(y)})"' if rot else ""
    texts.append(f'<text class="{cls}" x="{X(x)}" y="{Y(y)}" text-anchor="{anchor}"{tr}>{esc(s)}</text>')


# =============================================================== hierarchy frames
frame(10, 34, 2060, 1256, "ebaz_sadiy_top", "board top", "rtl/fpga/ebaz_sadiy_top.sv  (one clock: FCLK0 100 MHz)", "f0")
frame(270, 72, 1480, 1000, "u_engine", "sadiy_top", "rtl/src/sadiy_top.sv  (no pads, no vendor cells)", "f1")
frame(1790, 72, 270, 1000, "u_bd", "ebaz_sadiy_bd", "bd_ebaz_sadiy.tcl", "f2")
frame(870, 752, 660, 268, "u_if", "if_power", "if_power.sv", "f3")
note(20, 116, "pads, I/O buffers, FPGA pins", "hd")
note(-265, 116, "devices outside the FPGA", "hd dev-h")

# =============================================================== devices outside the FPGA
DX, DW = -265, 190
device(DX, 140, DW, 178, "ADF4351 eval board (LO)", ["25 MHz osc, 5 V DC jack", "header GND CE LE CLK LD",
                                                     "RF out -> AD831 LO in", "outputs on only after lock"])
device(DX, 334, DW, 52, "PE4302 module", ["V1..V6 = 0.5 .. 16 dB, high = in", "adapter pull-ups: 31.5 dB"])
device(DX, 400, DW, 112, "ADS1115 (I2C 0x48)", ["detector ADC, A0 vs GND", "read by the PL reader or PS I2C0",
                                                "analog: RF in -> PE4302 ->", "amp -> AD831 -> detector -> A0"])
device(DX, 896, DW, 48, "AD9226 module (not wired yet)", ["50 ohm SMA in, 5 V, 3.3 V logic"])
device(DX, 1090, DW, 44, "Adapter LCD, ST7789", ["SPI1 + DC / RES, Linux fbtft"])
device(DX, 1138, DW, 92, "Adapter LEDs, keys", ["LEDs 1..3: EMIO outputs", "keys 1..5: active low",
                                                          "Linux only, no PL logic"])
device(DX, 1234, DW, 44, "Ethernet PHY (EBAZ4205)", ["MII, 25 MHz clock from the PL"])

# =============================================================== pads
PR = 20 + PADW  # 155
pad(165, "adf4351_clk/dat/le", "3 output pads", "G20  G19  H20")
pad(230, "adf4351_ce", "IOBUF u_ce, EMIO n=6", "K19")
pad(295, "adf4351_ld", "input, also EMIO n=7", "J19")
pad(360, "pe4302_v[5:0]", "IOBUF g_pe, EMIO 0..5", "J20 L16 L19 M18 L20 M20")
pad(425, "i2c_scl", "IOBUF u_scl", "L17")
pad(490, "i2c_sda", "IOBUF u_sda", "K18")
pad(920, "adc_clk, adc_d, otr", "ADC_PADS build only", "DATA1, adapter v2", dashed=True)
pad(1112, "lcd_* (5 pins)", "SPI1, EMIO n=8, 9", "R19 P20 T20 R18 N17")
pad(1160, "led[2:0]", "OBUFT, EMIO n=10..12", "H18  K17  E19")
pad(1208, "keys[4:0]", "input, EMIO n=13..17", "T19 P19 U20 U19 V20")
pad(1256, "ENET0 MII, MDIO", "direct, IOBUF u_mdio", "U14..Y19, W15, Y14")

# =============================================================== engine blocks
box(280, 120, 150, 500, "u_pins", "pin_mux", [
    "owner = 0:", "  PS levels to the pins", "  (bench mode, Linux)", "owner = 1:", "  engine drives the pins",
    "  (sweep)", "", "ADF4351 SPI, CE,", "PE4302 V1..V6,", "ADS1115 SCL / SDA", "", "I2C to the PL reader",
    "only while i2c_pl = 1"])
inline(300, 665, 100, 52, "input sync", "2-FF, inline")

box(535, 100, 1195, 64, "u_regs", "axil_regs", [], cls="blk regs")
note(680, 124, "register file generated from regmap.toml by gen_regs.py, map 1.3 (VERSION 0x00010003), 4 KiB at 0x43C0_0000")
note(680, 140, "CTRL, STATUS, timing, PE4302, DET_CFG, TABLE_ADDR / W0 / W1, RESULT_ADDR / DATA (auto-increment), ADC_*, GEN_*, IF_*, FE_*", "bt dim")

box(545, 220, 170, 64, "u_spi", "adf4351_spi", ["32-bit word, MSB first"])
box(545, 330, 170, 64, "u_mbb", "pe4302_mbb", ["make-before-break step"])
inline(545, 445, 170, 50, "I2C handover", "inline, between samples")
box(545, 530, 170, 80, "u_adc", "ads1115_reader", ["I2C master, single shot", "NACK gives sample 0"])

box(815, 470, 160, 180, "u_det", "det_sampler", [])
sub(827, 518, 136, 54, "source select", ["0 push  1 test ramp", "2 stream  3 ADS1115"])
sub(827, 584, 136, 54, "n_avg accumulator", ["28-bit sum, then done"])

box(1110, 220, 200, 380, "u_seq", "sweep_seq", [
    "one table entry per step:", "",
    "IDLE", "FETCH      read entry", "ATT        PE4302 step", "SPI        ADF4351 word",
    "WAIT_MIN   T_MIN_US", "WAIT_LOCK  LD stable", "SETTLE     T_SETTLE_US", "SAMPLE     detector run",
    "STORE      result word", "NEXT", "", "abort, stop on error,", "lock timeout, counters"],
    cls="blk seq", tcls="bt mono")
mux(1115, 625, 50, 66, "path", "mode")

box(1400, 270, 160, 70, "u_table", "sdp_ram", ["table 4096 x 44 bit"])
box(1400, 410, 160, 70, "u_result", "sdp_ram", ["results 4096 x 32 bit"])
inline(1590, 216, 92, 40, "irq gate", "en AND done")

box(545, 780, 145, 110, "u_gen", "sample_gen", ["pattern player"])
box(545, 900, 145, 100, "u_fe", "adc_fe", ["FE_CFG: clock, phase", "tie-off / traffic gen", "or the pins", "u_adc: adc_ad9226"])
sub(557, 834, 121, 46, "u_ram : sdp_ram", ["4096 x 16 pattern"], cls="sub inst")
mux(745, 785, 40, 86, "src", "")

CX = [900 + i * 126 for i in range(5)]
for x, (t, l) in zip(CX, [("complex mixer", ["x cos, x sin"]), ("CIC, 3 stages", ["decimate by R"]),
                          ("shift, saturate", ["to 18 bit"]), ("I^2 + Q^2", ["power"]),
                          ("sum, normalise", ["exp / mant"])]):
    sub(x, 800, 92, 56, t, l)
sub(900, 925, 150, 60, "u_rom : nco_rom", ["2048 x 16 sin / cos"], cls="sub inst")
sub(1090, 925, 150, 60, "phase accumulator", ["32 bit, base + n * step"])

# =============================================================== block design
box(1808, 100, 236, 70, "axi_pc_0", "axi_protocol_converter", ["AXI3 to AXI4-Lite"], cls="blk amba")
box(1808, 195, 140, 66, "proc_sys_reset_0", "proc_sys_reset", [])
box(1808, 290, 236, 720, "processing_system7_0", "processing_system7 (PS7)", [
    "2x Cortex-A9, Linux", "sweepd -> /dev/mem", "DDR3, MIO[53:0]: not via PL", "",
    "M_AXI_GP0  0x43C0_0000", "IRQ_F2P[0]", "FCLK_CLK0  100 MHz", "",
    "EMIO SPI0  ADF4351", "EMIO I2C0  ADS1115", "EMIO GPIO 0..5  PE4302", "EMIO GPIO 6   ADF4351 CE",
    "EMIO GPIO 7   lock detect", "EMIO GPIO 8..17", "  LCD, LEDs, keys", "EMIO SPI1  LCD", "ENET0      MII",
    "", "Linux line = 54 + n"], cls="blk ps", tcls="bt mono")

# =============================================================== wires
# --- devices <-> pads
wire([(-75, 165), (20, 165)], "pin", "SPI writes", (-27, 159), start=True, end=False)
wire([(20, 230), (-75, 230)], "pin", "CE, high = on", (-27, 224))
wire([(-75, 295), (20, 295)], "pin", "lock detect", (-27, 289))
wire([(20, 360), (-75, 360)], "pin", "V1..V6 levels", (-27, 354))
wire([(20, 425), (-75, 425)], "pin", "I2C clock", (-27, 419))
wire([(20, 490), (-75, 490)], "pin", "I2C data", (-27, 484), start=True)
wire([(-75, 920), (20, 920)], "data", "ADC samples", (-27, 914))
wire([(20, 1112), (-75, 1112)], "ps", "display bus", (-27, 1106))
wire([(20, 1160), (-75, 1160)], "ps", "LED drive", (-27, 1154))
wire([(-75, 1208), (20, 1208)], "ps", "key levels", (-27, 1202))
wire([(-75, 1256), (20, 1256)], "ps", "MII, MDIO", (-27, 1250), start=True)

# --- pads <-> pin mux
wire([(280, 165), (PR, 165)], "pin", "ADF4351 SPI pins", (222, 159))
wire([(280, 230), (PR, 230)], "pin", "synth enable pin", (226, 224), start=True)
wire([(280, 360), (PR, 360)], "pin", "attenuator pins", (226, 354), start=True)
wire([(280, 425), (PR, 425)], "pin", "ADS1115 clock", (226, 419), start=True)
wire([(280, 490), (PR, 490)], "pin", "ADS1115 data", (226, 484), start=True)

# --- pad level sense bus (x = 172): synchronisers, reader SDA, PS GPIO readback
wire([(PR, 295), (172, 295)], "sense", None, end=False)
wire([(172, 230), (172, 691), (300, 691)], "sense", "pad level sense", (166, 600), rot=True)
wire([(172, 640), (515, 640), (515, 597), (545, 597)], "sense", "SDA input level", (440, 634))
wire([(172, 691), (172, 1058), (1782, 1058), (1782, 870), (1808, 870)], "sense", "GPIO readback lines", (1250, 1052))
for y in (230, 295, 360, 425, 490, 640, 691):
    dot(172, y, "sense")

# --- synchronisers
wire([(400, 691), (745, 691), (745, 455), (1110, 455)], "ctl", "lock detect sync", (930, 449))
wire([(350, 717), (350, 730)], "cfg", "pin state bits", (356, 750), anchor="start")

# --- register field bus: thick, from the synchronisers along the engine, trunk up to u_regs
wire([(350, 730), (1712, 730), (1712, 164)], "bus", "register field bus", (1460, 724), end=False)
note(1704, 470, "config and status fields", "wl l-bus", "middle", rot=True)

# --- regs -> pin mux, drivers, sequencer, irq
wire([(535, 150), (430, 150)], "cfg", "synth enable bit", (482, 144))
wire([(630, 164), (630, 220)], "cfg", "SPI clock divider", (636, 198), anchor="start")
wire([(735, 164), (735, 345), (715, 345)], "cfg", "MBB gap, polarity", (741, 312), anchor="start")
wire([(1150, 164), (1150, 220)], "cfg", "sweep control, timing", (1144, 198), anchor="end")
wire([(1270, 220), (1270, 164)], "cfg", "sweep status counters", (1276, 198), anchor="start")
wire([(1636, 164), (1636, 216)], "cfg", "irq enable", (1630, 196), anchor="end")

# --- drivers -> pin mux
wire([(545, 252), (430, 252)], "pin", "engine SPI frame", (487, 246))
wire([(545, 362), (430, 362)], "pin", "attenuator drive", (487, 356))
wire([(545, 470), (430, 470)], "ctl", "I2C owner select", (487, 464))
wire([(545, 560), (430, 560)], "pin", "reader I2C drive", (487, 554))

# --- sequencer <-> drivers, pin owner
wire([(1110, 252), (715, 252)], "ctl", "LO word handshake", (930, 246), start=True)
wire([(1110, 378), (715, 378)], "ctl", "attenuator step handshake", (930, 372), start=True)
wire([(1110, 420), (430, 420)], "ctl", "pin owner active", (930, 414))
wire([(630, 420), (630, 445)], "ctl")
dot(630, 420, "ctl")
wire([(630, 495), (630, 530)], "ctl", "reader run gate", (636, 517), anchor="start")

# --- detector samples
wire([(715, 545), (815, 545)], "data", "ADC samples", (780, 539))
wire([(1110, 520), (975, 520)], "ctl", "measure run gate", (1042, 514))
wire([(1080, 520), (1080, 752)], "ctl")
dot(1080, 520, "ctl")
wire([(975, 640), (1115, 640)], "data", "video power sum", (1024, 634))
wire([(1496, 828), (1550, 828), (1550, 660), (1165, 660)], "data", "IF power sum", (1380, 654))
wire([(1140, 625), (1140, 600)], "data", "point power sum", (1146, 617), anchor="start")

# --- sample stream
wire([(690, 808), (745, 808)], "data", "test stream", (717, 801))
wire([(PR, 920), (545, 920)], "data", "ADC data lines", (350, 914))
wire([(690, 920), (728, 920), (728, 858), (745, 858)], "data", "front-end stream", (700, 914), anchor="middle")
wire([(785, 828), (900, 828)], "data", "IF sample stream", (852, 846))
wire([(830, 828), (830, 650)], "data", "video sample stream", (824, 712), anchor="end")
dot(830, 828, "data")

# --- bus taps
wire([(680, 730), (680, 610)], "cfg", "reader config, status", (674, 662), anchor="end", start=True)
wire([(630, 730), (630, 780)], "cfg", "pattern upload", (624, 760), anchor="end")
wire([(765, 730), (765, 790)], "cfg", "stream source select", (759, 778), anchor="end")
wire([(930, 730), (930, 650)], "cfg", "sampler source, push", (936, 700), anchor="start")
wire([(1150, 730), (1150, 686)], "cfg", "path mode select", (1156, 712), anchor="start")
wire([(1300, 730), (1300, 752)], "cfg", "NCO, CIC settings", (1306, 747), anchor="start")
wire([(1712, 305), (1560, 305)], "cfg", "table upload write", (1636, 299))
wire([(1560, 445), (1712, 445)], "cfg", "result readout data", (1636, 439))
for x, y in [(680, 730), (630, 730), (765, 730), (930, 730), (1150, 730), (1300, 730), (1712, 305), (1712, 445)]:
    dot(x, y, "cfg")

# --- sequencer <-> memories, irq
wire([(1310, 305), (1400, 305)], "ctl", "table entry fetch", (1355, 299), start=True)
wire([(1310, 445), (1400, 445)], "data", "result write", (1355, 439))
wire([(1310, 236), (1590, 236)], "ctl", "sweep done flag", (1450, 230))

# --- IF chain inside u_if
for i, s in enumerate(["I/Q products", "decimated I/Q", "18-bit I/Q", "power samples"]):
    x0 = CX[i] + 92
    wire([(x0, 828), (CX[i + 1], 828)], "data")
    note((x0 + CX[i + 1]) / 2, 794, s, "wl l-data", "middle")
wire([(946, 925), (946, 856)], "data", "sin cos pair", (952, 896), anchor="start")
wire([(1090, 955), (1050, 955)], "data", "table address", (1070, 1004))

# --- AMBA and PS side
wire([(1730, 132), (1808, 132)], "amba", "AXI4-Lite bus", (1769, 124), start=True)
wire([(2000, 170), (2000, 290)], "amba", "AXI3 GP0 master", (1994, 230), start=True, rot=True)
wire([(1682, 236), (1765, 236), (1765, 330), (1808, 330)], "amba", "sweep done irq", (1759, 283), rot=True)
wire([(1808, 215), (1750, 215)], "ps", "sync reset", (1779, 209))
wire([(1878, 290), (1878, 261)], "ps", "FCLK0 clock", (1884, 280), anchor="start")
wire([(1808, 600), (1750, 600)], "ps", "fabric clock", (1779, 594))
wire([(1808, 840), (1772, 840), (1772, 1045), (288, 1045), (288, 620)], "ps",
     "PS pin levels (EMIO SPI0, I2C0, GPIO 0..6)", (720, 1039), start=True)
wire([(PR, 1112), (1830, 1112), (1830, 1010)], "ps", "LCD SPI1, DC, RES", (1000, 1106), start=True, end=False)
wire([(PR, 1160), (1880, 1160), (1880, 1010)], "ps", "LED lines", (1000, 1154), start=True, end=False)
wire([(PR, 1208), (1930, 1208), (1930, 1010)], "ps", "key lines", (1000, 1202))
wire([(PR, 1256), (1990, 1256), (1990, 1010)], "ps", "Ethernet MII, MDIO", (1000, 1250), start=True)

# =============================================================== title, legend
top.append(f'<text class="ttl" x="30" y="34">SAdiy on EBAZ4205 (XC7Z010): PL sweep engine, pads and devices</text>')
top.append('<text class="bt dim" x="30" y="52">Source: rtl/fpga/ebaz_sadiy_top.sv, rtl/src/*.sv, rtl/fpga/bd_ebaz_sadiy.tcl, '
           'constraints. Generated by rtl/scripts/gen_blockdiagram.py. FPGA pins: docs/pinmap.md. '
           'Dashed frames = Verilog hierarchy (instance : module); dashed boxes = logic inline in the parent; '
           'crossings without a dot are not connected. Clock and reset from u_bd reach every engine block.</text>')

LEG = [("pin", "pin-level signals"), ("sense", "pad levels read back"), ("ctl", "sequencer control"),
       ("data", "sample and power data"), ("cfg", "register fields"), ("bus", "register field bus"),
       ("amba", "AMBA: AXI, interrupt"), ("ps", "PS side: EMIO, clock, reset")]
LY = H - 24
for i, (c, s) in enumerate(LEG):
    x = 30 + 215 * i
    top.append(f'<path class="w w-{c}" d="M{x},{LY - 4} L{x + 34},{LY - 4}"/>')
    top.append(f'<text class="bt" x="{x + 42}" y="{LY}">{esc(s)}</text>')
top.append(f'<text class="bt dim" x="{30 + 215 * 8 + 20}" y="{LY}">not built yet: ADC pads (ADC_PADS), '
           f'FFT, PL access to keys / LEDs</text>')

# =============================================================== output
STYLE = """
.ground{fill:#ffffff}
text{font-family:'DejaVu Sans',Verdana,sans-serif}
.ttl{font-size:18px;font-weight:bold;fill:#1b2227}
.fr{fill:none;stroke-width:1.6;stroke-dasharray:7 5}
.fr.f0{stroke:#8b969d}.fr.f1{stroke:#2a6f93}.fr.f2{stroke:#7a52a3}.fr.f3{stroke:#b0641c}
.frl{font-family:'DejaVu Sans Mono',monospace;font-size:12.5px}
.frl.f0{fill:#6b767d}.frl.f1{fill:#2a6f93}.frl.f2{fill:#7a52a3}.frl.f3{fill:#b0641c}
.fi{font-weight:bold}.fs{font-family:'DejaVu Sans',sans-serif;font-size:10.5px}
.blk{fill:#ffffff;stroke:#36424b;stroke-width:1.3}
.blk.regs{fill:#f1ecfa;stroke:#7446c0}.blk.seq{fill:#eaf1fa;stroke:#2160b0}
.blk.ps{fill:#e9f5f0;stroke:#3c7c3c}.blk.amba{fill:#e4f4ee;stroke:#0b8a68}
.dev{fill:#fdf1e2;stroke:#b8651b;stroke-width:1.3}
.dt{font-size:12px;font-weight:bold;fill:#8a4a12}
.inl{fill:#eef1f0;stroke:#36424b;stroke-width:1;stroke-dasharray:3 3}
.sub{fill:#f4f6f5;stroke:#c9d1d0;stroke-width:1}.sub.inst{stroke:#b0641c;stroke-dasharray:4 3}
.pad{fill:#f4f6f5;stroke:#4f5f6b;stroke-width:1.2}.pad.dash{stroke-dasharray:4 3}
.bi{font-family:'DejaVu Sans Mono',monospace;font-weight:bold;font-size:12px;fill:#1b2227}
.bm{font-family:'DejaVu Sans Mono',monospace;font-size:11px;fill:#5d6a73}
.bt{font-size:10.5px;fill:#1b2227}.dim{fill:#5d6a73}
.bt.mono{font-family:'DejaVu Sans Mono',monospace;font-size:10px}
.st{font-family:'DejaVu Sans Condensed','Liberation Sans Narrow','Arial Narrow',sans-serif;font-weight:bold;font-size:11.5px;fill:#1b2227}
.pn{font-family:'DejaVu Sans Mono',monospace;font-weight:bold;font-size:10px;fill:#1b2227}
.ball{font-family:'DejaVu Sans Mono',monospace;font-size:9px;fill:#2a6f93}
.hd{font-weight:bold;font-size:11.5px;fill:#6b767d}.dev-h{fill:#b8651b}
.halo{fill:none;stroke:#ffffff;stroke-width:8;stroke-linejoin:round}.hb{stroke-width:14}
.w{fill:none;stroke-width:1.8;stroke-linejoin:round}
.w-pin{stroke:#4f5f6b}.w-sense{stroke:#6f8291;stroke-dasharray:5 3}.w-ctl{stroke:#2160b0}
.w-data{stroke:#c45a12;stroke-width:2.2}.w-cfg{stroke:#7446c0}.w-bus{stroke:#7446c0;stroke-width:6}
.w-amba{stroke:#0b8a68;stroke-width:4}.w-ps{stroke:#3c7c3c}
.m-pin{fill:#4f5f6b}.m-sense{fill:#6f8291}.m-ctl{fill:#2160b0}.m-data{fill:#c45a12}
.m-cfg,.m-bus{fill:#7446c0}.m-amba{fill:#0b8a68}.m-ps{fill:#3c7c3c}
.d-sense{fill:#6f8291}.d-ctl{fill:#2160b0}.d-data{fill:#c45a12}.d-cfg{fill:#7446c0}
.wl{font-family:'DejaVu Sans Condensed','Liberation Sans Narrow','Arial Narrow',sans-serif;font-size:10.5px;paint-order:stroke;stroke:#ffffff;stroke-width:4px;stroke-linejoin:round}
.l-pin{fill:#4f5f6b}.l-sense{fill:#5d6f7d}.l-ctl{fill:#2160b0}.l-data{fill:#b4520f}
.l-cfg,.l-bus{fill:#7446c0}.l-amba{fill:#0b7a5c;font-weight:bold}.l-ps{fill:#3c7c3c}
"""

WCLS = ["pin", "sense", "ctl", "data", "cfg", "bus", "amba", "ps"]
markers = []
for c in WCLS:
    markers.append(f'<marker id="a-{c}" viewBox="0 0 10 10" refX="9" refY="5" markerWidth="7" markerHeight="7" '
                   f'orient="auto"><path class="m-{c}" d="M0,1 L10,5 L0,9 z"/></marker>')
    markers.append(f'<marker id="s-{c}" viewBox="0 0 10 10" refX="1" refY="5" markerWidth="7" markerHeight="7" '
                   f'orient="auto"><path class="m-{c}" d="M10,1 L0,5 L10,9 z"/></marker>')

parts = [f'<svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 {W} {H}" width="{W}" height="{H}" role="img" '
         f'aria-label="Block diagram of the SAdiy PL sweep engine on the EBAZ4205 with the Verilog hierarchy">',
         f'<style>{STYLE}</style>', f'<defs>{"".join(markers)}</defs>',
         f'<rect class="ground" x="0" y="0" width="{W}" height="{H}"/>']
text = "\n".join(parts + frames + wires + boxes + dots + texts + top + ["</svg>"]) + "\n"

if "--check" in sys.argv:
    if not OUT.exists() or OUT.read_text() != text:
        print("blockdiagram.svg is out of date")
        sys.exit(1)
    print("blockdiagram.svg is current")
else:
    OUT.write_text(text)
    print(f"wrote {OUT}")
