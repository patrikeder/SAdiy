#!/usr/bin/env python3
"""Routability check for sa_sbc_adapter.kicad_pcb (pure Python, no KiCad, nothing to install).

1. Every connection is tested ALONE on the board (obstacles = pads and board edge only), in parallel over all CPU cores.
   A connection that fails here cannot be routed at all.
2. All nets are routed TOGETHER with negotiated congestion (PathFinder), several variants in parallel.
   Completion, conflicts, vias, lengths and congestion hot spots show whether the board is routable.
3. GND is treated as a pour on both layers: every GND pad must reach one connected copper area.
4. The wide-track nets (+5 V rails) are checked for room to widen.

Model: 2 copper layers, grid 0.254 mm aligned with the 2.54 mm pad lattice of P8/P9 (the gap between two header pads
is exactly one routing node), 4-direction moves, track 0.25 mm, clearance 0.20 mm, via 0.50 / 0.25 mm,
copper to board edge 0.30 mm. The model is slightly conservative (Manhattan routing, a via blocks a 3 x 3 node area),
so "routable here" means routable on the board; "not routable here" needs a look at the failing spot.

    python3 route_check.py board.kicad_pcb [out_prefix]
"""
import heapq
import json
import math
import multiprocessing as mp
import random
import re
import sys
import time
from collections import defaultdict

import place_components as pc
from place_components import OX, OY, match_end

H = 0.254                 # grid pitch
TRACK, CLEAR, VIA_PAD, EDGE = 0.25, 0.20, 0.50, 0.30
KEEP = CLEAR + TRACK / 2  # track centre to foreign copper
VKEEP = CLEAR + VIA_PAD / 2
VIA_COST = 8.0
NOROUTE = ("GND",)       # poured


# ------------------------------------------------------------------ board and pads
class Pad:
    pass


def load_board(path):
    s = open(path).read()
    parts = pc.load(s)
    pads = []
    for ref, p in parts.items():
        b = s[p.start:p.end]
        for m in re.finditer(r'\(pad "([^"]*)" (\w+) (\w+)\n\t\t\t\(at ([-\d.]+) ([-\d.]+)(?: ([-\d.]+))?\)\n\t\t\t\(size ([-\d.]+) ([-\d.]+)\)', b):
            end = match_end(b, b.index("(", m.start()))
            net = re.search(r'\(net "([^"]*)"\)', b[m.start():end])
            q = Pad()
            q.ref, q.num, q.type, q.shape = ref, m.group(1), m.group(2), m.group(3)
            lx, ly = float(m.group(4)), float(m.group(5))
            q.x, q.y = pc.pad_abs(p, p.x, p.y, p.a, (q.num, lx, ly))
            w, h = float(m.group(7)), float(m.group(8))
            rot = (float(m.group(6)) if m.group(6) else p.a) % 180
            if abs(rot - 90) < 1:
                w, h = h, w
            q.hx, q.hy = w / 2, h / 2
            q.net = pc.norm_net(net.group(1)) if net else None
            q.tht = q.type == "thru_hole"
            q.circle = q.shape == "circle"
            pads.append(q)
    edges = []
    for m in re.finditer(r'\(gr_line\s+\(start ([-\d.]+) ([-\d.]+)\)\s+\(end ([-\d.]+) ([-\d.]+)\)(?:(?!\n\t\)).)*?\(layer "Edge\.Cuts"\)', s, re.S):
        edges.append(tuple(map(float, m.groups())))
    return parts, pads, edges


class Ctx:
    pass


def build(path):
    parts, pads, edges = load_board(path)
    c = Ctx()
    c.parts, c.pads, c.edges = parts, pads, edges
    xs = [e[0] for e in edges] + [e[2] for e in edges]
    ys = [e[1] for e in edges] + [e[3] for e in edges]
    ax, ay = OX + 20.32, OY + 4.445
    c.X0 = ax - H * math.ceil((ax - min(xs)) / H)
    c.Y0 = ay - H * math.ceil((ay - min(ys)) / H)
    c.W = int((max(xs) - c.X0) / H) + 1
    c.Hh = int((max(ys) - c.Y0) / H) + 1
    c.HW = c.W * c.Hh
    c.N = 2 * c.HW
    N = c.N
    blk = [-1] * N
    vbad = [False] * c.HW             # a via may not be here (near any pad or the edge)
    # ---- board outline: inside the polygon and EDGE + half track from the edge
    def seg_dist(px, py, e):
        x1, y1, x2, y2 = e
        dx, dy = x2 - x1, y2 - y1
        t = max(0.0, min(1.0, ((px - x1) * dx + (py - y1) * dy) / (dx * dx + dy * dy)))
        return math.hypot(px - x1 - t * dx, py - y1 - t * dy)

    def inside(px, py):
        n = 0
        for (x1, y1, x2, y2) in edges:
            if (y1 > py) != (y2 > py) and px < x1 + (py - y1) * (x2 - x1) / (y2 - y1):
                n += 1
        return n % 2 == 1
    for j in range(c.Hh):
        y = c.Y0 + j * H
        for i in range(c.W):
            x = c.X0 + i * H
            r = j * c.W + i
            if not inside(x, y) or min(seg_dist(x, y, e) for e in edges) < EDGE + TRACK / 2:
                blk[r] = -2
                blk[c.HW + r] = -2
            elif min(seg_dist(x, y, e) for e in edges) < EDGE + VIA_PAD / 2:
                vbad[r] = True
    # ---- nets
    names = sorted({q.net for q in c.pads if q.net and not q.net.startswith("unconnected") and q.net not in NOROUTE
                    and sum(1 for z in c.pads if z.net == q.net) >= 2})
    c.nets = {n: k for k, n in enumerate(names)}
    c.names = names

    def window(q, m):
        i0 = int((q.x - q.hx - m - c.X0) / H) - 1
        i1 = int((q.x + q.hx + m - c.X0) / H) + 2
        j0 = int((q.y - q.hy - m - c.Y0) / H) - 1
        j1 = int((q.y + q.hy + m - c.Y0) / H) + 2
        return max(i0, 0), min(i1, c.W - 1), max(j0, 0), min(j1, c.Hh - 1)

    def dist(q, x, y):
        if q.circle:
            return max(math.hypot(x - q.x, y - q.y) - q.hx, 0.0)
        return math.hypot(max(abs(x - q.x) - q.hx, 0.0), max(abs(y - q.y) - q.hy, 0.0))
    layers_of = lambda q: (0, 1) if q.tht else (0,)
    c.term = []
    for q in c.pads:
        k = c.nets.get(q.net, -2) if q.net else -2
        if q.net in NOROUTE:
            k = -3
        elif q.net and q.net.startswith("unconnected"):
            k = -2
        i0, i1, j0, j1 = window(q, VKEEP)
        for j in range(j0, j1 + 1):
            for i in range(i0, i1 + 1):
                x, y = c.X0 + i * H, c.Y0 + j * H
                d = dist(q, x, y)
                r = j * c.W + i
                if d < VKEEP:
                    vbad[r] = vbad[r] or any(True for _ in layers_of(q))
                if d < KEEP:
                    for l in layers_of(q):
                        n = l * c.HW + r
                        if blk[n] == -1:
                            blk[n] = k
                        elif blk[n] != k:
                            blk[n] = -2
    # inside nodes belong to the pad's net (terminals)
    for q in c.pads:
        q.term = []
        k = c.nets.get(q.net, -2) if q.net and q.net not in NOROUTE and not q.net.startswith("unconnected") else -2
        i0, i1, j0, j1 = window(q, 0.5)
        cand = []
        for j in range(j0, j1 + 1):
            for i in range(i0, i1 + 1):
                x, y = c.X0 + i * H, c.Y0 + j * H
                d = dist(q, x, y)
                cand.append((d, i, j))
        ins = [t for t in cand if t[0] <= 1e-9]
        use = ins if ins else sorted(cand)[:2]
        for d, i, j in use:
            for l in layers_of(q):
                n = l * c.HW + j * c.W + i
                if k >= 0:
                    blk[n] = k
                elif q.net in NOROUTE and blk[n] == -2:
                    blk[n] = -3
                q.term.append(n)
        q.k = k
    c.blk, c.vbad = blk, vbad
    c.net_pads = defaultdict(list)
    for q in c.pads:
        if q.k is not None and q.k >= 0:
            c.net_pads[q.k].append(q)
    return c


# ------------------------------------------------------------------ routing
def neighbours(n, W, Hh, HW):
    r = n % HW
    l = n - r
    j, i = divmod(r, W)
    out = []
    if i > 0:
        out.append(n - 1)
    if i < W - 1:
        out.append(n + 1)
    if j > 0:
        out.append(n - W)
    if j < Hh - 1:
        out.append(n + W)
    return out


def around8(n, W, Hh, HW):
    r = n % HW
    l = n - r
    j, i = divmod(r, W)
    out = []
    for dj in (-1, 0, 1):
        jj = j + dj
        if jj < 0 or jj >= Hh:
            continue
        for di in (-1, 0, 1):
            ii = i + di
            if (di or dj) and 0 <= ii < W:
                out.append(l + jj * W + ii)
    return out


class Router:
    def __init__(self, c):
        self.c = c
        self.occ = [0] * c.N
        self.adj = [0] * c.N
        self.hist = [0.0] * c.N
        self.g = [0.0] * c.N
        self.gs = [0] * c.N
        self.cl = [0] * c.N
        self.par = [0] * c.N
        self.stamp = 0
        self.a8 = {}

    def a8n(self, n):
        a = self.a8.get(n)
        if a is None:
            a = around8(n, self.c.W, self.c.Hh, self.c.HW)
            self.a8[n] = a
        return a

    def add(self, claim, sign):
        occ, adj = self.occ, self.adj
        for n in claim:
            occ[n] += sign
            for m in self.a8n(n):
                adj[m] += sign

    def astar(self, k, sources, targets, tcent, pf, use_occ=True):
        c = self.c
        blk, occ, adj, hist = c.blk, self.occ, self.adj, self.hist
        W, Hh, HW = c.W, c.Hh, c.HW
        vbad = c.vbad
        self.stamp += 1
        st = self.stamp
        g, gs, cl, par = self.g, self.gs, self.cl, self.par
        heap = []
        push, pop = heapq.heappush, heapq.heappop

        def hfun(r):
            j, i = divmod(r, W)
            return min(abs(i - ci) + abs(j - cj) for ci, cj in tcent)
        for s in sources:
            g[s] = 0.0
            gs[s] = st
            par[s] = -1
            push(heap, (hfun(s % HW), s))
        while heap:
            f, n = pop(heap)
            if cl[n] == st:
                continue
            cl[n] = st
            if n in targets:
                path = []
                while n != -1:
                    path.append(n)
                    n = par[n]
                return path[::-1]
            gn = g[n]
            r = n % HW
            l = n - r
            j, i = divmod(r, W)
            for m in ((n - 1) if i > 0 else -1, (n + 1) if i < W - 1 else -1, (n - W) if j > 0 else -1, (n + W) if j < Hh - 1 else -1):
                if m < 0 or cl[m] == st:
                    continue
                b = blk[m]
                if b < -1 or (b >= 0 and b != k):
                    continue
                cost = 1.0 + hist[m]
                if use_occ:
                    cost += pf * (occ[m] * 3.0 + (1.5 if adj[m] else 0.0))
                ng = gn + cost
                if gs[m] != st or ng < g[m]:
                    g[m] = ng
                    gs[m] = st
                    par[m] = n
                    rr = m % HW
                    push(heap, (ng + hfun(rr), m))
            # via (only from a free node, to a free node on the other layer)
            if not vbad[r] and blk[n] == -1:
                m = n + HW if l == 0 else n - HW
                if cl[m] != st and blk[m] == -1:
                    cost = VIA_COST + hist[m]
                    if use_occ:
                        cost += pf * (occ[m] * 3.0 + (1.5 if adj[m] else 0.0))
                    ng = gn + cost
                    if gs[m] != st or ng < g[m]:
                        g[m] = ng
                        gs[m] = st
                        par[m] = n
                        push(heap, (ng + hfun(r), m))
        return None

    def route_net(self, k, pf, use_occ=True):
        """Route all pads of net k. Returns (paths, claim, failed_pads)."""
        c = self.c
        pads = c.net_pads[k]
        W, Hh, HW = c.W, c.Hh, c.HW
        tree = set(pads[0].term)
        done = {0}
        paths, claim = [], set()
        failed = []
        # start with the pad nearest to the centroid to keep the tree compact
        while len(done) < len(pads):
            rest = [(idx, q) for idx, q in enumerate(pads) if idx not in done]
            targets = set()
            tcent = []
            for idx, q in rest:
                targets.update(q.term)
                tcent.append((int(round((q.x - c.X0) / H)), int(round((q.y - c.Y0) / H))))
            path = self.astar(k, list(tree), targets, tcent, pf, use_occ)
            if path is None:
                # give up on the nearest remaining pad
                failed.append(rest[0][0])
                done.add(rest[0][0])
                continue
            end = path[-1]
            hit = next(idx for idx, q in rest if end in q.term)
            for idx, q in rest:
                if end in q.term:
                    done.add(idx)
                    tree.update(q.term)
            tree.update(path)
            paths.append(path)
            own_pad_nodes = set()
            for q in pads:
                own_pad_nodes.update(q.term)
            for a, b in zip(path, path[1:]):
                if abs(a - b) == HW:           # via: claim 3 x 3 on both layers
                    rr = a % HW
                    for l in (0, HW):
                        for m in [l + rr] + around8(l + rr, W, Hh, HW):
                            claim.add(m)
            for n in path:
                if n not in own_pad_nodes:
                    claim.add(n)
        return paths, claim, failed


# ------------------------------------------------------------------ parallel parts
_CTX = None
_ROUTER = None


def _init(path):
    global _CTX, _ROUTER
    if _CTX is None:
        _CTX = build(path)
    _ROUTER = Router(_CTX)


def _edge_job(args):
    k, ia, ib = args
    c, R = _CTX, _ROUTER
    pa, pb = c.net_pads[k][ia], c.net_pads[k][ib]
    tc = [(int(round((pb.x - c.X0) / H)), int(round((pb.y - c.Y0) / H)))]
    path = R.astar(k, list(pa.term), set(pb.term), tc, 0.0, use_occ=False)
    return (k, ia, ib, None if path is None else len(path))


def mst_edges(c, k):
    pads = c.net_pads[k]
    used = [0]
    edges = []
    while len(used) < len(pads):
        best = None
        for i in used:
            for j in range(len(pads)):
                if j in used:
                    continue
                d = math.hypot(pads[i].x - pads[j].x, pads[i].y - pads[j].y)
                if best is None or d < best[0]:
                    best = (d, i, j)
        edges.append((k, best[1], best[2]))
        used.append(best[2])
    return edges


def _variant(args):
    seed, order_mode, iters = args
    c, R = _CTX, _ROUTER
    rnd = random.Random(seed)
    nets = list(c.net_pads)
    def size(k):
        ps = c.net_pads[k]
        xs = [p.x for p in ps]
        ys = [p.y for p in ps]
        return (max(xs) - min(xs)) + (max(ys) - min(ys))
    if order_mode == "short":
        nets.sort(key=size)
    elif order_mode == "long":
        nets.sort(key=size, reverse=True)
    else:
        rnd.shuffle(nets)
    claims, paths, failed = {}, {}, {}
    pf, hf = 0.35, 0.35
    log = []
    best = None
    for it in range(iters):
        t0 = time.time()
        if it > 0:
            order = sorted(nets, key=lambda k: (not conflicted.get(k, False), rnd.random()))
        else:
            order = nets
        for k in order:
            if k in claims:
                R.add(claims[k], -1)
            p, cl, f = R.route_net(k, pf)
            claims[k], paths[k], failed[k] = cl, p, f
            R.add(cl, +1)
        # conflicts
        conflicted = {}
        nconf = 0
        hot = set()
        for k, cl in claims.items():
            for n in cl:
                bad = R.occ[n] > 1
                if not bad:
                    for m in R.a8n(n):
                        if R.occ[m] > 0 and m not in cl:
                            bad = True
                            break
                if bad:
                    conflicted[k] = True
                    nconf += 1
                    hot.add(n)
        nfail = sum(len(v) for v in failed.values())
        vias = sum(1 for k in paths for p in paths[k] for a, b in zip(p, p[1:]) if abs(a - b) == c.HW)
        log.append((it, nconf, nfail, vias, round(time.time() - t0, 1)))
        score = (nfail, nconf)
        if best is None or score < best[0]:
            best = (score, {k: [list(p) for p in v] for k, v in paths.items()}, dict(failed), set(hot))
        if nconf == 0 and nfail == 0:
            break
        for n in hot:
            R.hist[n] += hf
        pf *= 1.55
    return dict(seed=seed, mode=order_mode, log=log, score=best[0], paths=best[1], failed=best[2], hot=sorted(best[3]))


# ------------------------------------------------------------------ report
def stats(c, paths, failed):
    HW = c.HW
    per = {}
    for k, ps in paths.items():
        ln = 0.0
        vias = 0
        for p in ps:
            for a, b in zip(p, p[1:]):
                if abs(a - b) == HW:
                    vias += 1
                else:
                    ln += H
        per[c.names[k]] = dict(length=round(ln, 1), vias=vias, failed=len(failed.get(k, [])), pads=len(c.net_pads[k]))
    return per


def pour_check(c, paths):
    """Is every GND pad on one connected copper area (pour on both layers)?"""
    R = Router(c)
    for k, ps in paths.items():
        claim = set()
        for p in ps:
            claim.update(p)
            for a, b in zip(p, p[1:]):
                if abs(a - b) == c.HW:
                    r = a % c.HW
                    for l in (0, c.HW):
                        claim.update([l + r] + around8(l + r, c.W, c.Hh, c.HW))
        R.add(claim, +1)
    gnd = [q for q in c.pads if q.net == "GND"]
    # pourable: not blocked for GND, no track occupancy, not adjacent to a track
    ok = [False] * c.N
    gnd_inside = set()
    for q in gnd:
        for n in q.term:
            gnd_inside.add(n)
    for n in range(c.N):
        b = c.blk[n]
        if (b == -1 or b == -3 or n in gnd_inside) and R.occ[n] == 0 and R.adj[n] == 0:
            ok[n] = True
    # extra clearance for the pour (0.3 mm to tracks = about 1 more node): require the 4-neighbours too
    comp = [-1] * c.N
    ncomp = 0
    sizes = []
    for n in range(c.N):
        if ok[n] and comp[n] < 0:
            stack = [n]
            comp[n] = ncomp
            cnt = 0
            while stack:
                a = stack.pop()
                cnt += 1
                for m in neighbours(a, c.W, c.Hh, c.HW):
                    if ok[m] and comp[m] < 0:
                        comp[m] = ncomp
                        stack.append(m)
            sizes.append(cnt)
            ncomp += 1
    # union components through THT GND pads (both layers) and via the pad terminals
    parent = list(range(ncomp))
    def f(x):
        while parent[x] != x:
            parent[x] = parent[parent[x]]
            x = parent[x]
        return x
    def union_all(stitch):
        parent[:] = list(range(ncomp))
        pad_comp = []
        for q in gnd:
            cs = list({comp[n] for n in q.term if comp[n] >= 0})
            pad_comp.append(cs)
            for a in cs[1:]:
                parent[f(a)] = f(cs[0])
        if stitch:
            for r in range(c.HW):
                if not c.vbad[r] and comp[r] >= 0 and comp[c.HW + r] >= 0:
                    parent[f(comp[r])] = f(comp[c.HW + r])
        roots = defaultdict(list)
        isolated = []
        for q, cs in zip(gnd, pad_comp):
            if not cs:
                isolated.append("%s.%s" % (q.ref, q.num))
            else:
                roots[f(cs[0])].append("%s.%s" % (q.ref, q.num))
        return roots, isolated
    roots, isolated = union_all(False)
    big0 = sorted(roots.values(), key=lambda v: -len(v))
    areas_plain = [len(v) for v in big0]
    roots, isolated = union_all(True)
    big = sorted(roots.items(), key=lambda kv: -len(kv[1]))
    return dict(pads=len(gnd), isolated=isolated, areas_without_stitching=areas_plain, areas=[len(v) for _, v in big], islands=[v for _, v in big[1:]], sizes=sorted(sizes, reverse=True)[:6])


def widen_check(c, paths, names, extra=2):
    """fraction of track nodes of the given nets with no foreign copper within `extra` nodes (room for 0.5 mm)."""
    R = Router(c)
    own = {}
    for k, ps in paths.items():
        cl = set()
        for p in ps:
            cl.update(p)
        own[k] = cl
        R.add(cl, +1)
    out = {}
    for name in names:
        if name not in c.nets or c.nets[name] not in own:
            continue
        k = c.nets[name]
        cl = own[k]
        tot = ok = 0
        for n in cl:
            r = n % c.HW
            l = n - r
            j, i = divmod(r, c.W)
            good = True
            for dj in range(-extra, extra + 1):
                for di in range(-extra, extra + 1):
                    jj, ii = j + dj, i + di
                    if not (0 <= jj < c.Hh and 0 <= ii < c.W):
                        good = False
                        continue
                    m = l + jj * c.W + ii
                    b = c.blk[m]
                    if (R.occ[m] > 0 and m not in cl) or b < -1 or (b >= 0 and b != k):
                        good = False
            tot += 1
            ok += good
        out[name] = round(100.0 * ok / max(tot, 1))
    return out


def main(path, prefix):
    t0 = time.time()
    global _CTX
    _CTX = build(path)
    c = _CTX
    print("grid %d x %d nodes x 2 layers; %d routed nets, %d pads (GND is poured: %d pads); built in %.1f s"
          % (c.W, c.Hh, len(c.nets), sum(len(v) for v in c.net_pads.values()), sum(1 for q in c.pads if q.net == "GND"), time.time() - t0))
    ctx = mp.get_context("fork")
    # ---- 1. every connection alone, in parallel
    jobs = []
    for k in c.net_pads:
        jobs += mst_edges(c, k)
    t1 = time.time()
    with ctx.Pool(2, initializer=_init, initargs=(path,)) as pool:
        res = pool.map(_edge_job, jobs, chunksize=4)
    bad = [(c.names[k], "%s.%s" % (c.net_pads[k][a].ref, c.net_pads[k][a].num), "%s.%s" % (c.net_pads[k][b].ref, c.net_pads[k][b].num)) for k, a, b, l in res if l is None]
    print("1) single connections: %d tested alone in parallel (%.1f s): %d cannot be routed even on an empty board" % (len(jobs), time.time() - t1, len(bad)))
    for b in bad:
        print("   NO PATH", b)
    # ---- 2. all nets together, variants in parallel
    t2 = time.time()
    variants = [(1, "short", 45), (2, "long", 45), (3, "random", 45), (4, "short", 45)]
    with ctx.Pool(2, initializer=_init, initargs=(path,)) as pool:
        outs = pool.map(_variant, variants)
    for o in outs:
        print("   variant seed %d (%s first): %s -> failed pads %d, conflicts %d" % (o["seed"], o["mode"], o["log"][-1], o["score"][0], o["score"][1]))
    best = min(outs, key=lambda o: o["score"])
    print("2) all nets together: %d iterations, %.1f s" % (len(best["log"]), time.time() - t2))
    paths = {int(k): v for k, v in best["paths"].items()}
    failed = {int(k): v for k, v in best["failed"].items()}
    per = stats(c, paths, failed)
    tot_len = sum(v["length"] for v in per.values())
    tot_via = sum(v["vias"] for v in per.values())
    nfail = sum(v["failed"] for v in per.values())
    print("   total track length %.0f mm, vias %d, unrouted pads %d, remaining conflicts %d" % (tot_len, tot_via, nfail, best["score"][1]))
    # ---- 3. pour
    pour = pour_check(c, paths)
    print("3) GND pour: %d pads, isolated: %s, copper areas holding GND pads: %s (without stitching vias: %s)" % (pour["pads"], pour["isolated"] or "none", pour["areas"], pour["areas_without_stitching"]))
    # ---- 4. widening
    wide = widen_check(c, paths, ["+5V", "5V_EXT", "BBB_5V", "RPI_5V", "+3V3", "+5V_SYN", "+5V_DET"])
    print("4) share of the track with room for 0.5 mm: %s" % wide)
    json.dump(dict(grid=dict(X0=c.X0, Y0=c.Y0, W=c.W, H=c.Hh, h=H), per=per, bad=bad, scores=[o["score"] for o in outs],
                   logs=[o["log"] for o in outs], pour=pour, wide=wide, paths={c.names[k]: v for k, v in paths.items()},
                   hot=best["hot"]), open(prefix + ".json", "w"))
    print("done in %.0f s" % (time.time() - t0))
    return c, paths, per, best, pour, wide, bad


if __name__ == "__main__":
    main(sys.argv[1], sys.argv[2] if len(sys.argv) > 2 else "route")
