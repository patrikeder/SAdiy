#!/usr/bin/env python3
"""Place all parts except J1, J2, J3 on a regular lattice (rows and columns, one orientation per row or class).

Lattice (cape coordinates, origin = top-left corner of the BBB cape outline):
    x = 20.32 + 2.54 * a      (the pad columns of P8 / P9 / J3)
    y =  4.445 + 2.54 * b      (the pad rows of P8, 2.54 mm apart)
Every through-hole pad of the module headers sits on this lattice, so a header can be moved by whole pitches only.

Rules
  * all 1xN headers and jumpers: horizontal, pin 1 on the left (rotation 90); J6 the same
  * series resistors: directly on the pad column of their SBC pin, in five rows (above P8, between P8 and J3,
    below J3, above P9, below P9); the pad with the header net faces the header
  * pull-ups and test points: in the pin columns of the connector they belong to, in one row
  * capacitors and ferrites vertical (rotation 270), SOT-23 and the fuse at rotation 0 / 180

    python3 align_components.py in.kicad_pcb out.kicad_pcb [preview.svg]
"""
import math
import sys

import place_components as pc
from place_components import OX, OY, State, load, pad_abs, box_abs, overlap

PITCH = 2.54


def cape(x, y):
    return OX + x, OY + y


def lat(a, b):
    """lattice point (cape coordinates)"""
    return 20.32 + PITCH * a, 4.445 + PITCH * b


def col(i):
    return 20.32 + PITCH * i


ROW_A, ROW_B, ROW_C, ROW_D, ROW_E = -1.27, 8.255, 23.495, 46.99, 55.88   # series resistor rows (cape y)


def r_rot(p, net, header_below):
    """rotation (90 / 270) of a vertical resistor so that the pad on `net` faces the header."""
    best = None
    for rot in (90, 270):
        ys = {pd[0]: pad_abs(p, 0, 0, rot, pd)[1] for pd in p.pads}
        pad = [pd[0] for pd in p.pads if pd[3] == net][0]
        other = [pd[0] for pd in p.pads if pd[0] != pad][0]
        ok = ys[pad] > ys[other] if header_below else ys[pad] < ys[other]
        if ok:
            best = rot
    return best


def layout(state):
    parts = state.parts
    pos = {}

    def put(ref, x, y, rot):
        pos[ref] = (OX + x, OY + y, rot)

    # ---- series resistors (by nets)
    for r, p in parts.items():
        if p.fixed or p.value != "220" or not p.lib.startswith("Resistor"):
            continue
        side = [n for n in p.nets if n.startswith("BBB_") or n.startswith("RPI_")][0]
        hdr = next(h for h in ("J1", "J2", "J3") if any(pd[3] == side for pd in parts[h].pads))
        pin = int([pd[0] for pd in parts[hdr].pads if pd[3] == side][0])
        i = (pin - 1) // 2
        if hdr == "J2":                                   # P8: even pins outer (above), odd pins inner
            x, y, below = col(i), (ROW_A if pin % 2 == 0 else ROW_B), (pin % 2 == 0)
        elif hdr == "J1":                                 # P9: odd pins outer (below), even pins inner
            x, y, below = col(i), (ROW_E if pin % 2 == 1 else ROW_D), (pin % 2 == 0)
        else:                                             # J3: even pins = upper row, odd pins = lower row
            x = col(3 + i)
            y, below = (ROW_B, True) if pin % 2 == 0 else (ROW_C, False)
        put(r, x, y, r_rot(p, side, below))

    # ---- headers and jumpers, pin 1 on the left, on the lattice (origin = pin 1)
    def hdr(ref, a, b):
        put(ref, *lat(a, b), 90)
    hdr("J4", 28, 1)        # PE4302 control, pins to the right
    hdr("J5", 28, 5)        # PE4302 supply pads
    hdr("J10", 27, 10)      # ADS1115 breakout
    hdr("J8", 27, 14)       # detector OUT
    hdr("J9", 33, 14)       # detector supply
    hdr("J12", 28, 16)      # ADF4351 CE select
    hdr("JP5", 33, 16)      # ADF4351 PDR
    hdr("J6", 28, 19)       # ADF4351 header (2x5), odd row on the P9 outer row line
    hdr("J7", 34, 19)       # ADF4351 5 V
    hdr("JP6", 17, 21)      # BBB ADC enable, below P9
    hdr("JP2", 7, 8)        # RPi 5 V select
    hdr("JP4", 7, 10)       # RPi 3.3 V select
    hdr("JP3", 1, 14)       # BBB 3.3 V select
    hdr("JP1", 5, 14)       # BBB 5 V select
    hdr("J11", -5, 13)      # 5 V input

    # ---- PE4302 group: test points above, pull-ups below the J4 pin columns 2..7
    for k in range(6):
        x = 91.44 + PITCH * (k + 1)
        tp = next(r for r, p in parts.items() if p.lib.startswith("TestPoint") and p.value == "TP_PE_V%d" % (k + 1))
        pu = next(r for r, p in parts.items() if p.value == "2.2k" and ("ATT_V%d" % (k + 1)) in p.nets)
        put(tp, x, 3.175, 0)
        put(pu, x, 11.43, r_rot(parts[pu], "ATT_V%d" % (k + 1), False))
    put("FB3", 100.33, 17.145, 270)
    put("C10", 97.79, 17.145, 270)
    put("TP8", 103.505, 17.145, 0)

    # ---- ADS1115 / detector group
    put("TP23", 101.6, 25.4, 0)                  # ALRT
    put("TP22", 104.14, 25.4, 0)                 # A0
    put("D2", 108.585, 25.4, 0)
    put("R36", 93.98, 34.29, r_rot(parts["R36"], "I2C_SCL", False))
    put("R37", 96.52, 34.29, r_rot(parts["R37"], "I2C_SDA", False))
    put("R35", 104.14, 34.29, r_rot(parts["R35"], "ADS_A0", False))
    put("C2", 106.68, 34.29, 270)
    put("TP4", 109.22, 34.29, 0)                # +5V_DET
    put("TP20", 88.9, 36.195, 0)                 # DET_OUT
    put("TP3", 91.44, 36.195, 0)                 # AGND
    put("FB2", 95.25, 40.005, 270)
    put("C8", 97.79, 40.005, 270)
    put("C9", 100.33, 40.005, 270)

    # ---- ADF4351 group
    for k, v in enumerate(("TP_SYN_LE", "TP_SYN_DAT", "TP_SYN_CLK", "TP_SYN_MUX", "TP_SYN_LD")):
        tp = next(r for r, p in parts.items() if p.value == v)
        put(tp, 93.98 + PITCH * k, 57.15, 0)
    put("FB1", 107.315, 57.15, 270)
    put("C7", 109.855, 57.15, 270)
    put("TP6", 107.95, 48.895, 0)

    # ---- tap network and AGND star below P9
    put("D1", 57.15, 56.515, 0)
    put("R33", 69.85, ROW_E, r_rot(parts["R33"], "BBB_AIN0", False))
    put("R34", 72.39, ROW_E, r_rot(parts["R34"], "BBB_AIN0", False))
    put("C1", 74.93, ROW_E, 270)
    put("TP21", 77.47, ROW_E, 0)
    put("R38", 80.01, ROW_E, 270)
    put("TP2", 82.55, ROW_E, 0)

    # ---- supply entry (left, below the Ethernet cut-out)
    put("F1", 16.51, 37.465, 180)
    for ref, x in (("C3", 12.7), ("C4", 15.24), ("C5", 22.86), ("C6", 25.4)):
        put(ref, x, 44.45, 270)
    put("TP5", 17.78, 44.45, 0)
    put("TP7", 27.94, 44.45, 0)
    put("TP1", 33.02, 44.45, 0)
    return pos


def run(src, dst, svg=None):
    s = open(src).read()
    parts = load(s)
    st = State(parts)
    pos = layout(st)
    missing = [r for r, p in parts.items() if not p.fixed and r not in pos]
    assert not missing, "not placed: %s" % missing
    extra = [r for r in pos if r not in parts]
    assert not extra, "unknown refs: %s" % extra
    for r, v in pos.items():
        st.pos[r] = v
        st.placed.add(r)
    # legality: courtyards (0.7 mm) and the Ethernet cut-out
    bad = []
    items = list(parts)
    boxes = {}
    for r in items:
        x, y, a = st.pos[r]
        if r in ("J1", "J2"):
            q = [pad_abs(parts[r], x, y, a, pd) for pd in parts[r].pads]
            boxes[r] = (min(t[0] for t in q) - 0.85, min(t[1] for t in q) - 0.85, max(t[0] for t in q) + 0.85, max(t[1] for t in q) + 0.85)
        else:
            boxes[r] = box_abs(parts[r], x, y, a)
    for i in range(len(items)):
        for j in range(i + 1, len(items)):
            if items[i] in ("J1", "J2") and items[j] in ("J1", "J2"):
                continue
            tp = parts[items[i]].lib.startswith("TestPoint") and parts[items[j]].lib.startswith("TestPoint")
            if overlap(boxes[items[i]], boxes[items[j]], 0.0 if tp else 0.7):   # test pads keep >= 1 mm of copper gap
                bad.append((items[i], items[j]))
    for r in items:
        b = boxes[r]
        cb = (b[0] - OX, b[1] - OY, b[2] - OX, b[3] - OY)
        if cb[0] < pc.NOTCH[2] + 0.9 and cb[3] > pc.NOTCH[1] - 0.9 and cb[1] < pc.NOTCH[3] + 0.9 and r not in ("J1", "J2"):
            bad.append((r, "Ethernet cut-out"))
    if bad:
        for b in bad:
            print("CONFLICT", b)
        raise SystemExit(1)
    fit = pc.fit_board(st, margin=2.0)
    print("board fitted to the parts: x %.1f..%.1f, y %.1f..%.1f = %.1f x %.1f mm" % (fit["x0"], fit["x1"], fit["y0"], fit["y1"], fit["x1"] - fit["x0"], fit["y1"] - fit["y0"]))
    out = pc.put_edge_cuts(pc.apply(s, st))
    pc.match_end(out, out.index("(kicad_pcb"))
    open(dst, "w").write(out)
    if svg:
        pc.svg_preview(st, svg, [n for n in {n for p in parts.values() for n in p.nets} if pc.net_weight(n) >= 1.0 and n != "AGND"])
    return st


if __name__ == "__main__":
    a = sys.argv[1:]
    run(a[0], a[1], a[2] if len(a) > 2 else None)
