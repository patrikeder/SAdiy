#!/usr/bin/env python3
"""Check the connector placement in the .kicad_pcb against the BeagleBone cape geometry (no KiCad needed)."""
import math, re, sys
sys.path.insert(0, '.')
from place_connectors import find_footprint, match_end

def parse_fp(s, ref):
    st, en = find_footprint(s, ref)
    b = s[st:en]
    lib = re.match(r'\(footprint "([^"]+)"', b).group(1)
    layer = re.search(r'\(layer "([^"]+)"\)', b).group(1)
    at = re.search(r'\n\t\t\(at ([-\d.]+) ([-\d.]+)(?: ([-\d.]+))?\)', b)
    fx, fy, ang = float(at.group(1)), float(at.group(2)), float(at.group(3) or 0)
    pads = {}
    for m in re.finditer(r'\(pad "(\d+)" thru_hole \w+\n\t\t\t\(at ([-\d.]+) ([-\d.]+)\)', b):
        pads[int(m.group(1))] = (float(m.group(2)), float(m.group(3)))
    return b, lib, layer, (fx, fy, ang), pads

def absxy(fp, p):
    fx, fy, a = fp
    r = math.radians(a)
    x = p[0]*math.cos(r) + p[1]*math.sin(r)     # KiCad: CCW on screen, y down
    y = -p[0]*math.sin(r) + p[1]*math.cos(r)
    return fx + x, fy + y

def main(path, ox=170.0, oy=40.0):
    s = open(path).read()
    match_end(s, s.index('(kicad_pcb'))
    ok = True
    # reference table: SparkFun cape footprint, converted to top-left origin (y from the top edge)
    def bbb(k, header):
        i = (k-1)//2
        x = ox + 20.32 + 2.54*i
        if header == 'P9':
            y = oy + (54.61-1.905 if k % 2 else 54.61-4.445)
        else:
            y = oy + (54.61-50.165 if k % 2 else 54.61-52.705)
        return x, y
    for ref, hdr in (('J1', 'P9'), ('J2', 'P8')):
        b, lib, layer, fp, pads = parse_fp(s, ref)
        assert lib == 'sadiy:BBB_Header_2x23_Male_Bottom', lib
        assert layer == 'B.Cu', layer
        assert len(pads) == 46
        err = max(math.dist(absxy(fp, pads[k]), bbb(k, hdr)) for k in pads)
        stale = re.findall(r'\(layer "F\.[A-Za-z]+"\)', b)
        print(ref, hdr, lib, layer, 'at', fp, 'max pad error %.4f mm' % err, 'front-layer leftovers:', len(stale))
        ok &= err < 0.001 and not stale
    # J3
    b, lib, layer, fp, pads = parse_fp(s, 'J3')
    a = {k: absxy(fp, pads[k]) for k in pads}
    p1, p2, p3 = a[1], a[2], a[3]
    print('J3', lib, layer, 'at', fp, 'pin1 %.3f,%.3f pin2 %.3f,%.3f pin3 %.3f,%.3f pin40 %.3f,%.3f' % (*p1, *p2, *p3, *a[40]))
    same_dir = abs(p2[0]-p1[0]) < 1e-6 and p2[1]-p1[1] < 0 and abs(p3[1]-p1[1]) < 1e-6 and p3[0]-p1[0] > 0
    print('J3 same direction as P8/P9 (pin 2 above pin 1, pins run to +x):', same_dir)
    ok &= same_dir
    p8 = [absxy(parse_fp(s, 'J2')[3], q) for q in parse_fp(s, 'J2')[4].values()]
    dmin = min(math.dist(a[k], q) for k in a for q in p8)
    col = abs(p1[0]-bbb(7, 'P8')[0]) < 1e-6
    print('J3 pad to nearest P8 pad: %.2f mm; J3 pin1 x == P8 pin 7 column (inside the Ethernet notch limit):' % dmin, col)
    ok &= col
    ys = [v[1] for v in a.values()]; xs = [v[0] for v in a.values()]
    print('J3 pads span x %.2f..%.2f, y %.2f..%.2f (cape x %.2f..%.2f, y %.2f..%.2f); shroud must stay right of the Ethernet notch (x > 20.32)' % (min(xs), max(xs), min(ys), max(ys), ox, ox+86.36, oy, oy+54.61))
    ok &= dmin > 3.0
    print('PLACEMENT OK' if ok else 'PLACEMENT FAILED')
    return 0 if ok else 1

if __name__ == '__main__':
    sys.exit(main(sys.argv[1]))
