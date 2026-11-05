#!/usr/bin/env python3
"""Place all other components of sa_sbc_adapter.kicad_pcb (everything except J1, J2, J3).

Strategy (function first, then signal integrity):
  * J1 / J2 / J3 are the fixed anchors (BBB P9 / P8 on the bottom side, RPi IDC on top).
  * Every SBC-side 220 ohm series resistor sits at ITS OWN header pad (source termination: the resistor is
    at the driver, the long run to the module carries the damped edge). BBB side next to P8/P9, RPi side
    next to J3 (above the shroud for the upper row pins, below it for the lower row pins).
  * The ADF4351 SPI group sits in the middle between the two SBC sides, away from the detector / ADC
    corner, so SPI edges do not run past the analog nodes.
  * The BBB ADC divider (R_T, R_B, C, clamp, JP6) sits at P9.39 / P9.34 / P9.32, the detector connector
    next to it, so the high-impedance AIN0 node stays a few mm long.
  * The ADS1115 header sits next to the detector connector (short A0 net), decoupling caps and ferrites
    are placed at the module supply headers, the supply entry (J11, F1, jumpers, bulk caps) is in the free
    strip left of P9 pin 1, test points sit at the pin they probe.
  * Everything stays inside the BBB cape outline: Ethernet keep-out, top-left corner cut, rounded corners.

    python3 place_components.py in.kicad_pcb out.kicad_pcb [preview.svg]
"""
import math
import random
import re
import sys
from collections import defaultdict

from place_connectors import match_end, fmt

OX, OY = 170.0, 40.0
CAPE_W, CAPE_H = 86.36, 54.61
BOARD_MARGIN_SMD = 1.0
BOARD_MARGIN_THT = 1.5
CLEAR = 0.80
GRID = 0.5

# ---------------------------------------------------------------- geometry


def rot(x, y, a):
    r = math.radians(a)
    return x * math.cos(r) + y * math.sin(r), -x * math.sin(r) + y * math.cos(r)


def norm_net(n):
    return None if n is None else n.lstrip("/")


class Part:
    pass


def load(s):
    parts = {}
    for m in re.finditer(r"\n\t\(footprint \"([^\"]+)\"", s):
        st = s.index("(", m.start())
        en = match_end(s, st)
        b = s[st:en]
        p = Part()
        p.lib = m.group(1)
        p.ref = re.search(r'\(property "Reference" "([^"]+)"', b).group(1)
        p.value = re.search(r'\(property "Value" "([^"]*)"', b).group(1)
        p.layer = re.search(r'\(layer "([^"]+)"\)', b).group(1)
        at = re.search(r"\n\t\t\(at ([-\d.]+) ([-\d.]+)(?: ([-\d.]+))?\)", b)
        p.x, p.y, p.a = float(at.group(1)), float(at.group(2)), float(at.group(3) or 0)
        xs, ys = [], []
        for mm in re.finditer(r'\((?:fp_rect|fp_line)\s+\(start ([-\d.]+) ([-\d.]+)\)\s+\(end ([-\d.]+) ([-\d.]+)\)(?:(?!\n\t\t\)).)*?\(layer "[FB]\.CrtYd"\)', b, re.S):
            x1, y1, x2, y2 = map(float, mm.groups())
            xs += [x1, x2]
            ys += [y1, y2]
        p.pads = []
        for pm in re.finditer(r'\(pad "([^"]*)" (\w+) (\w+)\n\t\t\t\(at ([-\d.]+) ([-\d.]+)(?: ([-\d.]+))?\)\n\t\t\t\(size ([-\d.]+) ([-\d.]+)\)', b):
            pend = match_end(b, b.index("(", pm.start()))
            net = re.search(r'\(net "([^"]*)"\)', b[pm.start():pend])
            p.pads.append((pm.group(1), float(pm.group(4)), float(pm.group(5)), norm_net(net.group(1)) if net else None,
                           float(pm.group(7)), float(pm.group(8))))
        if xs:
            p.court = (min(xs), min(ys), max(xs), max(ys))
        else:  # test point: pad + margin
            q = p.pads[0]
            p.court = (q[1] - q[4] / 2 - 0.25, q[2] - q[5] / 2 - 0.25, q[1] + q[4] / 2 + 0.25, q[2] + q[5] / 2 + 0.25)
        p.nets = {n for (_, _, _, n, _, _) in p.pads if n and not n.startswith("unconnected")}
        p.start, p.end = st, en
        p.fixed = p.ref in ("J1", "J2", "J3")
        parts[p.ref] = p
    return parts


def pad_abs(p, x, y, a, pad):
    rx, ry = rot(pad[1], pad[2], a)
    return x + rx, y + ry


def box_abs(p, x, y, a):
    x1, y1, x2, y2 = p.court
    pts = [rot(cx, cy, a) for cx, cy in ((x1, y1), (x2, y1), (x2, y2), (x1, y2))]
    return (x + min(q[0] for q in pts), y + min(q[1] for q in pts), x + max(q[0] for q in pts), y + max(q[1] for q in pts))


# ---------------------------------------------------------------- board outline (cape coordinates)
# The board is larger than the BBB cape: it extends to the right and 6 mm beyond P8 and P9. Only the cut-out over the
# Ethernet connector (13 mm tall RJ45, taller than the gap under the board) is kept.
BOARD = dict(x0=0.0, y0=-6.0, x1=116.0, y1=60.6)
NOTCH = (0.0, 15.875, 20.32, 33.655)


def outline_ok(b, m):
    """b = bbox in PCB coordinates, m = margin. True if it lies on the board."""
    x1, y1, x2, y2 = b[0] - OX, b[1] - OY, b[2] - OX, b[3] - OY
    if x1 < BOARD["x0"] + m or y1 < BOARD["y0"] + m or x2 > BOARD["x1"] - m or y2 > BOARD["y1"] - m:
        return False
    if x1 < NOTCH[2] + m and y2 > NOTCH[1] - m and y1 < NOTCH[3] + m:
        return False
    return True


def board_polygon():
    x0, y0, x1, y1 = BOARD["x0"], BOARD["y0"], BOARD["x1"], BOARD["y1"]
    n = (x0, NOTCH[1], NOTCH[2], NOTCH[3])
    return [(x0, y0), (x1, y0), (x1, y1), (x0, y1), (x0, n[3]), (n[2], n[3]), (n[2], n[1]), (x0, n[1])]


# ---------------------------------------------------------------- net weights

def net_weight(n):
    if n in ("GND",):
        return 0.0
    if n in ("SYN_CLK", "SYN_DATA", "SYN_LE"):
        return 4.0
    if n in ("BBB_SYN_CLK", "BBB_SYN_DATA", "BBB_SYN_LE", "RPI_SYN_CLK", "RPI_SYN_DATA", "RPI_SYN_LE"):
        return 3.0
    if n in ("DET_OUT", "DET_DIV", "BBB_AIN0", "ADS_A0"):
        return 6.0
    if n == "AGND":
        return 1.5
    if n.startswith("I2C") or n.startswith("BBB_I2C") or n.startswith("RPI_I2C"):
        return 1.5
    if n in ("+5V", "+3V3", "5V_EXT"):
        return 0.4
    if n in ("+5V_SYN", "+5V_DET", "+3V3_ATT"):
        return 1.5
    if n in ("BBB_5V", "BBB_3V3", "RPI_5V", "RPI_3V3"):
        return 0.4
    return 1.0


# ---------------------------------------------------------------- state

class State:
    def __init__(self, parts):
        self.parts = parts
        self.pos = {r: (p.x, p.y, p.a) for r, p in parts.items()}
        self.placed = set(r for r, p in parts.items() if p.fixed)

    def pads_of_net(self, net, exclude=None, only_placed=False):
        out = []
        for r, p in self.parts.items():
            if r == exclude:
                continue
            if only_placed and r not in self.placed:
                continue
            x, y, a = self.pos[r]
            for pad in p.pads:
                if pad[3] == net:
                    out.append(pad_abs(p, x, y, a, pad))
        return out

    def pads_of_net_fixed(self, net, exclude=None):
        out = []
        for r in self.placed:
            p = self.parts[r]
            if r == exclude or not p.fixed:
                continue
            x, y, a = self.pos[r]
            out += [pad_abs(p, x, y, a, pad) for pad in p.pads if pad[3] == net]
        return out

    def obstacles(self, exclude=None):
        out = []
        for r in self.placed:
            if r == exclude:
                continue
            p = self.parts[r]
            x, y, a = self.pos[r]
            if r in ("J1", "J2"):  # through-hole pads show on the top copper too
                xs = [pad_abs(p, x, y, a, q)[0] for q in p.pads]
                ys = [pad_abs(p, x, y, a, q)[1] for q in p.pads]
                out.append((min(xs) - 0.85, min(ys) - 0.85, max(xs) + 0.85, max(ys) + 0.85, r))
            else:
                out.append(box_abs(p, x, y, a) + (r,))
        return out


def overlap(a, b, c):
    return not (a[2] + c <= b[0] or b[2] + c <= a[0] or a[3] + c <= b[1] or b[3] + c <= a[1])


def hpwl(state, nets=None):
    tot = 0.0
    allnets = defaultdict(list)
    for r, p in state.parts.items():
        x, y, a = state.pos[r]
        for pad in p.pads:
            if pad[3] and not pad[3].startswith("unconnected"):
                allnets[pad[3]].append(pad_abs(p, x, y, a, pad))
    detail = {}
    for n, pts in allnets.items():
        if nets is not None and n not in nets:
            continue
        w = net_weight(n)
        if len(pts) < 2 or w == 0:
            continue
        h = (max(q[0] for q in pts) - min(q[0] for q in pts)) + (max(q[1] for q in pts) - min(q[1] for q in pts))
        detail[n] = h
        tot += w * h
    return tot, detail


def part_cost(state, ref, x, y, a, hints, anchor, lam):
    p = state.parts[ref]
    cost = 0.0
    for pad in p.pads:
        n = pad[3]
        if not n or n.startswith("unconnected"):
            continue
        w = net_weight(n)
        if w == 0:
            continue
        px, py = pad_abs(p, x, y, a, pad)
        mult = 4.0 if (getattr(p, "sbc_r", False) and (n.startswith("BBB_") or n.startswith("RPI_"))) else 1.0
        others = state.pads_of_net(n, exclude=ref, only_placed=True)
        if others:
            cx = sum(q[0] for q in others) / len(others)
            cy = sum(q[1] for q in others) / len(others)
            # distance to the nearest placed pad of the net (short stubs) blended with the centroid
            dmin = min(math.hypot(px - q[0], py - q[1]) for q in others)
            cost += w * mult * (0.7 * dmin + 0.3 * math.hypot(px - cx, py - cy))
            fx = state.pads_of_net_fixed(n, exclude=ref)
            if fx:   # pads of the SBC headers are the anchors: pull harder towards them
                cost += w * mult * 0.8 * min(math.hypot(px - q[0], py - q[1]) for q in fx)
        elif hints and n in hints:
            hx, hy = hints[n]
            cost += w * math.hypot(px - hx, py - hy)
    if anchor:
        bx = box_abs(p, x, y, a)
        cx, cy = (bx[0] + bx[2]) / 2, (bx[1] + bx[3]) / 2
        cost += lam * math.hypot(cx - anchor[0], cy - anchor[1])
    return cost


def legal(state, ref, x, y, a):
    p = state.parts[ref]
    b = box_abs(p, x, y, a)
    tht = p.lib.startswith("Connector") or p.lib.startswith("sadiy")
    if not outline_ok(b, BOARD_MARGIN_THT if tht else BOARD_MARGIN_SMD):
        return False
    for ob in state.obstacles(exclude=ref):
        if overlap(b, ob, CLEAR):
            return False
    return True


def place_part(state, ref, anchor, rots, hints=None, radius=14.0, lam=0.25, min_x=None):
    """anchor = desired CENTER of the courtyard box (PCB coordinates)."""
    p = state.parts[ref]
    best = None
    ax, ay = anchor
    n_steps = int(radius / GRID)
    for a in rots:
        # offset from footprint origin to box center for this rotation
        b0 = box_abs(p, 0, 0, a)
        ocx, ocy = (b0[0] + b0[2]) / 2, (b0[1] + b0[3]) / 2
        for ix in range(-n_steps, n_steps + 1):
            for iy in range(-n_steps, n_steps + 1):
                cx = round((ax + ix * GRID) / GRID) * GRID
                cy = round((ay + iy * GRID) / GRID) * GRID
                if math.hypot(cx - ax, cy - ay) > radius:
                    continue
                x, y = cx - ocx, cy - ocy
                # snap the footprint origin to the 0.05 mm grid
                x, y = round(x / 0.05) * 0.05, round(y / 0.05) * 0.05
                if min_x is not None and box_abs(p, x, y, a)[0] < OX + min_x:
                    continue                           # keep this part right of x = min_x (cape coordinates)
                if not legal(state, ref, x, y, a):
                    continue
                c = part_cost(state, ref, x, y, a, hints, anchor, lam)
                if best is None or c < best[0]:
                    best = (c, x, y, a)
    if best is None:
        if radius < 40:
            print("  widening search for", ref, "near", (round(ax - OX, 1), round(ay - OY, 1)))
            return place_part(state, ref, anchor, rots, hints, radius * 1.6, lam, min_x)
        raise RuntimeError("no legal position for %s near %s" % (ref, anchor))
    state.pos[ref] = (best[1], best[2], best[3])
    state.placed.add(ref)
    return best


def auto_anchor(state, ref):
    """Centroid of the placed pads on the most specific nets of the part (fewest pads first)."""
    p = state.parts[ref]
    pts = []
    for n in p.nets:
        if net_weight(n) == 0:
            continue
        others = state.pads_of_net(n, exclude=ref, only_placed=True)
        if not others:
            continue
        w = net_weight(n) / len(others)
        pts += [(q[0], q[1], w) for q in others]
    if not pts:
        return None
    tw = sum(q[2] for q in pts)
    return sum(q[0] * q[2] for q in pts) / tw, sum(q[1] * q[2] for q in pts) / tw


def C(x, y):
    """cape coordinates -> PCB coordinates"""
    return (OX + x, OY + y)


# ---------------------------------------------------------------- the floorplan

ROWS = ["SYN_CLK", "SYN_DATA", "SYN_LE", "SYN_LD", "SYN_CE", "ATT_V1", "ATT_V2", "ATT_V3", "ATT_V4", "ATT_V5", "ATT_V6",
        "I2C_SDA", "I2C_SCL"]
MID_HINT = {"ATT": C(95, 6), "SYN": C(95, 51.5), "I2C": C(100, 27)}


def floorplan(state, log):
    parts = state.parts
    byval = lambda pred: [r for r, p in parts.items() if not p.fixed and pred(p)]

    # ---- 1. series resistors at the SBC headers
    sbc_r = {}
    for r, p in parts.items():
        if p.fixed or not p.lib.startswith("Resistor") or p.value != "220":
            continue
        nets = sorted(p.nets)
        sig = [n for n in nets if n in ROWS]
        side = [n for n in nets if n.startswith("BBB_") or n.startswith("RPI_")]
        sbc_r[r] = (sig[0], side[0])
        p.sbc_r = True
    order = sorted(sbc_r, key=lambda r: ROWS.index(sbc_r[r][0]))
    for r in order:
        sig, side = sbc_r[r]
        grp = sig.split("_")[0]
        # header pad of the SBC-side net
        if side.startswith("BBB_"):
            hdr = state.parts["J1"] if state.pads_of_net(side, only_placed=True) and any(pd[3] == side for pd in parts["J1"].pads) else parts["J2"]
        else:
            hdr = parts["J3"]
        hx, hy = [pad_abs(hdr, *state.pos[hdr.ref], pd) for pd in hdr.pads if pd[3] == side][0]
        hy_c = hy - OY
        if hdr.ref == "J2":      # P8: outer row (even pins) outside the header, inner row in the channel to J3
            anchor = (hx, OY + (-2.3 if hy_c < 3.0 else 7.4))
        elif hdr.ref == "J1":    # P9: outer row (odd pins) outside the header, inner row just above it
            anchor = (hx, OY + (57.2 if hy_c > 51.5 else 46.3))
        else:                    # J3: upper row above the shroud, lower row below it
            anchor = (hx, OY + (7.2 if hy_c < 14.0 else 21.3))
        hints = {sig: MID_HINT[grp]}
        place_part(state, r, anchor, (0, 90, 180, 270), hints, radius=9, lam=0.5)

    # ---- 2. module connectors
    place_part(state, "J4", C(101, 3.5), (90,), radius=6)
    place_part(state, "J6", C(97, 51.0), (90,), radius=4, lam=2.5, min_x=CAPE_W + 2.0)   # the ADF4351 group stays outside the BBB area
    place_part(state, "J10", C(101, 27.0), (90, 270), radius=4)
    place_part(state, "J8", C(94, 38), (0, 90, 180, 270), radius=7)
    place_part(state, "J9", C(107, 38), (0, 90, 180, 270), radius=7)
    for ref in ("FB2", "C8", "C9"):                 # detector supply filter right at J9, before the neighbours crowd it
        place_part(state, ref, auto_anchor(state, ref), (0, 90, 180, 270), None, radius=8, lam=0.2)
    place_part(state, "J12", auto_anchor(state, "J12"), (0, 90, 180, 270), radius=9, lam=0.6, min_x=CAPE_W + 1.5)
    place_part(state, "JP5", auto_anchor(state, "JP5"), (0, 90, 180, 270), radius=9, lam=0.6, min_x=CAPE_W + 1.5)
    place_part(state, "J7", C(107.5, 53.5), (0, 90, 180, 270), radius=9, min_x=CAPE_W + 1.5)
    place_part(state, "J5", C(106, 19), (0, 90, 180, 270), radius=7)
    # supply entry in the free strip left of P9 pin 1 and the lower-left corner
    place_part(state, "J11", C(11, 38), (0, 90, 180, 270), radius=6)
    place_part(state, "F1", C(11, 46), (0, 90), radius=6)
    place_part(state, "JP3", C(23.5, 45.5), (0, 90), radius=6)
    place_part(state, "JP1", C(28, 45.5), (0, 90), radius=6)
    place_part(state, "JP2", C(33, 25.5), (0, 90, 180, 270), radius=8)
    place_part(state, "JP4", C(40, 25.5), (0, 90, 180, 270), radius=8)

    # ---- 3. detector front end and ADS path
    for ref in ("R33", "R34", "D1", "C1"):          # tap network at P9.39 / P9.34 / P9.32
        parts[ref].sbc_r = True                      # weight the nets that go to the BBB header pads
        place_part(state, ref, auto_anchor(state, ref), (0, 90, 180, 270), None, radius=7, lam=0.3)
    # BBB ADC enable jumper right at the divider: the long run is the low-impedance DET_OUT, the DET_DIV node stays short
    r33, jp6 = parts["R33"], parts["JP6"]
    qx, qy = [pad_abs(r33, *state.pos["R33"], pd) for pd in r33.pads if pd[3] == "DET_DIV"][0]
    place_part(state, "JP6", (qx + 5.0, qy), (90, 270), None, radius=5, lam=2.0)
    for ref in ("R35", "C2"):                       # ADS1115 input network at J10 pin 7 / J8
        place_part(state, ref, auto_anchor(state, ref), (0, 90, 180, 270), None, radius=7, lam=0.3)
    j10 = parts["J10"]                              # clamp D2 above J10, at its A0 pin
    ax, ay = [pad_abs(j10, *state.pos["J10"], pd) for pd in j10.pads if pd[3] == "ADS_A0"][0]
    place_part(state, "D2", (ax, ay - 5.0), (0, 90, 180, 270), None, radius=6, lam=1.0)
    j10 = parts["J10"]
    for ref in ("R36", "R37"):                      # DNP I2C pull-ups at the ADS1115 header (SCL = pin 3, SDA = pin 4)
        net = next(n for n in parts[ref].nets if n.startswith("I2C"))
        px, py = [pad_abs(j10, *state.pos["J10"], pd) for pd in j10.pads if pd[3] == net][0]
        place_part(state, ref, (px, py + 4.5), (90, 270), None, radius=6, lam=0.8)
    place_part(state, "R38", auto_anchor(state, "R38"), (0, 90, 180, 270), None, radius=8, lam=0.3)

    # ---- 4. PE4302 pull-ups: one per control line, just below the matching J4 pad (in pin order)
    pu = sorted([r for r, p in parts.items() if p.value == "2.2k"], key=lambda r: min(n for n in parts[r].nets if n.startswith("ATT")))
    j4 = parts["J4"]
    for r in pu:
        net = next(n for n in parts[r].nets if n.startswith("ATT"))
        px, py = [pad_abs(j4, *state.pos["J4"], pd) for pd in j4.pads if pd[3] == net][0]
        place_part(state, r, (px, py + 4.0), (90, 270), None, radius=4, lam=0.8)

    # ---- 5. ferrites and capacitors at their headers (anchor derived from the nets)
    for ref in ("FB1", "FB2", "FB3", "C7", "C8", "C9", "C10"):
        if ref in state.placed:
            continue
        place_part(state, ref, auto_anchor(state, ref), (0, 90, 180, 270), None, radius=9, lam=0.2)
    for ref, anc in (("C3", C(14, 43)), ("C4", C(17.5, 43)), ("C5", C(14, 50)), ("C6", C(17.5, 50))):
        place_part(state, ref, anc, (0, 90, 180, 270), None, radius=10)

    # ---- 6. test points at the pin they probe (above the pin row of J4 / J6, otherwise nearest free spot)
    for r in sorted([r for r, p in parts.items() if p.lib.startswith("TestPoint")], key=lambda r: parts[r].value):
        n = next(iter(parts[r].nets))
        if n == "GND":
            anc = C(18, 36) if parts[r].value.endswith("1") else C(60, 49)
        else:
            conn = [pad_abs(parts[rr], *state.pos[rr], pd) for rr in ("J4", "J5", "J6", "J7", "J8", "J9", "J10", "J11", "J12", "JP1", "JP3", "JP5", "JP6")
                    for pd in parts[rr].pads if pd[3] == n]
            base = conn or state.pads_of_net(n, exclude=r, only_placed=True)
            anc = (sum(q[0] for q in base) / len(base), sum(q[1] for q in base) / len(base))
            if n.startswith("ATT"):
                anc = (anc[0], anc[1] - 3.3)
            elif n.startswith("SYN"):
                anc = (anc[0], anc[1] + 3.6)
        if n.startswith("SYN"):                       # keep the SPI test points right under their J6 pins
            place_part(state, r, anc, (0,), None, radius=5, lam=1.2)
        else:
            if n == "+3V3":
                anc = C(25.5, 38.5)                   # 3.3 V test point at the supply entry
            place_part(state, r, anc, (0,), None, radius=10, lam=0.6)


# ---------------------------------------------------------------- refinement

def refine(state, passes=3, seed=1):
    rnd = random.Random(seed)
    movable = [r for r, p in state.parts.items()
               if not p.fixed and not p.lib.startswith("Connector") and not p.lib.startswith("TestPoint") and p.value != "2.2k"]
    steps = [(0.5, 0), (-0.5, 0), (0, 0.5), (0, -0.5), (1, 0), (-1, 0), (0, 1), (0, -1), (1.5, 0), (-1.5, 0), (0, 1.5), (0, -1.5)]
    for _ in range(passes):
        rnd.shuffle(movable)
        for r in movable:
            p = state.parts[r]
            x, y, a = state.pos[r]
            base = part_cost(state, r, x, y, a, None, None, 0)
            best = (base, x, y, a)
            for da in (0, 90, 180, 270):
                if p.lib.startswith("TestPoint") and da:
                    continue
                for dx, dy in [(0, 0)] + steps:
                    nx, ny = round((x + dx) / 0.05) * 0.05, round((y + dy) / 0.05) * 0.05
                    na = da
                    if (nx, ny, na) == (x, y, a):
                        continue
                    if not legal(state, r, nx, ny, na):
                        continue
                    c = part_cost(state, r, nx, ny, na, None, None, 0)
                    if c < best[0] - 1e-9:
                        best = (c, nx, ny, na)
            state.pos[r] = best[1:]


# ---------------------------------------------------------------- output

def fit_board(state, margin=2.5):
    """Board outline = bounding box of all parts (J1/J2 by their pads) plus a margin, on a 0.5 mm grid."""
    xs, ys = [], []
    for r, p in state.parts.items():
        x, y, a = state.pos[r]
        if r in ("J1", "J2"):
            pts = [pad_abs(p, x, y, a, q) for q in p.pads]
            xs += [q[0] - 0.85 for q in pts] + [q[0] + 0.85 for q in pts]
            ys += [q[1] - 0.85 for q in pts] + [q[1] + 0.85 for q in pts]
        else:
            b = box_abs(p, x, y, a)
            xs += [b[0], b[2]]
            ys += [b[1], b[3]]
    g = lambda v, up: (math.ceil(v * 2) if up else math.floor(v * 2)) / 2
    BOARD["x0"] = g(min(xs) - OX - margin, False)
    BOARD["y0"] = g(min(ys) - OY - margin, False)
    BOARD["x1"] = g(max(xs) - OX + margin, True)
    BOARD["y1"] = g(max(ys) - OY + margin, True)
    return dict(BOARD)


def edge_cuts():
    import uuid as _u
    ns = _u.UUID("5d1d0a52-3c6e-4f0e-8d3a-6c1d5a0b7e13")
    poly = board_polygon()
    items, tags = "", []
    for i in range(len(poly)):
        a, b = poly[i], poly[(i + 1) % len(poly)]
        u = str(_u.uuid5(ns, "edge-%d" % i))
        tags.append(u)
        items += ('\t(gr_line\n\t\t(start %s %s)\n\t\t(end %s %s)\n\t\t(stroke\n\t\t\t(width 0.05)\n\t\t\t(type solid)\n\t\t)\n\t\t(layer "Edge.Cuts")\n\t\t(uuid "%s")\n\t)\n'
                  % (fmt(OX + a[0]), fmt(OY + a[1]), fmt(OX + b[0]), fmt(OY + b[1]), u))
    return items, tags


def put_edge_cuts(s):
    items, tags = edge_cuts()
    pos = 0
    while True:                       # remove an earlier version of this outline
        m = re.search(r"\n\t\(gr_line\b", s[pos:])
        if not m:
            break
        st = pos + m.start()
        en = match_end(s, s.index("(", st + 2))
        if any(t in s[st:en] for t in tags) or 'Edge.Cuts' in s[st:en]:
            s = s[:st] + s[en:]
            pos = st
        else:
            pos = en
    k = s.rindex("\n\t(embedded_fonts")
    return s[:k + 1] + items + s[k + 1:]


def apply(s, state):
    out = s
    # replace from the back so offsets stay valid
    for r, p in sorted(state.parts.items(), key=lambda kv: -kv[1].start):
        if r in ("J1", "J2"):
            continue
        x, y, a = state.pos[r]
        b = s[p.start:p.end]
        at = "(at %s %s%s)" % (fmt(x), fmt(y), (" " + fmt(a)) if a else "")
        b = re.sub(r"\n\t\t\(at [-\d. ]+\)", "\n\t\t" + at, b, count=1)
        # keep the reference / value text upright: stored angle is relative to the footprint
        ang = ((-a + 180) % 360) - 180
        for name in ("Reference", "Value"):
            m = re.search(r'(\(property "%s" "[^"]*"\s*\(at [-\d.]+ [-\d.]+ )[-\d.]+(\))' % name, b)
            if m:
                b = b[:m.start()] + m.group(1) + fmt(ang) + m.group(2) + b[m.end():]
        out = out[:p.start] + b + out[p.end:]
    return out


def svg_preview(state, path, flynets=None):
    sc = 9.0
    W, H = BOARD["x1"] - BOARD["x0"] + 6, BOARD["y1"] - BOARD["y0"] + 8
    o = ['<svg xmlns="http://www.w3.org/2000/svg" width="%d" height="%d" font-family="monospace">' % (W * sc, H * sc),
         '<rect width="100%" height="100%" fill="#fff"/>']
    X = lambda x: (x - OX - BOARD["x0"] + 3) * sc
    Y = lambda y: (y - OY - BOARD["y0"] + 4) * sc
    o.append('<polygon points="%s" fill="#f6faf0" stroke="#272" stroke-width="2.5"/>' % " ".join("%s,%s" % (X(OX + a), Y(OY + b)) for a, b in board_polygon()))
    o.append('<rect x="%s" y="%s" width="%s" height="%s" fill="none" stroke="#999" stroke-dasharray="6 4"/>' % (X(OX), Y(OY), CAPE_W * sc, CAPE_H * sc))
    o.append('<text x="%s" y="%s" font-size="10" fill="#888">BBB cape outline (reference)</text>' % (X(OX + 22), Y(OY + 31.5)))
    o.append('<text x="%s" y="%s" font-size="10" fill="#a55">Ethernet cut-out</text>' % (X(OX + 1), Y(OY + 24.5)))
    # flylines (MST per net)
    def mst(pts):
        n = len(pts)
        if n < 2:
            return []
        used = [0]
        edges = []
        while len(used) < n:
            best = None
            for i in used:
                for j in range(n):
                    if j in used:
                        continue
                    d = math.hypot(pts[i][0] - pts[j][0], pts[i][1] - pts[j][1])
                    if best is None or d < best[0]:
                        best = (d, i, j)
            edges.append((best[1], best[2]))
            used.append(best[2])
        return edges
    cols = {"SYN": "#d22", "DET": "#06c", "BBB_AIN0": "#06c", "ADS": "#06c", "ATT": "#2a2", "I2C": "#a0a"}
    for n in (flynets or []):
        pts = state.pads_of_net(n)
        c = next((v for k, v in cols.items() if n.startswith(k) or n.startswith("BBB_" + k) or n.startswith("RPI_" + k)), "#999")
        for i, j in mst(pts):
            o.append('<line x1="%s" y1="%s" x2="%s" y2="%s" stroke="%s" stroke-width="1" opacity="0.7"/>' % (X(pts[i][0]), Y(pts[i][1]), X(pts[j][0]), Y(pts[j][1]), c))
    for r, p in state.parts.items():
        x, y, a = state.pos[r]
        b = box_abs(p, x, y, a)
        o.append('<rect x="%s" y="%s" width="%s" height="%s" fill="%s" fill-opacity="0.35" stroke="#a60" stroke-width="0.8"/>' % (
            X(b[0]), Y(b[1]), (b[2] - b[0]) * sc, (b[3] - b[1]) * sc, "#fc8" if p.fixed else "#fff"))
        for pad in p.pads:
            px, py = pad_abs(p, x, y, a, pad)
            rr = max(pad[4], pad[5]) / 2 * sc
            o.append('<circle cx="%s" cy="%s" r="%s" fill="#c33" fill-opacity="0.45"/>' % (X(px), Y(py), min(rr, 9)))
        if not p.fixed:
            o.append('<text x="%s" y="%s" font-size="7" text-anchor="middle" fill="#036">%s</text>' % (X((b[0] + b[2]) / 2), Y((b[1] + b[3]) / 2) + 2, r))
        else:
            o.append('<text x="%s" y="%s" font-size="12" fill="#a40" font-weight="bold">%s</text>' % (X(b[0]) + 3, Y(b[1]) + 12, r))
    o.append("</svg>")
    open(path, "w").write("\n".join(o))


def main(src, dst, svg=None, seed=1):
    s = open(src).read()
    parts = load(s)
    state = State(parts)
    before_pos = dict(state.pos)
    before, bdet = hpwl(state)
    # J3 stays where place_connectors.py put it; all others are unplaced
    floorplan(state, print)
    refine(state, passes=3, seed=seed)
    after, adet = hpwl(state)
    print("weighted HPWL before %.0f after %.0f (%.0f%%)" % (before, after, 100 * (after - before) / before))
    crit = ["SYN_CLK", "SYN_DATA", "SYN_LE", "SYN_LD", "DET_OUT", "DET_DIV", "BBB_AIN0", "ADS_A0",
            "BBB_SYN_CLK", "BBB_SYN_DATA", "BBB_SYN_LE", "RPI_SYN_CLK", "RPI_SYN_DATA", "RPI_SYN_LE"]
    for n in crit:
        print("  %-14s %6.1f -> %6.1f mm (half-perimeter)" % (n, bdet.get(n, 0), adet.get(n, 0)))
    fit = fit_board(state)
    print("board fitted to the parts: x %.1f..%.1f, y %.1f..%.1f (cape coordinates) = %.1f x %.1f mm"
          % (fit["x0"], fit["x1"], fit["y0"], fit["y1"], fit["x1"] - fit["x0"], fit["y1"] - fit["y0"]))
    out = put_edge_cuts(apply(s, state))
    match_end(out, out.index("(kicad_pcb"))
    open(dst, "w").write(out)
    if svg:
        fly = [n for n in adet if net_weight(n) >= 1.0 and n not in ("AGND",)]
        svg_preview(state, svg, fly)
    return state, before, after


if __name__ == "__main__":
    a = sys.argv[1:]
    main(a[0], a[1], a[2] if len(a) > 2 else None)
