#!/usr/bin/env python3
"""Adapter LCD, LEDs and keys test, run ON the EBAZ4205 (python3 + numpy are in the image).

  python3 ebaz_lcd_test.py info                 framebuffers, what fbtft found (read only)
  python3 ebaz_lcd_test.py bars [--fb /dev/fb0]  colour bars, a white 1-pixel border and corner markers:
                                                 red top-left, green top-right, blue bottom-left, yellow bottom-right
  python3 ebaz_lcd_test.py clear                 black screen
  python3 ebaz_lcd_test.py leds                  LED1..3 on one after the other (sysfs, needs root for /sys/class/leds)
  python3 ebaz_lcd_test.py keys                  print key events for 15 s (needs read access to /dev/input/event*)

The bars show three things at once. A shifted or cut-off picture (border missing on one side) means the panel
RAM offset is wrong for this module; wrong colours (red and blue swapped) mean the `bgr` property of the
device-tree node; a mirrored or rotated picture means `rotate`. Details: zynq-ebaz/docs/lcd-st7789.md.
Writing to /dev/fb0 needs root or the video group: use sudo.
"""
import argparse
import glob
import os
import struct
import sys
import time


def read(path):
    try:
        with open(path) as fh:
            return fh.read().strip()
    except OSError:
        return None


def fb_info(fb):
    n = os.path.basename(fb)
    base = f"/sys/class/graphics/{n}"
    w, h = (int(x) for x in (read(f"{base}/virtual_size") or "0,0").split(","))
    return {"name": read(f"{base}/name"), "w": w, "h": h, "bpp": int(read(f"{base}/bits_per_pixel") or 0),
            "stride": int(read(f"{base}/stride") or 0), "rotate": read(f"{base}/rotate")}


def cmd_info(_a):
    fbs = sorted(glob.glob("/sys/class/graphics/fb*"))
    print("framebuffers:", [os.path.basename(f) for f in fbs] or "none")
    for f in fbs:
        print(" ", os.path.basename(f), fb_info("/dev/" + os.path.basename(f)))
    for d in sorted(glob.glob("/sys/bus/spi/devices/*")):
        print("spi device:", os.path.basename(d), "driver:", os.path.basename(os.path.realpath(d + "/driver")) if os.path.exists(d + "/driver") else "none")
    print("leds:", [os.path.basename(x) for x in sorted(glob.glob("/sys/class/leds/*"))])
    print("input:", [(os.path.basename(x), read(x + "/device/name")) for x in sorted(glob.glob("/sys/class/input/event*"))])
    return 0


def rgb565(r, g, b):
    return ((r & 0xF8) << 8) | ((g & 0xFC) << 3) | (b >> 3)


def frame(info):
    import numpy as np
    w, h = info["w"], info["h"]
    if info["bpp"] != 16:
        raise SystemExit(f"framebuffer is {info['bpp']} bpp, this test draws RGB565 (16 bpp)")
    img = np.zeros((h, w), dtype=np.uint16)
    colours = [(255, 255, 255), (255, 255, 0), (0, 255, 255), (0, 255, 0), (255, 0, 255), (255, 0, 0), (0, 0, 255), (0, 0, 0)]
    bar = max(1, w // len(colours))
    for i, c in enumerate(colours):
        img[h // 4: 3 * h // 4, i * bar: (i + 1) * bar if i < len(colours) - 1 else w] = rgb565(*c)
    ramp = np.linspace(0, 255, w).astype(np.uint8)
    img[: h // 4] = np.array([rgb565(int(v), int(v), int(v)) for v in ramp], dtype=np.uint16)
    img[3 * h // 4:] = np.array([rgb565(int(v), 0, 255 - int(v)) for v in ramp], dtype=np.uint16)
    white = rgb565(255, 255, 255)
    img[0, :] = img[-1, :] = white
    img[:, 0] = img[:, -1] = white
    m = max(6, min(w, h) // 12)
    img[1:m, 1:m] = rgb565(255, 0, 0)
    img[1:m, w - m: w - 1] = rgb565(0, 255, 0)
    img[h - m: h - 1, 1:m] = rgb565(0, 0, 255)
    img[h - m: h - 1, w - m: w - 1] = rgb565(255, 255, 0)
    return img


def write_fb(fb, img, info):
    import numpy as np
    stride = info["stride"] or info["w"] * 2
    rows = bytearray(stride * info["h"])
    for y in range(info["h"]):
        rows[y * stride: y * stride + info["w"] * 2] = img[y].astype("<u2").tobytes()
    with open(fb, "wb", buffering=0) as fh:
        fh.write(rows)
    _ = np


def cmd_bars(a):
    info = fb_info(a.fb)
    print("drawing on", a.fb, info)
    write_fb(a.fb, frame(info), info)
    print("done: look at the panel (border on all four sides, corners red / green / blue / yellow)")
    return 0


def cmd_clear(a):
    import numpy as np
    info = fb_info(a.fb)
    write_fb(a.fb, np.zeros((info["h"], info["w"]), dtype=np.uint16), info)
    return 0


def cmd_leds(_a):
    leds = sorted(glob.glob("/sys/class/leds/adapter:led*"))
    if not leds:
        print("no adapter:led* in /sys/class/leds (device-tree gpio-leds node missing?)")
        return 1
    for led in leds:
        for v in ("0", "1", "0"):
            with open(led + "/brightness", "w") as fh:
                fh.write(v)
            print(os.path.basename(led), "brightness", v)
            time.sleep(0.6)
    print("polarity: if 'brightness 1' turned the LED OFF, change GPIO_ACTIVE_HIGH to GPIO_ACTIVE_LOW in the dtsi")
    return 0


def cmd_keys(_a):
    dev = next((x for x in sorted(glob.glob("/dev/input/event*")) if "keys" in (read("/sys/class/input/" + os.path.basename(x) + "/device/name") or "")), None)
    if dev is None:
        print("no gpio-keys input device found (try: info)")
        return 1
    print("reading", dev, "for 15 s: press KEY1..KEY5")
    end = time.time() + 15
    fmt = "llHHi"
    size = struct.calcsize(fmt)
    import select
    with open(dev, "rb", buffering=0) as fh:
        while time.time() < end:
            if select.select([fh], [], [], 0.5)[0]:
                _s, _u, typ, code, val = struct.unpack(fmt, fh.read(size))
                if typ == 1:
                    print(f"key code {code} {'pressed' if val else 'released'}")
    return 0


def main(argv=None):
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--fb", default="/dev/fb0")
    sub = ap.add_subparsers(dest="cmd", required=True)
    for name, fn in (("info", cmd_info), ("bars", cmd_bars), ("clear", cmd_clear), ("leds", cmd_leds), ("keys", cmd_keys)):
        sub.add_parser(name).set_defaults(fn=fn)
    a = ap.parse_args(argv)
    return a.fn(a)


if __name__ == "__main__":
    sys.exit(main())
