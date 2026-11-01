#!/usr/bin/env python3
"""Remove the Raspberry Pi connector and everything that exists only for it from the adapter project.

Schematic: J3, JP2, JP4 and the RPi-side series resistors R2..R26 (even) with their wires, labels, no-connect flags and frame.
PCB: the same footprints. Nothing else is touched (hand placement of the user stays as it is).
    python3 remove_rpi.py in.kicad_sch in.kicad_pcb out.kicad_sch out.kicad_pcb
"""
import re, sys
sys.path.insert(0, "/home/claude")
from place_components import match_end
import check_schematic as cs

REMOVE = {"J3", "JP2", "JP4"} | {"R%d" % n for n in range(2, 27, 2)}


def items_of(s):
    out, i = [], 0
    rx = re.compile(r"\n\t\(([\w_]+)")
    while True:
        m = rx.search(s, i)
        if not m:
            break
        a = m.start() + 2
        b = match_end(s, a)
        out.append([m.group(1), a, b])
        i = b
    return out


def pt(x, y):
    return (round(float(x), 2), round(float(y), 2))


def on_seg(p, a, b):
    if a[0] == b[0] == p[0]:
        return min(a[1], b[1]) <= p[1] <= max(a[1], b[1])
    if a[1] == b[1] == p[1]:
        return min(a[0], b[0]) <= p[0] <= max(a[0], b[0])
    return False


def do_sch(s):
    tree = cs.parse(s)
    libpins = {}
    for sym in cs.find(cs.find(tree, "lib_symbols")[0], "symbol"):
        name = cs.val(sym[1])
        pins = {}
        for sub in cs.find(sym, "symbol"):
            for p in cs.find(sub, "pin"):
                at = cs.find(p, "at")[0]
                pins[cs.val(cs.find(p, "number")[0][1])] = (float(at[1]), float(at[2]))
        libpins[name] = pins
    its = items_of(s)
    # --- classify
    syms, wires, labels, ncs = [], [], [], []
    for it in its:
        t, a, b = it
        body = s[a:b]
        if t == "symbol" and body.startswith("(symbol\n"):
            lib = re.search(r'\(lib_id "([^"]+)"', body).group(1)
            at = re.search(r"\(at ([-\d.]+) ([-\d.]+) ([-\d.]+)\)", body)
            ref = re.search(r'\(property "Reference" "([^"]+)"', body).group(1)
            assert float(at.group(3)) == 0, ref
            x, y = float(at.group(1)), float(at.group(2))
            pins = {n: pt(x + px, y - py) for n, (px, py) in libpins[lib].items()}
            syms.append(dict(it=it, ref=ref, lib=lib, pins=pins))
        elif t == "wire":
            xy = re.findall(r"\(xy ([-\d.]+) ([-\d.]+)\)", s[a:b])
            wires.append(dict(it=it, a=pt(*xy[0]), b=pt(*xy[1])))
        elif t == "label":
            m = re.search(r'\(label "([^"]+)"\s+\(at ([-\d.]+) ([-\d.]+)', s[a:b])
            labels.append(dict(it=it, name=m.group(1), p=pt(m.group(2), m.group(3))))
        elif t == "no_connect":
            m = re.search(r"\(at ([-\d.]+) ([-\d.]+)", s[a:b])
            ncs.append(dict(it=it, p=pt(*m.groups())))
    gone = {x["ref"] for x in syms} & REMOVE
    assert gone == REMOVE, REMOVE - gone
    rem = [x for x in syms if x["ref"] in REMOVE]
    kept = [x for x in syms if x["ref"] not in REMOVE]
    rpins = {p for x in rem for p in x["pins"].values()}
    kpins = {p for x in kept for p in x["pins"].values()}
    delete, edits = set(), []   # delete: item ids; edits: (a, b, newtext)
    dead_w = []
    for w in wires:
        ends = (w["a"], w["b"])
        hit = [e for e in ends if e in rpins]
        if not hit:
            continue
        P = hit[0]
        Q = w["b"] if P == w["a"] else w["a"]
        if Q in kpins:
            # keep it, but end it on the label that sits on the wire (the common net label)
            lab = [l for l in labels if on_seg(l["p"], w["a"], w["b"]) and l["p"] not in (w["a"], w["b"])]
            assert len(lab) == 1, (w, lab)
            a, b = w["it"][1], w["it"][2]
            txt = s[a:b]
            old = "(xy %s %s)" % tuple(re.findall(r"\(xy ([-\d.]+) ([-\d.]+)\)", txt)[0 if P == w["a"] else 1])
            new = "(xy %s %s)" % (("%g" % lab[0]["p"][0]), ("%g" % lab[0]["p"][1]))
            edits.append((a, b, txt.replace(old, new, 1)))
            w["a" if P == w["a"] else "b"] = lab[0]["p"]
        else:
            delete.add(id(w["it"]))
            dead_w.append(w)
    live_w = [w for w in wires if w not in dead_w]
    touching = lambda p: any(on_seg(p, w["a"], w["b"]) for w in live_w) or p in kpins
    for l in labels:
        if any(on_seg(l["p"], w["a"], w["b"]) for w in dead_w) or l["p"] in rpins:
            if not touching(l["p"]):
                delete.add(id(l["it"]))
    for n in ncs:
        if n["p"] in rpins and n["p"] not in kpins:
            delete.add(id(n["it"]))
    for x in rem:
        delete.add(id(x["it"]))
    # RPi frame (rectangle) and its title text, lib symbol
    for it in its:
        t, a, b = it
        body = s[a:b]
        if t == "text" and ("Raspberry Pi 40-pin (IDC" in body):
            delete.add(id(it))
        if t == "rectangle":
            m = re.search(r"\(start ([-\d.]+) ([-\d.]+)\)", body)
            if m and abs(float(m.group(1)) - 305) < 0.01:
                delete.add(id(it))
        if t == "lib_symbols":
            for sm in re.finditer(r'\n\t\t\(symbol "sadiy:Conn_RPi_40"', body):
                a2 = a + sm.start() + 3
                b2 = match_end(s, a2)
                edits.append((a2 - 1, b2, ""))
    # text rewrites
    rep = [
        ("SAdiy SBC adapter: BeagleBone Black cape OR Raspberry Pi ribbon cable to the module boards",
         "SAdiy SBC adapter: BeagleBone Black cape for the module boards"),
        ("Signal rows: BBB side - 220 ohm - common net - 220 ohm - RPi side", "Signal rows: BBB header - 220 ohm - module net"),
        ("RPi / ADS1115 path (A0)", "ADS1115 path (A0)"),
        ("DNP I2C pull-ups: the Pi has 1.8k on SDA1/SCL1,\\nthe BBB has them on I2C2.", "DNP I2C pull-ups: the BBB already has them on I2C2."),
        ("  JP2 fitted: RPi 5V (pins 2/4) joins the rail\\n", ""),
        ("  JP3 fitted for the BBB, JP4 for the RPi, never both", "  JP3 fitted: BBB 3V3 (P9.3/4) joins the rail"),
        ("A) external 5V on J11 powers the SBC: fit that SBC's jumper,\\n     and do NOT plug the SBC's own supply\\n  B) SBC powers the modules: fit its jumper, leave J11 empty",
         "A) external 5V on J11 powers the BBB: fit JP1,\\n     and do NOT plug the BBB's own supply\\n  B) the BBB powers the modules: fit JP1, leave J11 empty"),
        ("3V3 rail (+3V3), from the SBC only:", "3V3 rail (+3V3), from the BBB only:"),
        ("BBB I2C2 (P9.19/20) and RPi I2C1 (pins 3/5) share I2C_SCL/I2C_SDA for the ADS1115.", "BBB I2C2 (P9.19/20) drives I2C_SCL/I2C_SDA for the ADS1115."),
        ("Unused BBB/RPi pins carry no connection (X).", "Unused BBB pins carry no connection (X)."),
        ("  J3: 2x20 shrouded IDC header, TOP side, at the board edge, for a straight 1:1 ribbon to the Pi (pin n to pin n).\\n", ""),
        ("Use ONE SBC at a time. Every SBC signal has a 220 ohm series resistor on each side, so a mistake with both attached limits the contention current.",
         "Every BBB signal has a 220 ohm series resistor at the BBB header (source termination, limits fault current)."),
        ("BeagleBone Black cape or Raspberry Pi ribbon, pin map from hw/netlist.md", "BeagleBone Black cape, pin map from hw/netlist.md"),
    ]
    out = []
    # apply deletions + edits from the back
    ops = [(a, b, "") for (t, a, b) in its if id([x for x in its if x[1] == a][0]) in delete]
    ops = []
    for it in its:
        if id(it) in delete:
            ops.append((it[1] - 2, it[2], ""))   # include the leading "\n\t"
    ops += edits
    ops.sort(key=lambda o: -o[0])
    for a, b, new in ops:
        s = s[:a] + new + s[b:]
    for o, n in rep:
        if o in s:
            s = s.replace(o, n)
        else:
            print("  note: text not found:", o[:50])
    return s, sorted(REMOVE), len(delete)


def do_pcb(s):
    its = items_of(s)
    ops = []
    found = set()
    for t, a, b in its:
        if t == "footprint":
            ref = re.search(r'\(property "Reference" "([^"]+)"', s[a:b]).group(1)
            if ref in REMOVE:
                found.add(ref)
                ops.append((a - 2, b))
    assert found == REMOVE, REMOVE - found
    for a, b in sorted(ops, reverse=True):
        s = s[:a] + s[b:]
    return s


if __name__ == "__main__":
    sch, pcb, osch, opcb = sys.argv[1:5]
    s, refs, nd = do_sch(open(sch).read())
    open(osch, "w").write(s)
    print("schematic: removed %s, %d items deleted" % (refs, nd))
    p = do_pcb(open(pcb).read())
    open(opcb, "w").write(p)
    print("pcb: footprints removed")
