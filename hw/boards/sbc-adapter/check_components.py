#!/usr/bin/env python3
"""Check the component placement of sa_sbc_adapter.kicad_pcb (no KiCad needed).

Reads the board file, recomputes every pad position from the footprint position and rotation, and reports
  * courtyard overlaps and parts outside the BBB cape outline (hard checks)
  * SBC-side stub lengths (series resistor to its header pad)
  * length of the shared SPI nets and the distance between SPI pads and the analog nodes
  * decoupling distances (cap / ferrite to the header they serve) and the ADC tap distances
Exit code 1 if a hard check fails.
"""
import itertools
import math
import re
import sys
from collections import defaultdict

import place_components as pc


def mst_len(pts):
    if len(pts) < 2:
        return 0.0
    used = [0]
    tot = 0.0
    while len(used) < len(pts):
        best = min(((math.dist(pts[i], pts[j]), j) for i in used for j in range(len(pts)) if j not in used))
        tot += best[0]
        used.append(best[1])
    return tot


def main(path):
    s = open(path).read()
    parts = pc.load(s)
    st = pc.State(parts)
    # board outline from Edge.Cuts
    xs, ys = [], []
    for m in re.finditer(r'\(gr_line\s+\(start ([-\d.]+) ([-\d.]+)\)\s+\(end ([-\d.]+) ([-\d.]+)\)(?:(?!\n\t\)).)*?\(layer "Edge\.Cuts"\)', s, re.S):
        a, b, c, d = map(float, m.groups())
        xs += [a, c]
        ys += [b, d]
    if xs:
        pc.BOARD.update(x0=min(xs) - pc.OX, x1=max(xs) - pc.OX, y0=min(ys) - pc.OY, y1=max(ys) - pc.OY)
        print("board outline from Edge.Cuts: x %.1f..%.1f, y %.1f..%.1f (cape coordinates)" % (pc.BOARD["x0"], pc.BOARD["x1"], pc.BOARD["y0"], pc.BOARD["y1"]))
    else:
        print("no Edge.Cuts outline in the file")
    ok = True
    # --- hard checks
    boxes = {}
    for r, p in parts.items():
        x, y, a = st.pos[r]
        boxes[r] = pc.box_abs(p, x, y, a)
    bad = []
    for (r1, b1), (r2, b2) in itertools.combinations(boxes.items(), 2):
        if r1 in ("J1", "J2") and r2 in ("J1", "J2"):
            continue
        b1o, b2o = b1, b2
        # J1 / J2 courtyards are on the bottom layer: use their top-side pad area instead
        for rr, bb in ((r1, b1), (r2, b2)):
            pass
        def top_box(r, b):
            if r in ("J1", "J2"):
                p = parts[r]
                x, y, a = st.pos[r]
                xs = [pc.pad_abs(p, x, y, a, q)[0] for q in p.pads]
                ys = [pc.pad_abs(p, x, y, a, q)[1] for q in p.pads]
                return (min(xs) - 0.85, min(ys) - 0.85, max(xs) + 0.85, max(ys) + 0.85)
            return b
        tp2 = parts[r1].lib.startswith("TestPoint") and parts[r2].lib.startswith("TestPoint")
        if pc.overlap(top_box(r1, b1), top_box(r2, b2), 0.0 if tp2 else 0.7):   # test pads: >= 1 mm copper gap
            bad.append((r1, r2))
    print("courtyard overlaps (clearance 0.7 mm):", bad if bad else "none")
    ok &= not bad
    out = [r for r, b in boxes.items() if r not in ("J1", "J2") and not pc.outline_ok(b, 0.9)]
    print("parts outside the board outline / Ethernet cut-out:", out if out else "none")
    ok &= not out
    # --- alignment
    import collections
    print("\nalignment")
    off = []
    for r, p in parts.items():
        if p.lib.startswith("Connector_PinHeader") or p.lib.startswith("Connector_IDC"):
            x, y, a = st.pos[r]
            for pd in p.pads:
                px, py = pc.pad_abs(p, x, y, a, pd)
                ax, by = (px - pc.OX - 20.32) / 2.54, (py - pc.OY - 4.445) / 2.54
                if abs(ax - round(ax)) > 0.01 or abs(by - round(by)) > 0.01:
                    off.append(r)
                    break
    print("   headers with a pad off the 2.54 mm lattice of P8/P9:", off if off else "none (all through-hole pads of the connectors are on the lattice)")
    rots = collections.defaultdict(set)
    for r, p in parts.items():
        if p.fixed:
            continue
        kind = ("1xN header" if p.lib.startswith("Connector_PinHeader_2.54mm:PinHeader_1x") else "2x5 header" if "2x05" in p.lib else
                "resistor" if p.lib.startswith("Resistor") else "capacitor" if p.lib.startswith("Capacitor") else
                "ferrite" if p.lib.startswith("Inductor") else "SOT-23" if "SOT" in p.lib else "test point" if p.lib.startswith("TestPoint") else "fuse")
        rots[kind].add(int(st.pos[r][2]))
    for k, v in sorted(rots.items()):
        print("   %-10s rotations used: %s" % (k, sorted(v)))
    rows = collections.defaultdict(list)
    for r, p in parts.items():
        if p.value == "220":
            rows[round(st.pos[r][1] - pc.OY, 2)].append(r)
    print("   series resistor rows (cape y): " + ", ".join("%s: %d parts" % (y, len(v)) for y, v in sorted(rows.items())))
    colerr = []
    for r, p in parts.items():
        if p.value == "220":
            side = [n for n in p.nets if n.startswith("BBB_") or n.startswith("RPI_")][0]
            hdr = next(h for h in ("J1", "J2", "J3") if any(pd[3] == side for pd in parts[h].pads))
            hp = [pc.pad_abs(parts[hdr], *st.pos[hdr], pd) for pd in parts[hdr].pads if pd[3] == side][0]
            if abs(hp[0] - st.pos[r][0]) > 0.01:
                colerr.append(r)
    print("   series resistors not on the pad column of their SBC pin:", colerr if colerr else "none")
    # --- board area and density
    poly = pc.board_polygon()
    area = abs(sum(poly[i][0] * poly[(i + 1) % len(poly)][1] - poly[(i + 1) % len(poly)][0] * poly[i][1] for i in range(len(poly)))) / 2
    parts_area = sum((b[2] - b[0]) * (b[3] - b[1]) for r, b in boxes.items() if r not in ("J1", "J2", "J3"))
    fixed_area = sum((boxes[r][2] - boxes[r][0]) * (boxes[r][3] - boxes[r][1]) for r in ("J2", "J3")) + (boxes["J1"][2] - boxes["J1"][0]) * 5.7
    cape = pc.CAPE_W * pc.CAPE_H - 20.32 * (33.655 - 15.875)
    print("board %.0f x %.1f mm, area %.0f mm2 (cape %.0f mm2, %+.0f %%); courtyards of the 93 parts cover %.0f %% of the free board area"
          % (pc.BOARD["x1"] - pc.BOARD["x0"], pc.BOARD["y1"] - pc.BOARD["y0"], area, cape, 100 * (area - cape) / cape,
             100 * parts_area / (area - fixed_area)))
    # --- stubs
    print("\nSBC-side series resistors (220 ohm): pad to header pad")
    stubs = []
    for r, p in parts.items():
        if p.value != "220":
            continue
        x, y, a = st.pos[r]
        for pad in p.pads:
            n = pad[3]
            if n and (n.startswith("BBB_") or n.startswith("RPI_")):
                hdr = "J1" if any(q[3] == n for q in parts["J1"].pads) else ("J2" if any(q[3] == n for q in parts["J2"].pads) else "J3")
                hp = [pc.pad_abs(parts[hdr], *st.pos[hdr], q) for q in parts[hdr].pads if q[3] == n][0]
                stubs.append((math.dist(pc.pad_abs(p, x, y, a, pad), hp), r, n, hdr))
    stubs.sort(reverse=True)
    for d, r, n, h in stubs[:5]:
        print("   longest: %-4s %-14s %-3s %5.1f mm" % (r, n, h, d))
    print("   mean %.1f mm, max %.1f mm over %d resistors" % (sum(d for d, *_ in stubs) / len(stubs), stubs[0][0], len(stubs)))
    # --- SPI vs analog
    def pts_of(nets):
        return [q for n in nets for q in st.pads_of_net(n)]
    spi_nets = ["SYN_CLK", "SYN_DATA", "SYN_LE", "BBB_SYN_CLK", "BBB_SYN_DATA", "BBB_SYN_LE", "RPI_SYN_CLK", "RPI_SYN_DATA", "RPI_SYN_LE"]
    ana_nets = ["DET_OUT", "DET_DIV", "BBB_AIN0", "ADS_A0", "AGND"]
    spi, ana = pts_of(spi_nets), pts_of(ana_nets)
    dmin = min(math.dist(a, b) for a in spi for b in ana)
    d_mid = min(math.dist(a, b) for a in pts_of(["SYN_CLK", "SYN_DATA", "SYN_LE"]) for b in pts_of(["DET_OUT", "DET_DIV", "BBB_AIN0", "ADS_A0"]))
    print("\nSPI nets (CLK, DATA, LE, both sides) to analog nodes (DET_OUT, DET_DIV, AIN0, A0, AGND): closest pads %.1f mm" % dmin)
    print("shared SPI nets to the high-impedance analog nodes (DET_OUT, DET_DIV, AIN0, A0): closest pads %.1f mm" % d_mid)
    for n in ("SYN_CLK", "SYN_DATA", "SYN_LE"):
        print("   %-9s shared net: %5.1f mm (shortest tree over its pads)" % (n, mst_len(st.pads_of_net(n))))
    # --- analog
    j1 = parts["J1"]
    tap = [pc.pad_abs(j1, *st.pos["J1"], q) for q in j1.pads if q[3] == "BBB_AIN0"][0]
    print("\nAIN0 tap: P9.39 pad to the parts on BBB_AIN0 (mm):",
          {r: round(min(math.dist(tap, pc.pad_abs(parts[r], *st.pos[r], q)) for q in parts[r].pads if q[3] == "BBB_AIN0"), 1)
           for r in ("R33", "R34", "C1", "D1", "TP21") if r in parts})
    r33 = parts["R33"]
    jp6 = parts["JP6"]
    d_jp6 = min(math.dist(pc.pad_abs(jp6, *st.pos["JP6"], q), pc.pad_abs(r33, *st.pos["R33"], w)) for q in jp6.pads if q[3] == "DET_DIV" for w in r33.pads if w[3] == "DET_DIV")
    print("JP6 pad to R33 on the DET_DIV node: %.1f mm" % d_jp6)
    # --- decoupling
    print("\ndecoupling / filtering distances (pad to header pad, same net):")
    for cap, hdr, net in (("C7", "J7", "+5V_SYN"), ("FB1", "J7", "+5V_SYN"), ("C8", "J9", "+5V_DET"), ("C9", "J9", "+5V_DET"),
                          ("FB2", "J9", "+5V_DET"), ("C10", "J5", "+3V3_ATT"), ("FB3", "J5", "+3V3_ATT"),
                          ("C3", "F1", "+5V"), ("C5", "JP3", "+3V3")):
        p = parts[cap]
        hp = [pc.pad_abs(parts[hdr], *st.pos[hdr], q) for q in parts[hdr].pads if q[3] == net or hdr == "F1" or hdr == "JP3"]
        a = [pc.pad_abs(p, *st.pos[cap], q) for q in p.pads if q[3] == net]
        if a and hp:
            print("   %-4s %-3s %-9s %5.1f mm" % (cap, hdr, net, min(math.dist(x, y) for x in a for y in hp)))
    print("\nPLACEMENT CHECK OK" if ok else "\nPLACEMENT CHECK FAILED")
    return 0 if ok else 1


if __name__ == "__main__":
    sys.exit(main(sys.argv[1]))
