#!/usr/bin/env python3
"""Project footprint library for the SBC adapter: sadiy.pretty

BBB_Header_2x23_Male_Bottom
    BeagleBone P8 / P9 male header, mounted on the BOTTOM side of the cape
    (plastic body under the board, long pins down into the BBB sockets).

Why a custom footprint: P8 and P9 have pin 1 at the left (Ethernet) end, odd pins on
the lower row and even pins on the upper row (cape seen from the top). The stock
PinHeader_2x23 footprint cannot give that pattern on the bottom side, because KiCad
mirrors a footprint left-right when it is flipped. So this footprint is the MIRROR
IMAGE of the header as seen from the top: pin 1 at the origin, the pin numbers run
towards -x, even pins at -2.54 mm in y. Placed on B.Cu with orientation 0 at the
position of pin 1, KiCad mirrors it again and the pads land exactly on the BBB
pattern (pin index along +x, even pins above the odd ones).

    python3 gen_footprints.py            # writes sadiy.pretty/ and fp-lib-table next to the script
"""
import os
import sys
import uuid

NS = uuid.UUID("3f6c0a52-8a6e-4a0e-9d3a-6c1d5a0b7e11")
_n = [0]


def uid():
    _n[0] += 1
    return str(uuid.uuid5(NS, "fp-%d" % _n[0]))


def f(v):
    s = ("%.4f" % v).rstrip("0").rstrip(".")
    return "0" if s in ("-0", "") else s


PITCH = 2.54
NPIN = 46
NAME = "BBB_Header_2x23_Male_Bottom"


def pad_xy_stored(k):
    """Pad position relative to pin 1, cape seen from the top (this is what is stored in a B.Cu instance)."""
    i = (k - 1) // 2
    return PITCH * i, (0.0 if k % 2 == 1 else -PITCH)


def geometry():
    """Silk / fab / courtyard in the stored (top view) frame. Returns list of (kind, args, layer_base)."""
    xl, xr = -1.38, PITCH * 22 + 1.38
    yt, yb = -PITCH - 1.38, 1.38
    g = []
    for a, b in (((xl, yt), (xr, yt)), ((xr, yt), (xr, yb)), ((xr, yb), (xl, yb)), ((xl, yb), (xl, yt))):
        g.append(("line", (a, b, 0.12), "SilkS"))
    # pin 1 marker: small bar on the left of pad 1
    g.append(("line", ((-2.4, -0.9), (-2.4, 0.9), 0.15), "SilkS"))
    g.append(("rect", ((-1.27, -PITCH - 1.27), (PITCH * 22 + 1.27, 1.27), 0.1), "Fab"))
    g.append(("rect", ((-1.77, -PITCH - 1.78), (PITCH * 22 + 1.77, 1.78), 0.05), "CrtYd"))
    return g


def effects(size, mirror, hide=False):
    s = "(effects (font (size %s %s) (thickness 0.15))%s" % (f(size), f(size), " (justify mirror)" if mirror else "")
    return s + ")"


def kicad_mod():
    """Library footprint (front definition = mirror of the stored/top view)."""
    o = []
    o.append('(footprint "%s"' % NAME)
    o.append("\t(version 20241229)")
    o.append('\t(generator "sadiy_gen_footprints")')
    o.append('\t(generator_version "1.0")')
    o.append('\t(layer "F.Cu")')
    o.append('\t(descr "BeagleBone Black P8/P9 2x23 male header, bottom-side mounting. Mirror image of the top view: '
             'pin 1 at the origin, numbers run to -x, even pins at -2.54 mm. Place on B.Cu, orientation 0, at the BBB pin 1 position.")')
    o.append('\t(tags "BBB BeagleBone cape P8 P9 header bottom mirror")')
    o.append('\t(property "Reference" "REF**" (at -27.94 -5.6 0) (layer "F.SilkS") (uuid "%s") %s)' % (uid(), effects(1, False)))
    o.append('\t(property "Value" "%s" (at -27.94 3.2 0) (layer "F.Fab") (uuid "%s") %s)' % (NAME, uid(), effects(1, False)))
    o.append('\t(property "Datasheet" "" (at 0 0 0) (layer "F.Fab") (hide yes) (uuid "%s") (effects (font (size 1.27 1.27))))' % uid())
    o.append('\t(property "Description" "" (at 0 0 0) (layer "F.Fab") (hide yes) (uuid "%s") (effects (font (size 1.27 1.27))))' % uid())
    o.append("\t(attr through_hole)")
    for kind, a, base in geometry():
        layer = "F." + base
        if kind == "line":
            (x1, y1), (x2, y2), w = a
            o.append('\t(fp_line (start %s %s) (end %s %s) (stroke (width %s) (type solid)) (layer "%s") (uuid "%s"))'
                     % (f(-x1), f(y1), f(-x2), f(y2), f(w), layer, uid()))
        else:
            (x1, y1), (x2, y2), w = a
            o.append('\t(fp_rect (start %s %s) (end %s %s) (stroke (width %s) (type solid)) (fill no) (layer "%s") (uuid "%s"))'
                     % (f(-x1), f(y1), f(-x2), f(y2), f(w), layer, uid()))
    o.append('\t(fp_text user "${REFERENCE}" (at -27.94 -1.27 0) (layer "F.Fab") (uuid "%s") %s)' % (uid(), effects(1, False)))
    for k in range(1, NPIN + 1):
        x, y = pad_xy_stored(k)
        o.append('\t(pad "%d" thru_hole %s (at %s %s) (size 1.7 1.7) (drill 1) (layers "*.Cu" "*.Mask") (remove_unused_layers no) (uuid "%s"))'
                 % (k, "rect" if k == 1 else "circle", f(-x), f(y), uid()))
    o.append("\t(embedded_fonts no)")
    o.append(")")
    return "\n".join(o) + "\n"


def main(out):
    pretty = os.path.join(out, "sadiy.pretty")
    os.makedirs(pretty, exist_ok=True)
    with open(os.path.join(pretty, NAME + ".kicad_mod"), "w") as fh:
        fh.write(kicad_mod())
    with open(os.path.join(out, "fp-lib-table"), "w") as fh:
        fh.write('(fp_lib_table\n  (version 7)\n  (lib (name "sadiy")(type "KiCad")(uri "${KIPRJMOD}/sadiy.pretty")(options "")(descr "SAdiy adapter footprints"))\n)\n')
    print("wrote", pretty)


if __name__ == "__main__":
    main(sys.argv[1] if len(sys.argv) > 1 else os.path.dirname(os.path.abspath(__file__)))
