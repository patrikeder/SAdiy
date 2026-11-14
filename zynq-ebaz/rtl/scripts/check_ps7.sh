#!/usr/bin/env bash
# Usage: rtl/scripts/check_ps7.sh [reference_dir]
# Diffs the PS7 user settings of rtl/fpga/ps7_config.tcl against session L's Phase 1 design
# (ps7_base.tcl + the overrides in phase1.tcl, default: zynq-ebaz/rtl/vivado of this worktree,
# else /media/patrik/Workspaces/uC/SAdiy-linux/...). Prints every differing CONFIG key.
# Exit 0 identical, 1 differences, 2 reference not reachable.
set -euo pipefail
. "$(dirname "${BASH_SOURCE[0]}")/env.sh"
exec "${PYTHON:-python3}" -I "$RTL_DIR/fpga/check_ps7.py" "$@"
