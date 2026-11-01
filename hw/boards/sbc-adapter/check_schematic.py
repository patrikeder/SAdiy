#!/usr/bin/env python3
"""Independent connectivity check of the generated .kicad_sch (no KiCad needed).

Parses the file, builds nets from wires / labels / pin positions, and checks them
against the pin map in hw/netlist.md (copied below as EXPECTED).
"""
import re
import sys
from collections import defaultdict


def parse(text):
    tokens = re.findall(r'"(?:[^"\\]|\\.)*"|\(|\)|[^\s()]+', text)
    pos = 0

    def rd():
        nonlocal pos
        t = tokens[pos]
        pos += 1
        if t == "(":
            lst = []
            while tokens[pos] != ")":
                lst.append(rd())
            pos += 1
            return lst
        if t.startswith('"'):
            return ("S", t[1:-1])
        return t

    tree = rd()
    assert pos == len(tokens), "trailing tokens: unbalanced parentheses"
    return tree


def val(x):
    return x[1] if isinstance(x, tuple) else x


def find(node, key):
    return [c for c in node if isinstance(c, list) and c and c[0] == key]


def main(path):
    tree = parse(open(path).read())
    assert tree[0] == "kicad_sch"
    # lib pins
    libpins = {}
    for sym in find(find(tree, "lib_symbols")[0], "symbol"):
        name = val(sym[1])
        pins = {}
        for sub in find(sym, "symbol"):
            for p in find(sub, "pin"):
                at = find(p, "at")[0]
                num = val(find(p, "number")[0][1])
                pins[num] = (float(at[1]), float(at[2]), val(find(p, "name")[0][1]), p[1])
        libpins[name] = pins
    parent = {}

    def F(a):
        parent.setdefault(a, a)
        while parent[a] != a:
            parent[a] = parent[parent[a]]
            a = parent[a]
        return a

    def U(a, b):
        parent[F(a)] = F(b)

    def pt(x, y):
        return (round(float(x), 2), round(float(y), 2))

    segs = []
    for w in find(tree, "wire"):
        xy = find(find(w, "pts")[0], "xy")
        a, b = pt(*xy[0][1:3]), pt(*xy[1][1:3])
        segs.append((a, b))
        U(a, b)
    labels = []
    for l in find(tree, "label"):
        at = find(l, "at")[0]
        labels.append((val(l[1]), pt(at[1], at[2])))
    ncs = {pt(*find(c, "at")[0][1:3]) for c in find(tree, "no_connect")}
    refpin = {}   # (ref,num) -> point
    refinfo = {}
    for s in find(tree, "symbol"):
        lib = val(find(s, "lib_id")[0][1])
        at = find(s, "at")[0]
        x, y = float(at[1]), float(at[2])
        assert float(at[3]) == 0
        props = {val(p[1]): val(p[2]) for p in find(s, "property")}
        ref = props["Reference"]
        refinfo[ref] = (lib, props["Value"], find(s, "dnp")[0][1])
        for num, (px, py, pname, ptype) in libpins[lib].items():
            refpin[(ref, num)] = pt(x + px, y - py)
        if lib.split(":")[1] in ("GND", "+3V3", "+5V"):
            labels.append((props["Value"], refpin[(ref, "1")]))
    # label touching a wire interior
    def on_seg(p, a, b):
        if a[0] == b[0] == p[0]:
            return min(a[1], b[1]) <= p[1] <= max(a[1], b[1])
        if a[1] == b[1] == p[1]:
            return min(a[0], b[0]) <= p[0] <= max(a[0], b[0])
        return False

    for name, p in labels:
        F(p)
        for a, b in segs:
            if on_seg(p, a, b):
                U(p, a)
    for p in refpin.values():
        F(p)
        for a, b in segs:
            if on_seg(p, a, b):
                U(p, a)
    byname = defaultdict(list)
    for name, p in labels:
        byname[name].append(p)
    for name, ps in byname.items():
        for p in ps[1:]:
            U(ps[0], p)
    netname = {}
    for name, ps in byname.items():
        r = F(ps[0])
        if r in netname and netname[r] != name:
            raise SystemExit("SHORT: nets %s and %s are joined" % (netname[r], name))
        netname[r] = name
    # also detect two different names in one component
    comp_names = defaultdict(set)
    for name, ps in byname.items():
        for p in ps:
            comp_names[F(p)].add(name)
    errs = []
    for r, names in comp_names.items():
        if len(names) > 1:
            errs.append("SHORT: %s" % sorted(names))

    def net_of(ref, num):
        p = refpin[(ref, num)]
        return netname.get(F(p))

    # --- expected pin map (hw/netlist.md)
    EXPECTED = {   # net: (BBB ref, pin, RPi pin, module ref, module pin)
        "SYN_CLK": ("J1", "22", "23", "J6", "7"), "SYN_DATA": ("J1", "18", "19", "J6", "6"),
        "SYN_LE": ("J1", "17", "24", "J6", "5"), "SYN_LD": ("J1", "23", "35", "J6", "9"),
        "ATT_V1": ("J2", "7", "29", "J4", "2"), "ATT_V2": ("J2", "8", "31", "J4", "3"),
        "ATT_V3": ("J2", "9", "32", "J4", "4"), "ATT_V4": ("J2", "10", "33", "J4", "5"),
        "ATT_V5": ("J2", "11", "38", "J4", "6"), "ATT_V6": ("J2", "12", "40", "J4", "7"),
        "I2C_SDA": ("J1", "20", "3", "J10", "4"), "I2C_SCL": ("J1", "19", "5", "J10", "3"),
    }
    # two-pin resistor graph: net -> neighbours via series resistors
    res_edges = defaultdict(set)
    for ref, (lib, value, dnp) in refinfo.items():
        if lib.endswith(":R_H"):
            a, b = net_of(ref, "1"), net_of(ref, "2")
            res_edges[a].add((b, ref))
            res_edges[b].add((a, ref))

    def via_one_resistor(n1, n2):
        return any(nb == n2 for nb, _ in res_edges[n1])

    ok = 0
    for net, (bref, bpin, rpin, mref, mpin) in EXPECTED.items():
        nb, nr, nm = net_of(bref, bpin), net_of("J3", rpin), net_of(mref, mpin)
        if nm != net:
            errs.append("%s: module %s.%s is on %r" % (net, mref, mpin, nm))
        if not via_one_resistor(nb, net):
            errs.append("%s: BBB %s.%s net %r not one resistor from %s" % (net, bref, bpin, nb, net))
        if not via_one_resistor(nr, net):
            errs.append("%s: RPi pin %s net %r not one resistor from %s" % (net, rpin, nr, net))
        ok += 1
    # CE via jumper block, others
    checks = {
        ("J1", "27"): "BBB_SYN_CE", ("J3", "36"): "RPI_SYN_CE", ("J12", "3"): "SYN_CE", ("J12", "2"): "SYN_CE_M",
        ("J12", "1"): "+3V3", ("J6", "3"): "SYN_CE_M", ("J6", "10"): "SYN_PDR", ("JP5", "2"): "SYN_PDR",
        ("J6", "1"): "GND", ("J6", "4"): "GND", ("J6", "8"): "SYN_MUX",
        ("J4", "1"): "GND", ("J5", "1"): "+3V3_ATT",
        ("J1", "39"): "BBB_AIN0", ("J1", "34"): "AGND", ("J1", "32"): "BBB_VDD_ADC",
        ("J1", "3"): "BBB_3V3", ("J1", "4"): "BBB_3V3", ("J1", "5"): "BBB_5V", ("J1", "6"): "BBB_5V",
        ("J3", "1"): "RPI_3V3", ("J3", "17"): "RPI_3V3", ("J3", "2"): "RPI_5V", ("J3", "4"): "RPI_5V",
        ("J2", "1"): "GND", ("J2", "2"): "GND",
        ("J10", "1"): "+3V3", ("J10", "2"): "GND", ("J10", "5"): "GND", ("J10", "7"): "ADS_A0",
        ("J8", "1"): "DET_OUT", ("J8", "2"): "AGND", ("J9", "1"): "+5V_DET", ("J9", "2"): "GND",
        ("J7", "1"): "+5V_SYN", ("J7", "2"): "GND", ("J11", "1"): "5V_EXT",
        ("JP1", "1"): "+5V", ("JP1", "2"): "BBB_5V", ("JP2", "2"): "RPI_5V",
        ("JP3", "2"): "BBB_3V3", ("JP4", "2"): "RPI_3V3", ("JP3", "1"): "+3V3", ("JP4", "1"): "+3V3",
        ("JP6", "1"): "DET_OUT", ("JP6", "2"): "DET_DIV",
    }
    for (ref, num), want in checks.items():
        got = net_of(ref, num)
        if got != want:
            errs.append("%s.%s: expected %s got %s" % (ref, num, want, got))
    for p in (6, 9, 14, 20, 25, 30, 34, 39):
        if net_of("J3", str(p)) != "GND":
            errs.append("J3.%d not GND" % p)
    for p in (1, 2, 43, 44, 45, 46):
        if net_of("J1", str(p)) != "GND":
            errs.append("J1.%d not GND" % p)
    # every connector pin either NC or on a named net with >= 1 other pin on it
    members = defaultdict(list)
    for (ref, num), p in refpin.items():
        members[netname.get(F(p))].append((ref, num))
    unconnected = []
    for (ref, num), p in refpin.items():
        lib = refinfo[ref][0]
        nm = netname.get(F(p))
        if p in ncs:
            continue
        if nm is None:
            unconnected.append((ref, num))
        elif len(members[nm]) < 2 and not lib.endswith("PWR_FLAG"):
            unconnected.append((ref, num, nm, "only pin on net"))
    # no-connect markers must sit on a pin that is otherwise unconnected
    for c in ncs:
        pins_here = [k for k, p in refpin.items() if p == c]
        if not pins_here:
            errs.append("no_connect at %s with no pin" % (c,))
        elif any(p == c for _, p in labels) :
            errs.append("no_connect on a labelled pin %s" % pins_here)
    # grid and dangling-wire checks
    def ongrid(v):
        q = v / 1.27
        return abs(q - round(q)) < 0.004
    for a, b in segs:
        for p in (a, b):
            if not (ongrid(p[0]) and ongrid(p[1])):
                errs.append("off-grid wire end %s" % (p,))
    for name, p in labels:
        if not (ongrid(p[0]) and ongrid(p[1])):
            errs.append("off-grid label %s at %s" % (name, p))
    touch = defaultdict(int)
    for a, b in segs:
        touch[a] += 1
        touch[b] += 1
    anchors = {p for _, p in labels} | set(refpin.values())
    for a, b in segs:
        if a[0] != b[0] and a[1] != b[1]:
            errs.append("diagonal wire %s-%s" % (a, b))
    for p, cnt in touch.items():
        if cnt == 1 and p not in anchors:
            errs.append("dangling wire end at %s" % (p,))
    # series resistor values
    print("rows checked:", ok, "components:", len(refinfo), "nets:", len(set(netname.values())))
    print("unconnected pins (excluding NC-marked):", unconnected if unconnected else "none")
    print("nc markers:", len(ncs))
    if errs:
        print("ERRORS:")
        for e in errs:
            print("  ", e)
        return 1
    print("ALL CHECKS PASSED")
    return 0


if __name__ == "__main__":
    sys.exit(main(sys.argv[1] if len(sys.argv) > 1 else "sa_sbc_adapter.kicad_sch"))
