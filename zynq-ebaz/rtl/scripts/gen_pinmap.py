#!/usr/bin/env python3
"""Pin map report of the EBAZ4205 design: docs/pinmap.md (table) and docs/pinmap.svg (picture).

Sources (read only):
  rtl/fpga/constraints/data2_pins.xdc   pins that are constrained in the build (= "in use")
  rtl/fpga/constraints/eth.xdc          Ethernet PHY pins (board fixed)
  rtl/fpga/constraints/adapter_ui.xdc   display, keys, LEDs of the HelloFPGA adapter board
  pins.toml of session L                names, connector pins and notes; entries with active = false are "planned"
  rtl/fpga/ps7_config.tcl               MIO use (SD card, console UART)
  rtl/fpga/clg400_pins.csv              package table (bank, I/O name, site), from dump_package.tcl
Output: docs/pinmap.md, docs/pinmap.svg (connectors), docs/pinmap-fpga.svg (ball map of the package),
        docs/pinmap-adapter.svg (the HelloFPGA adapter board: what is where)
Usage: python3 gen_pinmap.py [--check]
"""
import csv
import re
import sys
import tomllib
from pathlib import Path

RTL = Path(__file__).resolve().parents[1]
EBAZ = RTL.parent
OUT_MD, OUT_SVG = EBAZ / "docs/pinmap.md", EBAZ / "docs/pinmap.svg"
OUT_BALLS = EBAZ / "docs/pinmap-fpga.svg"
OUT_ADAPTER = EBAZ / "docs/pinmap-adapter.svg"


def find_pins_toml():
    for p in (RTL / "vivado/pins.toml", EBAZ.parent.parent / "SAdiy-linux/zynq-ebaz/rtl/vivado/pins.toml"):
        if p.exists():
            return p
    sys.exit("pins.toml not found")


def package():
    """{ball: (bank, io function, site)} for xc7z010clg400."""
    with open(RTL / "fpga/clg400_pins.csv") as f:
        return {r["ball"]: (r["bank"], r["function"], r["site"]) for r in csv.DictReader(f)}


def used_balls():
    """{port name: ball} from the XDC files of the build."""
    d = {}
    for f in ("constraints/data2_pins.xdc", "constraints/eth.xdc", "constraints/adapter_ui.xdc"):
        for line in (RTL / "fpga" / f).read_text().splitlines():
            if line.lstrip().startswith("#"):
                continue                       # commented-out constraints are not in the build
            m = re.search(r"PACKAGE_PIN (\w+).*get_ports \{?([\w\[\]]+)\}?\]", line)
            if m:
                d[m.group(2)] = m.group(1)
    return d


FUNC = {  # signal prefix -> (function, colour)
    "adf4351": ("ADF4351 synthesiser", "#2f6fdb"),
    "pe4302": ("PE4302 attenuator", "#e07b00"),
    "i2c": ("I2C, ADS1115", "#2a9d4b"),
    "adc": ("AD9226 (planned)", "#6b6b6b"),
    "spare": ("spare", "#c8c8c8"),
}


def func_of(name):
    for k, v in FUNC.items():
        if name.startswith(k):
            return v
    return ("other", "#999")


def load():
    toml = tomllib.loads(find_pins_toml().read_text())
    used = used_balls()
    rows = []
    for s in toml["signal"]:
        port = s["name"]
        rows.append(dict(conn=s["connector"], pin=int(s["pin"]), name=port, ball=s["ball"], dir=s["dir"],
                         note=s.get("note", ""), used=port in used and used[port] == s["ball"],
                         planned=not s.get("active", False)))
    return rows


def fixed_balls():
    """Ethernet ports and their balls, from eth.xdc."""
    return sorted(((b, p) for p, b in used_balls().items() if p.startswith(("ENET0", "enet0"))),
                  key=lambda t: t[0])


ADAPTER_PREFIX = ("lcd_", "keys", "led")
ADAPTER_NOTE = {"lcd_cs": "LCD_PIN CS", "lcd_dc": "LCD_PIN DC", "lcd_scl": "LCD_PIN SCL", "lcd_sda": "LCD_PIN SDA",
                "lcd_res": "LCD_PIN RES", "keys[0]": "KEY1", "keys[1]": "KEY2", "keys[2]": "KEY3",
                "keys[3]": "KEY4", "keys[4]": "KEY5", "led[0]": "LED1", "led[1]": "LED2", "led[2]": "LED3"}


def adapter_balls():
    """(ball, port) of the adapter board's display, keys and LEDs, from adapter_ui.xdc."""
    return sorted(((b, p) for p, b in used_balls().items() if p.startswith(ADAPTER_PREFIX)),
                  key=lambda t: (t[1].split("[")[0], t[1]))


# Right-hand 2x10 connector of the adapter (photo docs/20261114_134742.heic), silk text, row 1 at the top.
# Row 3 reads "U20" on the silk but must be J20 (U20 is KEY3, J20 is DATA2-14): verify on the board.
RIGHT_CONN = [("K18", "J18"), ("G19", "G20"), ("J20", "H20"), ("K19", "J19"), ("L20", "L19"), ("L17", "L16"),
              ("M20", "M18"), ("M19", "N20"), ("P18", "M17"), ("GND", "3V3")]
# HDMI port of the adapter: TMDS pairs as P/N balls (P/N from the package: D19/D20 = L4P/N etc.). The silk gives
# only the positive nets; the negatives are inferred from the package pairing: verify with a meter.
HDMI = [("DAT0", "D19", "D20"), ("DAT1", "C20", "B20"), ("DAT2", "B19", "A20"), ("CLK", "F19", "F20")]
# PROPOSAL (not in pins.toml): AD9226 on the HDMI pairs plus the free pins of the right connector.
ADC_PROPOSAL = [("adc_d[0]", "A20", "HDMI DAT2 N"), ("adc_d[1]", "B19", "HDMI DAT2 P"),
                ("adc_d[2]", "B20", "HDMI DAT1 N"), ("adc_d[3]", "C20", "HDMI DAT1 P"),
                ("adc_d[4]", "D20", "HDMI DAT0 N"), ("adc_d[5]", "J18", "right connector row 1"),
                ("adc_d[6]", "D19", "HDMI DAT0 P"), ("adc_d[7]", "F20", "HDMI CLK N"),
                ("adc_d[8]", "M19", "right connector row 8"), ("adc_d[9]", "F19", "HDMI CLK P"),
                ("adc_d[10]", "N20", "right connector row 8"), ("adc_d[11]", "P18", "right connector row 9"),
                ("adc_clk", "M17", "right connector row 9"), ("adc_otr", "H16", "UART header (remove its jumper)")]
# Adapter functions that share a DATA1 ball with the planned AD9226 pins.
DATA1_ON_ADAPTER = {"H18": "LED1", "K17": "LED2", "E19": "LED3", "H16": "UART header RX", "H17": "UART header TX",
                    "D19": "HDMI DAT0", "C20": "HDMI DAT1", "B19": "HDMI DAT2", "F19": "HDMI CLK", "D18": "buzzer"}
FIXED = [  # board-fixed functions: (group, signal, ball or MIO, note)
    ("Ethernet PHY (MII on EMIO)", "phy clk 25 MHz (FCLK1)", "U18", "out"),
    ("Ethernet PHY (MII on EMIO)", "MDC / MDIO", "W15 / Y14", "out / inout"),
    ("Ethernet PHY (MII on EMIO)", "RX_CLK, RX_DV, RX_ER", "U14, W16, G17", "in"),
    ("Ethernet PHY (MII on EMIO)", "RXD[3:0]", "Y17, V17, V16, Y16", "in"),
    ("Ethernet PHY (MII on EMIO)", "TX_CLK, TX_EN", "U15, W19", "in / out"),
    ("Ethernet PHY (MII on EMIO)", "TXD[3:0]", "Y19, V18, Y18, W18", "out"),
    ("Adapter board (display, keys, LEDs)", "LCD CS, DC, SCL, SDA, RES", "T20 R18 R19 P20 N17", "out"),
    ("Adapter board (display, keys, LEDs)", "KEY1..KEY5", "T19 P19 U20 U19 V20", "in"),
    ("Adapter board (display, keys, LEDs)", "LED1..LED3", "H18 K17 E19", "out"),
    ("PS MIO (fixed pins)", "SD card (TF) SD0", "MIO 40..45", "boot"),
    ("PS MIO (fixed pins)", "console UART1 (J7)", "MIO 24..25", "115200"),
]


def md(rows):
    L = ["# Pin map (generated by rtl/scripts/gen_pinmap.py, do not edit)", "",
         "Reference: EBAZ4205 (XC7Z010-CLG400), expansion connectors DATA1..3 (2.0 mm, 2x10). All I/O LVCMOS33, "
         "series 22 ohm on the board. Master list: `rtl/vivado/pins.toml` (session L). "
         "\"In use\" = constrained in the current bitstream.", "",
         "## Expansion connectors", "",
         "| Connector pin | FPGA ball | Bank | I/O name | Signal | Dir | Function | Status | EMIO / note |",
         "|---|---|---|---|---|---|---|---|---|"]
    pk = package()
    for r in sorted(rows, key=lambda r: (r["conn"], r["pin"])):
        L.append(f"| {r['conn']}-{r['pin']} | {r['ball']} | {pk[r['ball']][0]} | {pk[r['ball']][1]} | "
                 f"`{r['name']}` | {r['dir']} | {func_of(r['name'])[0]} | "
                 f"{'in use' if r['used'] else 'planned' if r['planned'] else 'NOT constrained'} | {r['note']} |")
    L += ["", "Supply / ground per the plan: pins 1-2 of every connector are supply (5..12 V, never wire to a "
          "peripheral), 3-4 and 12 GND, 10 NC. DATA3 is not mapped yet.", "",
          "## Board-fixed pins, one line each", "",
          "| FPGA ball / pin | Bank | I/O name | Signal | Group |", "|---|---|---|---|---|"]
    for ball, port in fixed_balls():
        bank, fn, _ = pk[ball]
        L.append(f"| {ball} | {bank} | {fn} | `{port}` | Ethernet PHY (MII on EMIO) |")
    for mio, what in [(24, "UART1 TX/RX (console, J7)"), (25, "UART1 TX/RX (console, J7)")] + \
            [(n, "SD0 (boot card)") for n in range(40, 46)]:
        for ball, (bank, fn, _) in pk.items():
            if fn.startswith(f"PS_MIO{mio}_"):
                L.append(f"| {ball} | {bank} | {fn} | MIO {mio} | {what} |")
    L += ["", "Bank 34 and 35 are the PL I/O banks (3.3 V here); banks 500 and 501 are the PS MIO banks. "
          "Package ball map: `pinmap-fpga.svg`.", ""]
    L += ["", "## Adapter board (HelloFPGA EBAZ4205_ZJB05): display, keys, LEDs", "",
          "Constrained in `rtl/fpga/constraints/adapter_ui.xdc`. Keys and LEDs are EMIO "
          "GPIO for Linux (keys 13..17, active low with pull-up; LEDs 10..12, polarity not verified), no PL logic. "
          "The LCD (ST7789) also belongs to Linux: SCL / SDA / CS = PS SPI1 on EMIO, DC / RES = EMIO GPIO "
          "8 / 9 (Linux lines 62 / 63); no PL logic. See `lcd-st7789.md`.", "",
          "| Adapter silk | FPGA ball | Bank | I/O name | Port | Dir |", "|---|---|---|---|---|---|"]
    for ball, port in adapter_balls():
        L.append(f"| {ADAPTER_NOTE.get(port, '')} | {ball} | {pk[ball][0]} | {pk[ball][1]} | `{port}` | "
                 f"{'in' if port.startswith('keys') else 'out'} |")
    L += ["", "Present on the adapter but not constrained: HDMI (DAT0 D19, DAT1 C20, DAT2 B19, CLK F19), buzzer D18, "
          "UART header H16 (RX) / H17 (TX).", "",
          "### Right-hand connector of the adapter (to the SAdiy PCBs), row 1 at the top", "",
          "| Row | Left | Signal | Right | Signal |", "|---|---|---|---|---|"]
    port_of = {b: p for p, b in used_balls().items()}
    spare = {"J18": "spare_d2_6"}
    for i, (a, b) in enumerate(RIGHT_CONN, 1):
        def sig(x):
            if x in ("GND", "3V3"):
                return x
            return f"`{port_of.get(x, spare.get(x, 'free'))}`"
        L.append(f"| {i} | {a} | {sig(a)} | {b} | {sig(b)} |")
    free = [x for r in RIGHT_CONN for x in r if x not in ("GND", "3V3") and x not in port_of]
    L += ["", f"All 14 DATA2 control balls are on this connector. Free for the PCBs: {', '.join(free)} "
          "(J18 is DATA2-6, the others come from DATA3).", "",
          "### Conflict with the planned AD9226 on DATA1", "",
          "With this adapter the following planned `adc_*` balls are also wired to adapter functions: " +
          ", ".join(f"{b} ({f})" for b, f in DATA1_ON_ADAPTER.items() if b in {r['ball'] for r in rows}) +
          ". The right-hand connector carries no DATA1 signals, so the AD9226 cannot use DATA1 with this adapter.",
          "",
          "### Proposal: AD9226 through the HDMI port", "",
          "The HDMI port carries four differential pairs (DAT0, DAT1, DAT2, CLK) = 8 FPGA balls, exactly 8 of the "
          "14 planned AD9226 balls. With the 5 free balls of the right connector that makes 13: 12 data bits and "
          "the clock; OTR needs one more (the UART header H16 once its jumper is removed, or leave it out). "
          "Used as single-ended LVCMOS33. NOT in `pins.toml`; the Linux lane owns that file.", "",
          "| AD9226 signal | Ball | Where | Bank | I/O name |", "|---|---|---|---|---|"]
    for sig_, ball, where in ADC_PROPOSAL:
        L.append(f"| `{sig_}` | {ball} | {where} | {pk[ball][0]} | {pk[ball][1]} |")
    L += ["", "To check before wiring: (1) continuity from each HDMI pad to its EBAZ DATA1 pin and that no series "
          "resistor, termination or ESD part sits on it; (2) that the negative balls reach the HDMI pins (the "
          "silk only names the positive nets); (3) the HDMI +5 V and shield pins must never touch a signal line; "
          "(4) which pad of your HDMI breakout is which TMDS line.", ""]
    L += ["", "## EMIO line map (Linux GPIO line = 54 + n on the Zynq gpiochip)", "",
          "| n | Signal | n | Signal |", "|---|---|---|---|"]
    emio = ["pe4302_v[0] (V1)", "pe4302_v[1] (V2)", "pe4302_v[2] (V3)", "pe4302_v[3] (V4)", "pe4302_v[4] (V5)",
            "pe4302_v[5] (V6)", "adf4351_ce", "adf4351_ld"]
    second = ["lcd_dc (adapter LCD)", "lcd_res (adapter LCD)", "led[0] (adapter)", "led[1] (adapter)",
              "led[2] (adapter)", "keys[0] (adapter, active low)", "keys[1] (adapter, active low)",
              "keys[2] (adapter, active low)", "keys[3] (adapter, active low)", "keys[4] (adapter, active low)"]
    L += [f"| {i} | {emio[i]} | {i + 8} | {second[i]} |" for i in range(8)]
    L += [f"| | | {i + 8} | {second[i]} |" for i in range(8, 10)]
    L += ["", "Since register map 1.1 `adf4351_ce` and the I2C pins pass the engine's pin mux: while the engine owns the pins "
          "CE follows `ADF_PINS.ce`, and with `DET_CFG.src = 3` the PL reads the ADS1115 itself.", "",
          "Also on EMIO: SPI0 (SCLK, MOSI, SS0 = LE), SPI1 (adapter LCD: SCLK, MOSI, SS0) and I2C0 (SCL, SDA), "
          "see the tables above.", ""]
    return "\n".join(L)


# ------------------------------------------------------------------ SVG
def svg(rows):
    by = {(r["conn"], r["pin"]): r for r in rows}
    W, H = 1560, 820
    o = [f'<svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 {W} {H}" font-family="Helvetica,Arial,sans-serif" '
         f'font-size="12">',
         '<title>EBAZ4205 pin map</title>',
         f'<rect width="{W}" height="{H}" fill="#fff"/>',
         '<text x="20" y="30" font-size="20" font-weight="bold">EBAZ4205 pin map (current bitstream)</text>',
         '<text x="20" y="50" fill="#555">XC7Z010-CLG400, I/O LVCMOS33, 22 ohm series on the board. '
         'Pin numbering of the 2x10 headers: row n holds pins 2n-1 | 2n (orientation not verified on the board).</text>',
         # board
         '<rect x="20" y="70" width="1120" height="730" rx="14" fill="#1f7a4d" stroke="#0f4a2d" stroke-width="3"/>',
         '<text x="580" y="98" text-anchor="middle" fill="#dff5e6" font-size="14" font-weight="bold">'
         'EBAZ4205 (top view, schematic arrangement)</text>',
         '<rect x="500" y="640" width="160" height="60" rx="6" fill="#16603b" stroke="#0f4a2d"/>',
         '<text x="580" y="665" text-anchor="middle" fill="#dff5e6">Zynq XC7Z010</text>',
         '<text x="580" y="683" text-anchor="middle" fill="#dff5e6" font-size="11">PS: SD, UART1, EMIO</text>']
    # connectors
    cols = {"DATA1": 60, "DATA2": 420, "DATA3": 780}
    top = 150
    rh = 44
    for conn, x0 in cols.items():
        o.append(f'<rect x="{x0 + 82}" y="{top - 28}" width="76" height="{rh * 10 + 20}" rx="5" fill="#222"/>')
        o.append(f'<text x="{x0 + 120}" y="{top - 36}" text-anchor="middle" fill="#fff" font-weight="bold" '
                 f'font-size="15">{conn}</text>')
        for n in range(10):
            y = top + n * rh
            for side, pin in (("L", 2 * n + 1), ("R", 2 * n + 2)):
                r = by.get((conn, pin))
                cx = x0 + 102 if side == "L" else x0 + 138
                if r:
                    col = func_of(r["name"])[1]
                    dash = ' stroke-dasharray="3 2"' if r["planned"] else ""
                    fill = "#fff" if r["planned"] else col
                    pc = col if r["planned"] else "#fff"
                else:
                    col, dash, fill, pc = "#777", "", "#d9d9d9", "#222"
                o.append(f'<circle cx="{cx}" cy="{y}" r="13" fill="{fill}" stroke="{col}" stroke-width="2"{dash}/>')
                o.append(f'<text x="{cx}" y="{y + 4}" text-anchor="middle" font-size="11" font-weight="bold" '
                         f'fill="{pc if r else "#222"}">{pin}</text>')
                if r:
                    nm = r["name"]
                    lab = f'{nm}  [{r["ball"]}]'
                    tx = x0 + 82 - 10 if side == "L" else x0 + 158 + 10
                    anchor = "end" if side == "L" else "start"
                    o.append(f'<text x="{tx}" y="{y + 4}" text-anchor="{anchor}" font-size="11" fill="#fff">'
                             f'{lab}</text>')
                else:
                    tx = x0 + 82 - 10 if side == "L" else x0 + 158 + 10
                    anchor = "end" if side == "L" else "start"
                    txt = {1: "supply", 2: "supply", 3: "GND", 4: "GND", 12: "GND", 10: "NC"}.get(pin, "-")
                    if conn == "DATA3":
                        txt = "not mapped"
                    o.append(f'<text x="{tx}" y="{y + 4}" text-anchor="{anchor}" font-size="11" '
                             f'fill="#bfe3cb">{txt}</text>')
    # legend + fixed pins panel
    px = 1180
    o.append(f'<text x="{px}" y="100" font-size="14" font-weight="bold">Legend</text>')
    y = 122
    for k, (name, col) in FUNC.items():
        planned = k in ("adc",)
        fill = "#fff" if planned else col
        d = ' stroke-dasharray="3 2"' if planned else ""
        o.append(f'<circle cx="{px + 8}" cy="{y - 4}" r="8" fill="{fill}" stroke="{col}" stroke-width="2"{d}/>')
        o.append(f'<text x="{px + 24}" y="{y}">{name}</text>')
        y += 24
    o.append(f'<circle cx="{px + 8}" cy="{y - 4}" r="8" fill="#d9d9d9" stroke="#777" stroke-width="2"/>')
    o.append(f'<text x="{px + 24}" y="{y}">supply / GND / NC / not mapped</text>')
    y += 24
    o.append(f'<text x="{px}" y="{y}" fill="#555" font-size="11">Dashed outline = in pins.toml, not constrained '
             f'yet.</text>')
    y += 44
    o.append(f'<text x="{px}" y="{y}" font-size="14" font-weight="bold">Board-fixed pins</text>')
    y += 22
    group = None
    for g, sig, ball, d in FIXED:
        if g != group:
            group = g
            o.append(f'<text x="{px}" y="{y}" font-weight="bold" fill="#333">{g}</text>')
            y += 18
        o.append(f'<text x="{px + 8}" y="{y}" font-size="11">{sig}</text>')
        o.append(f'<text x="{px + 322}" y="{y}" font-size="11" text-anchor="end" fill="#333">{ball}</text>')
        y += 17
    y += 22
    o.append(f'<text x="{px}" y="{y}" font-size="14" font-weight="bold">EMIO GPIO lines (Linux 54 + n)</text>')
    y += 20
    for n, nm in enumerate(["V1 .. V6 = pe4302_v[0..5]", "", "", "", "", "", "adf4351_ce", "adf4351_ld", "lcd_dc",
                            "lcd_res", "led[0..2] = n 10..12", "keys[0..4] = n 13..17"]):
        if nm:
            lab = {0: "n = 0..5", 6: "n = 6", 7: "n = 7", 8: "n = 8", 9: "n = 9", 10: "n = 10..12", 11: "n = 13..17"}[n]
            o.append(f'<text x="{px + 8}" y="{y}" font-size="11">{lab}</text>')
            o.append(f'<text x="{px + 322}" y="{y}" font-size="11" text-anchor="end">{nm}</text>')
            y += 17
    o.append("</svg>")
    return "\n".join(o)


def ball_svg(rows):
    pk = package()
    used = used_balls()
    sig = {}                                    # ball -> (label, colour)
    for r in rows:
        if r["used"]:
            sig[r["ball"]] = (r["name"].replace("adf4351_", "adf_").replace("pe4302_v", "pe"), func_of(r["name"])[1])
    for ball, port in fixed_balls():
        sig[ball] = (port.replace("ENET0_GMII_", "").replace("enet0_mdio_mdio_io", "mdio").replace("enet0_mdio_", "")
                                .replace("enet0_", "").replace("_0", ""), "#8a4fbf")
    for ball, (bank, fn, _) in pk.items():          # PS MIO balls used for the boot card and the console
        m = re.match(r"PS_MIO(\d+)_", fn)
        if m and int(m.group(1)) in (24, 25, 40, 41, 42, 43, 44, 45):
            sig[ball] = (("UART1 " if int(m.group(1)) < 30 else "SD0 ") + m.group(1), "#8c6d00")
    for ball, port in adapter_balls():
        sig[ball] = (port.replace("lcd_", "lcd ").replace("keys", "key").replace("led", "led"), "#00838f")
    planned = {r["ball"]: r["name"].replace("adf4351_", "adf_") for r in rows if r["planned"]}
    letters = sorted({b[0] for b in pk if re.fullmatch(r"[A-Z]\d+", b)})
    cw, ch, x0, y0 = 62, 44, 56, 90
    W, H = x0 + 20 * cw + 320, y0 + len(letters) * ch + 40
    o = [f'<svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 {W} {H}" font-family="Helvetica,Arial,sans-serif">',
         '<title>XC7Z010-CLG400 ball map</title>', f'<rect width="{W}" height="{H}" fill="#fff"/>',
         '<text x="20" y="28" font-size="20" font-weight="bold">XC7Z010-CLG400: balls used by the design</text>',
         '<text x="20" y="48" font-size="12" fill="#555">Top view, ball A1 at the top left. Label = signal, small text = '
         'ball and bank. Grey grid = ball exists (PL bank 34 / 35 light blue, PS banks 500/501 light yellow, '
         'power and config white).</text>']
    for c in range(1, 21):
        o.append(f'<text x="{x0 + (c - 1) * cw + cw / 2}" y="{y0 - 8}" text-anchor="middle" font-size="12" '
                 f'font-weight="bold">{c}</text>')
    for i, L in enumerate(letters):
        o.append(f'<text x="{x0 - 10}" y="{y0 + i * ch + ch / 2 + 4}" text-anchor="end" font-size="12" '
                 f'font-weight="bold">{L}</text>')
        for c in range(1, 21):
            ball = f"{L}{c}"
            x, y = x0 + (c - 1) * cw, y0 + i * ch
            if ball not in pk:
                o.append(f'<rect x="{x + 1}" y="{y + 1}" width="{cw - 2}" height="{ch - 2}" fill="#f4f4f4"/>')
                continue
            bank = pk[ball][0]
            fill = {"34": "#e3f0fb", "35": "#e3f0fb", "500": "#fdf6d8", "501": "#fdf6d8", "502": "#fdf6d8"}.get(bank,
                                                                                                           "#fff")
            stroke, txt, dash = "#bbb", "", ""
            if ball in sig:
                txt, col = sig[ball]
                fill, stroke = col, col
            elif ball in planned:
                txt, stroke, dash = planned[ball], "#6b6b6b", ' stroke-dasharray="3 2"'
            o.append(f'<rect x="{x + 1}" y="{y + 1}" width="{cw - 2}" height="{ch - 2}" rx="3" fill="{fill}" '
                     f'stroke="{stroke}" stroke-width="{2 if ball in sig or ball in planned else 1}"{dash}/>')
            tcol = "#fff" if ball in sig else "#222"
            o.append(f'<text x="{x + cw / 2}" y="{y + 17}" text-anchor="middle" font-size="11" font-weight="bold" '
                     f'fill="{tcol if ball in sig else "#222"}">{txt[:11]}</text>')
            o.append(f'<text x="{x + cw / 2}" y="{y + 33}" text-anchor="middle" font-size="9" '
                     f'fill="{"#fff" if ball in sig else "#666"}">{ball} · {bank}</text>')
    lx, ly = x0 + 20 * cw + 24, y0
    o.append(f'<text x="{lx}" y="{ly}" font-size="14" font-weight="bold">Legend</text>')
    items = [(c, n, "") for n, c in [(v[0], v[1]) for v in FUNC.values() if v[0] not in ("AD9226 (planned)", "spare")]]
    items += [("#8a4fbf", "Ethernet PHY (board)", ""), ("#00838f", "Adapter: display, keys, LEDs", ""),
              ("#8c6d00", "PS MIO: SD0 boot card, UART1 console", ""),
              ("#fff", "planned, not constrained", "d")]
    for k, (col, name, d) in enumerate(items):
        yy = ly + 24 + k * 24
        dash = ' stroke-dasharray="3 2"' if d else ""
        stroke = "#6b6b6b" if d else col
        o.append(f'<rect x="{lx}" y="{yy - 12}" width="20" height="16" rx="3" fill="{col}" stroke="{stroke}" '
                 f'stroke-width="2"/><text x="{lx + 28}" y="{yy}" font-size="12">{name}</text>')
    o.append("</svg>")
    return "\n".join(o)


def adapter_svg(rows):
    pk = package()
    port_of = {b: p for p, b in used_balls().items()}
    plan = {b: n for n, b, _ in ADC_PROPOSAL}
    col_of = lambda port: func_of(port)[1] if not port.startswith(ADAPTER_PREFIX) else "#00838f"
    W, H = 1500, 900
    o = [f'<svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 {W} {H}" font-family="Helvetica,Arial,sans-serif">',
         '<title>HelloFPGA adapter pinout</title>', f'<rect width="{W}" height="{H}" fill="#fff"/>',
         '<text x="20" y="30" font-size="20" font-weight="bold">Pinout with the HelloFPGA adapter (EBAZ4205_ZJB05)</text>',
         '<text x="20" y="50" fill="#555" font-size="12">Schematic of the adapter as in the photo (top view). '
         'Text: signal, then FPGA ball and bank. Italic purple = proposal for the AD9226, not constrained.</text>',
         '<rect x="20" y="70" width="940" height="810" rx="16" fill="#1c1c1c" stroke="#000" stroke-width="3"/>']

    def lab(x, y, name, ball, anchor="start", colour="#fff", italic=False):
        st = ' font-style="italic"' if italic else ""
        o.append(f'<text x="{x}" y="{y}" text-anchor="{anchor}" font-size="12" font-weight="bold" fill="{colour}"{st}>'
                 f'{name}</text>')
        o.append(f'<text x="{x}" y="{y + 12}" text-anchor="{anchor}" font-size="9" fill="#9ad">{ball} · bank '
                 f'{pk[ball][0] if ball in pk else "?"}</text>')

    def dot(cx, cy, colour, txt="", r=13, dash=False):
        d = ' stroke-dasharray="3 2"' if dash else ""
        fill = "#1c1c1c" if dash else colour
        o.append(f'<circle cx="{cx}" cy="{cy}" r="{r}" fill="{fill}" stroke="{colour}" stroke-width="2"{d}/>')
        if txt:
            o.append(f'<text x="{cx}" y="{cy + 4}" text-anchor="middle" font-size="11" font-weight="bold" '
                     f'fill="#fff">{txt}</text>')

    # EBAZ side connectors (left edge)
    for name, y0, y1, note in (("DATA1", 230, 440, "HDMI, 3 LEDs, buzzer, UART header"),
                               ("DATA2", 470, 650, "right connector: control signals"),
                               ("DATA3", 680, 860, "keys, LCD, 4 pins to the right connector")):
        o.append(f'<rect x="26" y="{y0}" width="22" height="{y1 - y0}" rx="3" fill="#444" stroke="#888"/>')
        o.append(f'<text x="56" y="{y0 + 16}" fill="#fff" font-size="13" font-weight="bold">{name}</text>')
        o.append(f'<text x="56" y="{y0 + 32}" fill="#bbb" font-size="10">{note}</text>')
    o.append('<text x="56" y="214" fill="#bbb" font-size="10">EBAZ4205 plugs into these three headers</text>')

    # UART header
    o.append('<rect x="70" y="90" width="150" height="100" rx="6" fill="#2a2a2a" stroke="#888"/>')
    o.append('<text x="80" y="108" fill="#fff" font-size="12" font-weight="bold">UART header</text>')
    o.append('<text x="80" y="122" fill="#bbb" font-size="10">jumpers to the USB-UART (EMIO)</text>')
    lab(80, 146, "H16 = RX", "H16"); lab(80, 176, "H17 = TX", "H17")
    # USB-C and 5V/3V3 header
    o.append('<rect x="300" y="86" width="110" height="34" rx="6" fill="#888"/>'
             '<text x="355" y="108" text-anchor="middle" font-size="12" font-weight="bold">USB-C 5 V</text>')
    o.append('<text x="300" y="140" fill="#bbb" font-size="10">5V / 3V3 / GND pads next to it</text>')

    # HDMI
    o.append('<rect x="470" y="86" width="340" height="188" rx="8" fill="#2a2a2a" stroke="#8a4fbf" stroke-width="2"/>')
    o.append('<text x="482" y="106" fill="#c9a6ee" font-size="13" font-weight="bold">HDMI port (HDMI_PIN): 4 TMDS pairs, '
             'use with the HDMI breakout</text>')
    for i, (nm, pb, nb) in enumerate(HDMI):
        y = 130 + i * 36
        o.append(f'<text x="482" y="{y + 12}" fill="#fff" font-size="12" font-weight="bold">{nm}</text>')
        for k, (ball, sgn) in enumerate(((pb, "+"), (nb, "-"))):
            x = 540 + k * 130
            o.append(f'<text x="{x}" y="{y + 4}" fill="#fff" font-size="12" font-weight="bold">{ball}{sgn}'
                     f'{"" if k == 0 else " (inferred)"}</text>')
            o.append(f'<text x="{x}" y="{y + 18}" fill="#c9a6ee" font-size="11" font-style="italic">'
                     f'{plan.get(ball, "")}</text>')
    o.append('<text x="482" y="268" fill="#999" font-size="9">HDMI +5 V and shield pins: never wire to a signal. Negatives are '
             'inferred from the package pairing.</text>')

    # buzzer, LEDs
    dot(870, 150, "#777", "", 38)
    o.append('<text x="870" y="154" text-anchor="middle" fill="#fff" font-size="12" font-weight="bold">Buzzer</text>')
    lab(840, 205, "D18", "D18", "middle", "#fff")
    for i, (nm, ball, port) in enumerate((("LED1", "H18", "led[0]"), ("LED2", "K17", "led[1]"),
                                          ("LED3", "E19", "led[2]"))):
        y = 262 + i * 34
        dot(900, y, "#00838f", "", 10)
        lab(885, y - 2, f"{nm}  {port}", ball, "end", "#fff")
        o.append(f'<text x="885" y="{y + 24}" text-anchor="end" fill="#c9a6ee" font-size="10" font-style="italic">'
                 f'{plan.get(ball, "")}</text>' if ball in plan else "")

    # LCD
    o.append('<rect x="330" y="400" width="250" height="260" rx="6" fill="#050505" stroke="#555" stroke-width="2"/>')
    o.append('<text x="455" y="535" text-anchor="middle" fill="#666" font-size="16">LCD</text>')
    o.append('<text x="300" y="396" text-anchor="end" fill="#fff" font-size="12" font-weight="bold">LCD_PIN</text>')
    for i, (nm, port) in enumerate((("CS", "lcd_cs"), ("DC", "lcd_dc"), ("SCL", "lcd_scl"), ("SDA", "lcd_sda"),
                                    ("RES", "lcd_res"))):
        ball = next(b for b, p in adapter_balls() if p == port)
        lab(300, 424 + i * 46, f"{nm}  {port}", ball, "end")

    # keys
    for nm, ball, port, x, y in (("KEY1", "T19", "keys[0]", 470, 700), ("KEY2", "P19", "keys[1]", 330, 770),
                                 ("KEY3", "U20", "keys[2]", 470, 770), ("KEY5", "V20", "keys[4]", 610, 770),
                                 ("KEY4", "U19", "keys[3]", 470, 840)):
        o.append(f'<rect x="{x - 22}" y="{y - 16}" width="44" height="32" rx="6" fill="#444" stroke="#00838f" '
                 f'stroke-width="2"/><text x="{x}" y="{y + 4}" text-anchor="middle" fill="#fff" font-size="11" '
                 f'font-weight="bold">{nm}</text>')
        lab(x + 28, y - 2, port, ball)

    # right connector
    cx = (790, 830)
    o.append(f'<rect x="{cx[0] - 22}" y="400" width="{cx[1] - cx[0] + 44}" height="440" rx="5" fill="#000" '
             f'stroke="#aaa"/>')
    o.append('<text x="810" y="388" text-anchor="middle" fill="#fff" font-size="14" font-weight="bold">'
             'Right connector: to the SAdiy PCBs</text>')
    for i, (a, b) in enumerate(RIGHT_CONN):
        y = 428 + i * 44
        for k, ball in enumerate((a, b)):
            x = cx[k]
            if ball in ("GND", "3V3"):
                dot(x, y, "#777", ball[0] if ball == "GND" else "3", 13)
                lab(x - 22 if k == 0 else x + 22, y - 2, ball, "A1", "end" if k == 0 else "start") if False else \
                    o.append(f'<text x="{x - 22 if k == 0 else x + 22}" y="{y + 4}" '
                             f'text-anchor="{"end" if k == 0 else "start"}" fill="#ddd" font-size="12" '
                             f'font-weight="bold">{ball}</text>')
                continue
            port = port_of.get(ball, "")
            free = port == ""
            colour = "#9a9a9a" if free else col_of(port)
            dot(x, y, colour, "", 13, dash=free)
            name = port or "free"
            if ball == "J18":
                name = "spare_d2_6 (free)"
            xl = x - 22 if k == 0 else x + 22
            lab(xl, y - 2, name, ball, "end" if k == 0 else "start", "#fff" if not free else "#ccc")
            if ball in plan and (free or ball == "J18"):
                o.append(f'<text x="{xl}" y="{y + 24}" text-anchor="{"end" if k == 0 else "start"}" fill="#c9a6ee" '
                         f'font-size="10" font-style="italic">AD9226 {plan[ball]}</text>')
    # side panel: legend and proposal
    px = 990
    o.append(f'<text x="{px}" y="90" font-size="16" font-weight="bold">Legend</text>')
    for i, (c, t, d) in enumerate(((FUNC["adf4351"][1], "ADF4351 synthesiser", 0), (FUNC["pe4302"][1], "PE4302", 0),
                                   (FUNC["i2c"][1], "I2C (ADS1115)", 0), ("#00838f", "adapter display, keys, LEDs", 0),
                                   ("#9a9a9a", "free pin", 1))):
        y = 116 + i * 24
        dot(px + 8, y - 4, c, "", 8, dash=bool(d))
        o.append(f'<text x="{px + 24}" y="{y}" font-size="12">{t}</text>')
    o.append(f'<text x="{px}" y="262" font-size="16" font-weight="bold">AD9226 proposal via HDMI</text>')
    o.append(f'<text x="{px}" y="280" font-size="11" fill="#555">12 data + clock fit: 8 HDMI balls + 5 free pins</text>')
    for i, (sg, ball, where) in enumerate(ADC_PROPOSAL):
        y = 306 + i * 22
        o.append(f'<text x="{px}" y="{y}" font-size="12" font-weight="bold" fill="#6a3d9a">{sg}</text>'
                 f'<text x="{px + 90}" y="{y}" font-size="12">{ball}</text>'
                 f'<text x="{px + 135}" y="{y}" font-size="12" fill="#444">{where}</text>')
    o.append(f'<text x="{px}" y="{306 + len(ADC_PROPOSAL) * 22 + 10}" font-size="11" fill="#555">Check first: HDMI pad to '
             f'DATA1 pin continuity, no series parts,</text>')
    o.append(f'<text x="{px}" y="{306 + len(ADC_PROPOSAL) * 22 + 26}" font-size="11" fill="#555">negatives reach the '
             f'HDMI pins, +5 V pin kept away.</text>')
    o.append("</svg>")
    return "\n".join(o)


def main():
    rows = load()
    files = {OUT_MD: md(rows), OUT_SVG: svg(rows), OUT_BALLS: ball_svg(rows), OUT_ADAPTER: adapter_svg(rows)}
    if "--check" in sys.argv:
        bad = [p.name for p, t in files.items() if not p.exists() or p.read_text() != t]
        if bad:
            sys.exit("out of date: " + ", ".join(bad))
        print("pinmap files are current")
        return
    for p, t in files.items():
        p.write_text(t)
        print("wrote", p)


if __name__ == "__main__":
    main()
