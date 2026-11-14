#!/usr/bin/env python3
"""Compare our PS7 user settings with session L's Phase 1 design.

Our side: ps7_config.tcl (ps7_base + ps7_overrides). Reference side: ps7_base.tcl plus the
`set_property -dict [list CONFIG.* ...] $ps` override block of phase1.tcl, in the same
directory (session L's rtl/vivado/). The boot image (FSBL, device tree) is built from the
Phase 1 design and our bitstream is loaded on top at runtime, so the two must be identical.

Usage: python3 -I check_ps7.py [reference_dir]
Exit: 0 identical, 1 differences (every differing key is printed), 2 reference not reachable.
Standard library only.
"""
import re
import sys
from pathlib import Path

HERE = Path(__file__).resolve().parent
DEFAULT_REF = [
    HERE.parents[1] / "rtl" / "vivado",   # same worktree, after a merge of session L's work
    Path("/media/patrik/Workspaces/uC/SAdiy-linux/zynq-ebaz/rtl/vivado"),
]
KV = re.compile(r"CONFIG\.(\w+)\s+\{([^}]*)\}")


def dict_block(text, name):
    m = re.search(r"set\s+%s\s+\[dict create\s*\\(.*?)\n\]" % re.escape(name), text, re.S)
    return dict(KV.findall(m.group(1))) if m else {}


def main(argv):
    refs = [Path(argv[0])] if argv else DEFAULT_REF
    ref = next((r for r in refs if (r / "ps7_base.tcl").is_file() and (r / "phase1.tcl").is_file()), None)
    if ref is None:
        print("check_ps7: reference (ps7_base.tcl + phase1.tcl) not reachable, nothing compared")
        return 2
    ours_t = (HERE / "ps7_config.tcl").read_text()
    ours = dict_block(ours_t, "ps7_base")
    ours.update(dict_block(ours_t, "ps7_overrides"))
    theirs = dict_block((ref / "ps7_base.tcl").read_text(), "ps7_base")
    p1 = (ref / "phase1.tcl").read_text()
    m = re.search(r"set_property -dict \[list(.*?)\]\s*\$ps\b", p1, re.S)
    theirs.update(dict(KV.findall(m.group(1))) if m else {})
    print(f"check_ps7: reference {ref}: {len(theirs)} keys, ours {len(ours)} keys")
    bad = 0
    for k in sorted(set(ours) | set(theirs)):
        a, b = ours.get(k), theirs.get(k)
        if a != b:
            bad += 1
            print(f"  DIFF CONFIG.{k}: ours={a!r} phase1={b!r}")
    print("check_ps7: " + ("IDENTICAL" if not bad else f"{bad} DIFFERENCES (report them, do not accept silently)"))
    return 1 if bad else 0


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))
