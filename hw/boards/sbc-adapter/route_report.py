#!/usr/bin/env python3
"""Statistics + images from a route_check result (json written by route_check/more.py). Does not touch the PCB."""
import json, sys, math, collections
import route_check as rc
board, jf, prefix = sys.argv[1], sys.argv[2], sys.argv[3]
c = rc.build(board)
d = json.load(open(jf))
paths = {c.nets[n]: v for n, v in {c.names[k]: None for k in c.nets.values()}.items()} if False else None
names = {v: k for k, v in c.nets.items()}
P = {}
if isinstance(next(iter(d["paths"])), str) and not d["paths"].keys().__iter__().__next__().isdigit() and d["paths"].keys().__iter__().__next__() in c.nets:
    P = {c.nets[n]: v for n, v in d["paths"].items()}
else:
    P = {int(k): v for k, v in d["paths"].items()}
per = rc.stats(c, P, {})
tot_len = sum(v["length"] for v in per.values()); tot_via = sum(v["vias"] for v in per.values())
print("nets %d, track %.0f mm, vias %d" % (len(P), tot_len, tot_via))
HW, W, Hh = c.HW, c.W, c.Hh
xy = lambda n: (c.X0 + (n % HW % W) * rc.H, c.Y0 + (n % HW // W) * rc.H, n // HW)
# layer split
lay = [0, 0]
for ps in P.values():
    for p in ps:
        for a, b in zip(p, p[1:]):
            if abs(a - b) != HW:
                lay[a // HW] += rc.H
print("length F.Cu %.0f mm, B.Cu %.0f mm" % tuple(lay))
# channel occupancy: free nodes used per 10x10 mm window
used = collections.Counter(); free = collections.Counter()
for l in (0, 1):
    for r in range(HW):
        n = l * HW + r
        if c.blk[n] != -2:
            x, y, _ = xy(n); free[(int((x - 170) // 10), int((y - 40) // 10), l)] += 1
for ps in P.values():
    for p in ps:
        for n in p:
            x, y, l = xy(n); used[(int((x - 170) // 10), int((y - 40) // 10), l)] += 1
# a track blocks about 3 nodes of width (itself + clearance), so "track share" = used/(free/2)
dens = {k: 100.0 * used[k] * 2 / max(free[k], 1) for k in free}
worst = sorted(dens.items(), key=lambda kv: -kv[1])[:8]
print("busiest 10x10 mm windows (x,y,layer: share of routing capacity):")
for (i, j, l), v in worst:
    print("  x %d..%d y %d..%d %s: %.0f %%" % (i * 10, i * 10 + 10, j * 10, j * 10 + 10, "F" if l == 0 else "B", v))
# crosstalk exposure: analog vs digital
dig = [n for n in c.nets if n.startswith(("SYN_CLK", "SYN_DATA", "SYN_LE", "BBB_SYN_CLK", "BBB_SYN_DATA", "BBB_SYN_LE", "RPI_SYN_CLK", "RPI_SYN_DATA", "RPI_SYN_LE", "I2C_SCL", "I2C_SDA", "BBB_I2C", "RPI_I2C"))]
ana = [n for n in ("DET_OUT", "DET_DIV", "BBB_AIN0", "ADS_A0") if n in c.nets]
digset = collections.defaultdict(set)
for n in dig:
    for p in P.get(c.nets[n], []):
        for q in p:
            x, y, l = xy(q); digset[l].add((round(x / rc.H), round(y / rc.H)))
R = int(round(2.54 / rc.H))
print("analog track within 2.54 mm of a digital track (same layer):")
xt = {}
for a in ana:
    tot = near = 0; mind = 99.0
    for p in P.get(c.nets[a], []):
        for q in p:
            x, y, l = xy(q); tot += 1
            i, j = round(x / rc.H), round(y / rc.H)
            md = 99.0
            for di in range(-R, R + 1):
                for dj in range(-R, R + 1):
                    if (i + di, j + dj) in digset[l]:
                        md = min(md, math.hypot(di, dj) * rc.H)
            if md < 99: near += 1
            mind = min(mind, md)
    xt[a] = (round(per[a]["length"], 1), round(near * rc.H, 1), None if mind == 99 else round(mind, 2))
    print("  %-9s length %5.1f mm, %5.1f mm of it within 2.54 mm of digital, closest %s mm" % (a, xt[a][0], xt[a][1], xt[a][2]))
pour = rc.pour_check(c, P)
print("GND pour:", {k: pour[k] for k in ("pads", "isolated", "areas", "areas_without_stitching")})
wide = rc.widen_check(c, P, ["+5V", "5V_EXT", "BBB_5V", "RPI_5V", "+3V3", "+5V_SYN", "+5V_DET", "+3V3_ATT", "BBB_3V3", "RPI_3V3"])
print("room for 0.5 mm on the supply tracks (% of track):", wide)
json.dump(dict(per=per, tot_len=tot_len, tot_via=tot_via, layer=lay, worst=[(k, v) for k, v in worst], xt=xt, pour=pour, wide=wide), open(prefix + "_stats.json", "w"))
# ------------------------------------------------------------------ pictures
x0, y0, x1, y1 = [170 + 0, 40 - 8, 170 + 118, 40 + 64]
S = 9.0
def X(x): return (x - x0) * S
def Y(y): return (y - y0) * S
out = ['<svg xmlns="http://www.w3.org/2000/svg" width="%d" height="%d" viewBox="0 0 %d %d" font-family="sans-serif">' % ((x1 - x0) * S, (y1 - y0) * S + 28, (x1 - x0) * S, (y1 - y0) * S + 28),
       '<rect width="100%" height="100%" fill="#10151c"/>']
# board outline
poly = "".join("M%.1f %.1f L%.1f %.1f " % (X(a), Y(b), X(cc), Y(dd)) for a, b, cc, dd in c.edges)
out.append('<path d="%s" stroke="#e0c040" stroke-width="2" fill="none"/>' % poly)
col = {0: "#d94f4f", 1: "#4f8fe0"}
for k, ps in P.items():
    nm = names[k]
    wcol = 1.0
    for p in ps:
        for a, b in zip(p, p[1:]):
            xa, ya, la = xy(a); xb, yb, lb = xy(b)
            if abs(a - b) == HW:
                out.append('<circle cx="%.1f" cy="%.1f" r="%.1f" fill="#f2f2f2" stroke="#222"/>' % (X(xa), Y(ya), 0.5 * 0.5 * S))
            else:
                out.append('<line x1="%.1f" y1="%.1f" x2="%.1f" y2="%.1f" stroke="%s" stroke-width="%.1f" stroke-linecap="round" opacity="0.85"/>' % (X(xa), Y(ya), X(xb), Y(yb), col[la], 0.25 * S))
for q in c.pads:
    fill = "#c8c8c8" if q.net != "GND" else "#4a9a5a"
    if q.circle:
        out.append('<circle cx="%.1f" cy="%.1f" r="%.1f" fill="%s" opacity="0.9"/>' % (X(q.x), Y(q.y), q.hx * S, fill))
    else:
        out.append('<rect x="%.1f" y="%.1f" width="%.1f" height="%.1f" fill="%s" opacity="0.9"/>' % (X(q.x - q.hx), Y(q.y - q.hy), 2 * q.hx * S, 2 * q.hy * S, fill))
out.append('<text x="8" y="%d" fill="#ddd" font-size="14">Routability check (generator output, not a KiCad render): red = F.Cu, blue = B.Cu, white dots = vias, green pads = GND (poured, not routed). %d nets, %.0f mm, %d vias.</text>' % ((y1 - y0) * S + 20, len(P), tot_len, tot_via))
out.append("</svg>")
open(prefix + "_routed.svg", "w").write("\n".join(out))
# heat map
cell = 4.0
hm = {}
for ps in P.values():
    for p in ps:
        for n in p:
            x, y, l = xy(n); hm[(int((x - 170) // cell), int((y - 40) // cell))] = hm.get((int((x - 170) // cell), int((y - 40) // cell)), 0) + 1
freec = collections.Counter()
for r in range(HW):
    if c.blk[r] != -2 or c.blk[HW + r] != -2:
        x, y, _ = xy(r); freec[(int((x - 170) // cell), int((y - 40) // cell))] += 2 if (c.blk[r] != -2 and c.blk[HW + r] != -2) else 1
o2 = ['<svg xmlns="http://www.w3.org/2000/svg" width="%d" height="%d" viewBox="0 0 %d %d" font-family="sans-serif">' % ((x1 - x0) * S, (y1 - y0) * S + 28, (x1 - x0) * S, (y1 - y0) * S + 28), '<rect width="100%" height="100%" fill="#10151c"/>']
for (i, j), n in hm.items():
    share = min(1.0, n * 2.0 / max(freec[(i, j)], 1))
    r_, g_, b_ = int(40 + 215 * share), int(120 + 60 * (1 - abs(share - 0.5) * 2)) if share < 1 else 60, int(160 * (1 - share))
    o2.append('<rect x="%.1f" y="%.1f" width="%.1f" height="%.1f" fill="rgb(%d,%d,%d)" opacity="0.9"/><text x="%.1f" y="%.1f" font-size="9" fill="#fff" text-anchor="middle">%d</text>' % (X(170 + i * cell), Y(40 + j * cell), cell * S, cell * S, r_, g_, b_, X(170 + i * cell + cell / 2), Y(40 + j * cell + cell / 2) + 3, round(share * 100)))
o2.append('<path d="%s" stroke="#e0c040" stroke-width="2" fill="none"/>' % poly)
for q in c.pads:
    o2.append('<circle cx="%.1f" cy="%.1f" r="2" fill="#fff"/>' % (X(q.x), Y(q.y)))
o2.append('<text x="8" y="%d" fill="#ddd" font-size="14">Routing load per 4 x 4 mm cell, both layers, in percent of the usable routing capacity (generator output, not a KiCad render)</text>' % ((y1 - y0) * S + 20))
o2.append("</svg>")
open(prefix + "_heat.svg", "w").write("\n".join(o2))
