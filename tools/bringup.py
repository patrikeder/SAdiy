#!/usr/bin/env python3
"""Bring-up helpers. Run from the project root:  PYTHONPATH=src python tools/bringup.py <command>

  pe4302-pattern --db 10 [--from-db 15.5] [--csv f]
                           line levels V1..V6 and the write order for an attenuator change, with the
                           attenuation after every write. The lowest value during the change must not
                           drop below the lower of old and new. Compare with a logic analyzer capture.
  pe4302-walk --gpio 30,60,31,50,48,51 [--active-low] [--dry-run]
                           run ON THE SBC: switches one PE4302 input at a time so you can identify the
                           weight of V1..V6 and the polarity with the detector and a DMM
  adf4351-pattern --word 0x00580005 [--word ...]
                           SPI frame for ADF4351 register words (MSB first, 32 clocks each)
  pll --mhz 110.7          divider / INT / FRAC / MOD and the real output frequency
  sim-sweep                one simulated sweep, prints the strongest points
"""
import argparse

from sadiy import config, patterns
from sadiy.bringup import walk_lines
from sadiy.core.freqplan import build_sweep, plan_pll
from sadiy.hal.fake import FakeGpio, PinLog
from sadiy.server.sweepd import Sweepd, build_sim_engine


def cmd_pe4302(args):
    cfg = config.load()["attenuator"]
    p = patterns.pe4302_parallel(args.db, args.from_db, cfg["weights_db"], cfg["active_high"])
    print("\n".join(patterns.describe(p)))
    if args.csv:
        with open(args.csv, "w") as fh:
            fh.write(patterns.to_csv(p))
        print(f"wrote {args.csv}")


def cmd_walk(args):
    numbers = [int(x) for x in args.gpio.split(",")]
    active_high = not args.active_low
    if args.dry_run:
        log = PinLog()
        lines = [FakeGpio(f"V{i + 1}", log) for i in range(len(numbers))]
        walk_lines(lines, active_high, ask=lambda m: "")
        return
    from sadiy.hal.linux import SysfsGpio

    # start with every stage switched in so the outputs never glitch to minimum attenuation
    safe = 1 if active_high else 0
    lines = [SysfsGpio(n, initial=safe) for n in numbers]
    print("Keep the RF level at the module input below -20 dBm while walking the lines.")
    walk_lines(lines, active_high)


def cmd_adf(args):
    words = [int(w, 0) for w in args.word]
    print("\n".join(patterns.describe(patterns.adf4351_words(words))))


def cmd_pll(args):
    cfg = config.load()
    p = plan_pll(args.mhz * 1e6, cfg["synth"]["pfd_hz"])
    print(p)
    print(f"error: {p.f_actual_hz - p.f_out_hz:+.1f} Hz")


def cmd_sim(args):
    cfg = config.load()
    d = Sweepd(cfg, build_sim_engine(cfg))
    pts = build_sweep(60e6, 140e6, 401, cfg["rf"]["if_hz"], cfg["rf"]["injection"], cfg["synth"]["pfd_hz"])
    p = d.engine.run(pts, 0.0)
    for i in p.argsort()[::-1][:5]:
        print(f"{pts[i].f_rf_hz / 1e6:8.3f} MHz  {p[i]:7.2f} dBm")


def main():
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    sub = ap.add_subparsers(dest="cmd", required=True)
    a = sub.add_parser("pe4302-pattern")
    a.add_argument("--db", type=float, default=10.0)
    a.add_argument("--from-db", type=float, default=None, help="starting attenuation (default: all stages in)")
    a.add_argument("--csv")
    a.set_defaults(fn=cmd_pe4302)
    w = sub.add_parser("pe4302-walk")
    w.add_argument("--gpio", required=True, help="kernel GPIO numbers of V1..V6, comma separated")
    w.add_argument("--active-low", action="store_true")
    w.add_argument("--dry-run", action="store_true", help="no hardware, just print the procedure")
    w.set_defaults(fn=cmd_walk)
    f = sub.add_parser("adf4351-pattern")
    f.add_argument("--word", action="append", required=True, help="register word, e.g. 0x00580005")
    f.set_defaults(fn=cmd_adf)
    b = sub.add_parser("pll")
    b.add_argument("--mhz", type=float, required=True)
    b.set_defaults(fn=cmd_pll)
    c = sub.add_parser("sim-sweep")
    c.set_defaults(fn=cmd_sim)
    args = ap.parse_args()
    args.fn(args)


if __name__ == "__main__":
    main()
