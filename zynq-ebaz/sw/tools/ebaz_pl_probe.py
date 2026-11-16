#!/usr/bin/env python3
"""What is in the PL? Runs ON the EBAZ4205 (as root: /dev/mem). Read-only; used by ~/sadiy/fpga.sh, status.sh, bench.sh, sweep.sh.

  python3 ebaz_pl_probe.py [--base 0x43C00000] [--quiet]

Prints the FPGA manager state, the sweep core's ID and register map version against the one the deployed software
expects (regmap.toml) and who owns the pins. Registers are read only when the FPGA manager says "operating":
an AXI read of an unconfigured PL range stalls the CPU.

Exit code: 0 core found, map equals the software's | 1 core found, map differs | 2 PL operating but no sweep core
           3 PL not configured (or no FPGA manager) | 4 registers not readable (not root? no /dev/mem)
"""
from __future__ import annotations

import argparse
import sys
from pathlib import Path
from typing import List, Optional, Sequence

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))        # zynq-ebaz/sw (or PYTHONPATH on the board)

from sadiy_ebaz import regmap_toml  # noqa: E402
from sadiy_ebaz.devmem import DEFAULT_BASE, FPGA_STATE, DevMemRegs  # noqa: E402


def _ver(v: int) -> str:
    return f"{v >> 16}.{v & 0xFFFF}"


def probe(base: int = DEFAULT_BASE, state_path: Path = FPGA_STATE, mem_path: str = "/dev/mem",
          lines: Optional[List[str]] = None) -> int:
    out = lines if lines is not None else []
    try:
        state = Path(state_path).read_text().strip()
    except OSError:
        out.append("PL state: unknown (no FPGA manager: not on the board?)")
        return 3
    out.append(f"PL state: {state}")
    if state != "operating":
        out.append("the PL has no bitstream: run ./fpga.sh")
        return 3
    try:
        regs = DevMemRegs(base, path=mem_path)
    except (OSError, ValueError) as exc:
        out.append(f"cannot map the registers ({exc}): run as root")
        return 4
    try:
        ident = regs.read(regmap_toml.REGS["ID"].offset)
        if ident != regmap_toml.REGS["ID"].reset_value():
            out.append(f"no sweep core at 0x{base:X}: ID reads 0x{ident:08X}, want 0x{regmap_toml.REGS['ID'].reset_value():08X} "
                       "(another bitstream?): run ./fpga.sh --force")
            return 2
        version = regs.read(regmap_toml.REGS["VERSION"].offset)
        status = regs.read(regmap_toml.REGS["STATUS"].offset)
        owner = "the sweep engine" if regmap_toml.REGS["STATUS"].fields["pin_owner_act"].get(status) else "Linux (PS)"
    finally:
        regs.close()
    expect = regmap_toml.map_version()
    out.append(f"core: ID ok, register map {_ver(version)}; software expects {_ver(expect)}")
    out.append(f"pins: owned by {owner}")
    if version != expect:
        out.append("the bitstream and the deployed software disagree: run ./fpga.sh --force (and deploy the matching bitstream)")
        return 1
    return 0


def main(argv: Optional[Sequence[str]] = None) -> int:
    ap = argparse.ArgumentParser(description=__doc__.split("\n\n")[0])
    ap.add_argument("--base", type=lambda x: int(x, 0), default=DEFAULT_BASE)
    ap.add_argument("--state", default=str(FPGA_STATE), help=argparse.SUPPRESS)      # tests
    ap.add_argument("--mem", default="/dev/mem", help=argparse.SUPPRESS)             # tests
    ap.add_argument("--quiet", action="store_true", help="exit code only")
    args = ap.parse_args(argv)
    lines: List[str] = []
    rc = probe(args.base, Path(args.state), args.mem, lines)
    if not args.quiet:
        print("\n".join(lines))
    return rc


if __name__ == "__main__":
    sys.exit(main())
