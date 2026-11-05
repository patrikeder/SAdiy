#!/usr/bin/env python3
"""Place the SBC connectors of sa_sbc_adapter.kicad_pcb to the BeagleBone cape geometry.

  J1 (BBB P9)  bottom side, custom footprint sadiy:BBB_Header_2x23_Male_Bottom, pin 1 at the BBB P9 pin 1 position
  J2 (BBB P8)  bottom side, same footprint, pin 1 at the BBB P8 pin 1 position
  J3 (RPi IDC) top side, rotated 90 degrees so it runs in the same direction as P8/P9
               (pin 1 at the left, even pins on the upper row), just inside P8, pin 1 on the same x as P8 pin 1
  Dwgs.User    reference outline of the cape (86.36 x 54.61 mm) and P8 / P9 / Ethernet-end labels

Cape geometry (BeagleBone cape standard, from the SparkFun BEAGLE_BONE_BLACK_CAPE footprint made from the BBB gerbers),
cape seen from the top, origin at the top-left corner of the cape outline (OX, OY on the board):
  pin 1 of P8 and P9 at x = 20.32 mm (the Ethernet end is the left end)
  P8 odd row  y = 4.445,  even row y = 1.905   (even pins are the outer row, next to the top edge)
  P9 odd row  y = 52.705, even row y = 50.165  (odd pins are the outer row, next to the bottom edge)
  pitch 2.54 mm, 23 pins per row.

    python3 place_connectors.py [in.kicad_pcb [out.kicad_pcb [OX OY]]]
"""
import math
import re
import sys
import uuid

NS = uuid.UUID("9b1d0a52-3c6e-4f0e-8d3a-6c1d5a0b7e12")
OX_DEFAULT, OY_DEFAULT = 170.0, 40.0
CAPE_W, CAPE_H = 86.36, 54.61
FP_BBB = "sadiy:BBB_Header_2x23_Male_Bottom"
PITCH = 2.54
P1_X = 20.32
P8_ODD_Y, P8_EVEN_Y = 4.445, 1.905
P9_ODD_Y, P9_EVEN_Y = 52.705, 50.165
J3_EVEN_Y = 14.605            # J3 upper (even) row, cape y; shroud top then clears the resistor channel under P8
J3_PIN1_X = P1_X + 3 * PITCH  # J3 pin 1 on the P8 column of pin 7: the shroud stays out of the Ethernet notch


def fmt(v):
    s = ("%.4f" % v).rstrip("0").rstrip(".")
    return "0" if s in ("-0", "") else s


def uid(name):
    return str(uuid.uuid5(NS, name))


def match_end(s, i):
    """Index just after the s-expression starting at s[i] == '(' (string aware)."""
    depth = 0
    instr = False
    j = i
    while j < len(s):
        c = s[j]
        if instr:
            if c == "\\":
                j += 1
            elif c == '"':
                instr = False
        else:
            if c == '"':
                instr = True
            elif c == "(":
                depth += 1
            elif c == ")":
                depth -= 1
                if depth == 0:
                    return j + 1
        j += 1
    raise ValueError("unbalanced")


def find_footprint(s, ref):
    i = s.index('(property "Reference" "%s"' % ref)
    st = s.rfind("\n\t(footprint ", 0, i) + 1
    st = s.index("(footprint ", st)
    return st, match_end(s, st)


def remove_children(b, names, indent="\n\t\t"):
    """Remove direct children of the footprint block b whose tag is in names."""
    out = []
    pos = 0
    pat = re.compile(re.escape(indent) + r"\((%s)\b" % "|".join(names))
    while True:
        m = pat.search(b, pos)
        if not m:
            out.append(b[pos:])
            break
        st = m.start() + len(indent) - 0
        st = m.start()
        paren = b.index("(", st)
        en = match_end(b, paren)
        out.append(b[pos:st])
        pos = en
    return "".join(out)


def line(x1, y1, x2, y2, w, layer, tag):
    return ('\t\t(fp_line\n\t\t\t(start %s %s)\n\t\t\t(end %s %s)\n\t\t\t(stroke\n\t\t\t\t(width %s)\n\t\t\t\t(type solid)\n\t\t\t)\n'
            '\t\t\t(layer "%s")\n\t\t\t(uuid "%s")\n\t\t)\n' % (fmt(x1), fmt(y1), fmt(x2), fmt(y2), fmt(w), layer, uid(tag)))


def rect(x1, y1, x2, y2, w, layer, tag):
    return ('\t\t(fp_rect\n\t\t\t(start %s %s)\n\t\t\t(end %s %s)\n\t\t\t(stroke\n\t\t\t\t(width %s)\n\t\t\t\t(type solid)\n\t\t\t)\n'
            '\t\t\t(fill no)\n\t\t\t(layer "%s")\n\t\t\t(uuid "%s")\n\t\t)\n' % (fmt(x1), fmt(y1), fmt(x2), fmt(y2), fmt(w), layer, uid(tag)))


def text_user(txt, x, y, ang, layer, size, mirror, tag):
    return ('\t\t(fp_text user "%s"\n\t\t\t(at %s %s %s)\n\t\t\t(layer "%s")\n\t\t\t(uuid "%s")\n\t\t\t(effects\n\t\t\t\t(font\n'
            '\t\t\t\t\t(size %s %s)\n\t\t\t\t\t(thickness 0.15)\n\t\t\t\t)\n%s\t\t\t)\n\t\t)\n'
            % (txt, fmt(x), fmt(y), fmt(ang), layer, uid(tag), fmt(size), fmt(size), "\t\t\t\t(justify mirror)\n" if mirror else ""))


def prop_block(name, value, x, y, ang, layer, uuid_s, mirror):
    return ('\t\t(property "%s" "%s"\n\t\t\t(at %s %s %s)\n\t\t\t(layer "%s")\n\t\t\t(uuid "%s")\n\t\t\t(effects\n\t\t\t\t(font\n'
            '\t\t\t\t\t(size 1 1)\n\t\t\t\t\t(thickness 0.15)\n\t\t\t\t)\n%s\t\t\t)\n\t\t)' % (name, value, fmt(x), fmt(y), fmt(ang), layer, uuid_s,
                                                                                    "\t\t\t\t(justify mirror)\n" if mirror else ""))


def get_uuid(block, name):
    m = re.search(r'\(property "%s" "[^"]*"\s*\(at [^)]*\)\s*\(layer "[^"]*"\)\s*(?:\(hide yes\)\s*)?\(uuid "([^"]+)"\)' % re.escape(name), block)
    return m.group(1)


def stored_pad(k):
    i = (k - 1) // 2
    return PITCH * i, (0.0 if k % 2 == 1 else -PITCH)


def bbb_header(block, ref, value, fx, fy):
    """Turn the J1/J2 footprint block into the bottom-side BBB header at (fx, fy)."""
    ref_uuid, val_uuid = get_uuid(block, "Reference"), get_uuid(block, "Value")
    # header lines
    block = re.sub(r'^\(footprint "[^"]+"', '(footprint "%s"' % FP_BBB, block, count=1)
    block = re.sub(r'\(layer "F\.Cu"\)', '(layer "B.Cu")', block, count=1)
    block = re.sub(r'\n\t\t\(at [-\d. ]+\)', '\n\t\t(at %s %s)' % (fmt(fx), fmt(fy)), block, count=1)
    block = re.sub(r'\n\t\t\(descr "[^"]*"\)', '\n\t\t(descr "BeagleBone Black P8/P9 2x23 male header, bottom-side mounting (mirror image, see gen_footprints.py)")', block, count=1)
    block = re.sub(r'\n\t\t\(tags "[^"]*"\)', '\n\t\t(tags "BBB BeagleBone cape P8 P9 header bottom mirror")', block, count=1)
    # properties: Reference / Value rebuilt, hidden ones moved to the back layers, generator property dropped
    for name in ("Reference", "Value", "KiLib_Generator"):
        m = re.search(r'\n\t\t\(property "%s"' % name, block)
        if m:
            st = block.index("(", m.start())
            en = match_end(block, st)
            if name == "Reference":
                new = prop_block("Reference", ref, 27.94, -5.6, 0, "B.SilkS", ref_uuid, True)
            elif name == "Value":
                new = prop_block("Value", value, 27.94, 3.2, 0, "B.Fab", val_uuid, True)
            else:
                new = None
            block = block[:m.start()] + ("\n" + new if new else "") + block[en:]
    block = block.replace('(layer "F.Fab")', '(layer "B.Fab")').replace('(layer "F.SilkS")', '(layer "B.SilkS")')
    # graphics and 3D model out, new graphics in
    block = remove_children(block, ["fp_line", "fp_rect", "fp_text", "fp_circle", "fp_arc", "fp_poly", "model"])
    g = ""
    xl, xr = -1.38, PITCH * 22 + 1.38
    yt, yb = -PITCH - 1.38, 1.38
    for n_, (a, b) in enumerate((((xl, yt), (xr, yt)), ((xr, yt), (xr, yb)), ((xr, yb), (xl, yb)), ((xl, yb), (xl, yt)))):
        g += line(a[0], a[1], b[0], b[1], 0.12, "B.SilkS", ref + "-silk%d" % n_)
    g += line(-2.4, -0.9, -2.4, 0.9, 0.15, "B.SilkS", ref + "-pin1")
    g += rect(-1.27, -PITCH - 1.27, PITCH * 22 + 1.27, 1.27, 0.1, "B.Fab", ref + "-fab")
    g += rect(-1.77, -PITCH - 1.78, PITCH * 22 + 1.77, 1.78, 0.05, "B.CrtYd", ref + "-crtyd")
    g += text_user("${REFERENCE}", 27.94, -1.27, 0, "B.Fab", 1, True, ref + "-reftext")
    k = block.index("\n\t\t(pad ")
    block = block[:k + 1] + g.lstrip("\n") + block[k + 1:]

    def pad_at(m):
        x, y = stored_pad(int(m.group(2)))
        return "%s(at %s %s)" % (m.group(1), fmt(x), fmt(y))
    block = re.sub(r'(\n\t\t\(pad "(\d+)" thru_hole \w+\n\t\t\t)\(at [-\d. ]+\)', pad_at, block)
    return block


def idc_block(block, x, y, ang):
    block = re.sub(r'\n\t\t\(at [-\d. ]+\)', '\n\t\t(at %s %s %s)' % (fmt(x), fmt(y), fmt(ang)), block, count=1)
    # keep the reference / value texts upright: stored angle is relative to the footprint
    for name in ("Reference", "Value"):
        m = re.search(r'(\(property "%s" "[^"]*"\s*\(at [-\d.]+ [-\d.]+ )[-\d.]+(\))' % name, block)
        block = block[:m.start()] + m.group(1) + fmt(-ang) + m.group(2) + block[m.end():]
    return block


def outline(ox, oy):
    s = ""
    lay = "Dwgs.User"

    def rect_item(x1, y1, x2, y2, tag, kind="dash"):
        return ('\t(gr_rect\n\t\t(start %s %s)\n\t\t(end %s %s)\n\t\t(stroke\n\t\t\t(width 0.1)\n\t\t\t(type %s)\n\t\t)\n\t\t(fill no)\n\t\t(layer "%s")\n\t\t(uuid "%s")\n\t)\n'
                % (fmt(x1), fmt(y1), fmt(x2), fmt(y2), kind, lay, uid(tag)))

    def arc_item(a, m, b, tag):
        return ('\t(gr_arc\n\t\t(start %s %s)\n\t\t(mid %s %s)\n\t\t(end %s %s)\n\t\t(stroke\n\t\t\t(width 0.1)\n\t\t\t(type dash)\n\t\t)\n\t\t(layer "%s")\n\t\t(uuid "%s")\n\t)\n'
                % (fmt(ox + a[0]), fmt(oy + a[1]), fmt(ox + m[0]), fmt(oy + m[1]), fmt(ox + b[0]), fmt(oy + b[1]), lay, uid(tag)))
    s += rect_item(ox, oy, ox + CAPE_W, oy + CAPE_H, "outline")
    s += rect_item(ox, oy + 15.875, ox + 20.32, oy + 33.655, "notch")      # Ethernet connector keep-out
    s += rect_item(ox, oy, ox + 5.715, oy + 15.875, "cut")                 # top-left corner cut
    s += arc_item((73.66, 0), (82.64, 3.72), (86.36, 12.7), "arc-tr")       # rounded cape corners
    s += arc_item((86.36, 41.91), (82.64, 50.89), (73.66, 54.61), "arc-br")
    s += arc_item((0, 48.26), (1.86, 52.75), (6.35, 54.61), "arc-bl")
    labels = [("BBB cape outline 86.36 x 54.61 mm (reference, not the board edge). Ethernet end = left end, P8 on top, P9 at the bottom",
               ox, oy - 2.0, "outline-title"),
              ("P8", ox + P1_X - 8.0, oy + 3.2, "lab-p8"), ("P9", ox + P1_X - 8.0, oy + 51.4, "lab-p9"),
              ("pin 1", ox + P1_X - 1.0, oy + CAPE_H + 3.0, "lab-pin1"),
              ("Ethernet keep-out", ox + 1.0, oy + 25.5, "lab-notch")]
    for txt, x, y, tag in labels:
        s += ('\t(gr_text "%s"\n\t\t(at %s %s 0)\n\t\t(layer "%s")\n\t\t(uuid "%s")\n\t\t(effects\n\t\t\t(font\n\t\t\t\t(size 1.2 1.2)\n\t\t\t\t(thickness 0.15)\n\t\t\t)\n'
              '\t\t\t(justify left bottom)\n\t\t)\n\t)\n' % (txt, fmt(x), fmt(y), lay, uid(tag)))
    return s


def strip_old_outline(s):
    known = [uid(t) for t in ("outline", "outline-title", "lab-p8", "lab-p9", "lab-pin1", "notch", "cut", "arc-tr", "arc-br", "arc-bl", "lab-notch")]
    pos = 0
    while True:
        m = re.search(r'\n\t\((gr_rect|gr_text|gr_arc)\b', s[pos:])
        if not m:
            return s
        st = pos + m.start()
        paren = s.index("(", st)
        en = match_end(s, paren)
        if any(k in s[st:en] for k in known):
            s = s[:st] + s[en:]
            pos = st
        else:
            pos = en


def main(src, dst, ox, oy):
    s = open(src).read()
    nets_before = {}
    for ref in ("J1", "J2", "J3"):
        st, en = find_footprint(s, ref)
        nets_before[ref] = re.findall(r'\(pad "(\d+)" .*?\(net "([^"]*)"\)', s[st:en], re.S)
    # J1 (P9)
    st, en = find_footprint(s, "J1")
    blk = bbb_header(s[st:en], "J1", "BBB P9", ox + P1_X, oy + P9_ODD_Y)
    s = s[:st] + blk + s[en:]
    # J2 (P8)
    st, en = find_footprint(s, "J2")
    blk = bbb_header(s[st:en], "J2", "BBB P8", ox + P1_X, oy + P8_ODD_Y)
    s = s[:st] + blk + s[en:]
    # J3 (IDC), pin 1 = lower row, rotated 90: pin 2 above pin 1, pin 3 to the right
    st, en = find_footprint(s, "J3")
    blk = idc_block(s[st:en], ox + J3_PIN1_X, oy + J3_EVEN_Y + PITCH, 90)
    s = s[:st] + blk + s[en:]
    # outline
    s = strip_old_outline(s)
    k = s.rindex("\n\t(embedded_fonts")
    s = s[:k + 1] + outline(ox, oy) + s[k + 1:]
    open(dst, "w").write(s)
    # self check
    match_end(s, s.index("(kicad_pcb"))
    for ref in ("J1", "J2", "J3"):
        st, en = find_footprint(s, ref)
        after = re.findall(r'\(pad "(\d+)" .*?\(net "([^"]*)"\)', s[st:en], re.S)
        assert after == nets_before[ref], ref + ": pad nets changed"
    print("ok: nets of J1/J2/J3 unchanged, cape origin (%s, %s)" % (fmt(ox), fmt(oy)))


if __name__ == "__main__":
    a = sys.argv[1:]
    src = a[0] if len(a) > 0 else "sa_sbc_adapter.kicad_pcb"
    dst = a[1] if len(a) > 1 else src
    ox = float(a[2]) if len(a) > 2 else OX_DEFAULT
    oy = float(a[3]) if len(a) > 3 else OY_DEFAULT
    main(src, dst, ox, oy)
