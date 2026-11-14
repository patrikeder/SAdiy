#!/usr/bin/env bash
# Usage: rtl/scripts/build_bit.sh
# Creates the Vivado project if it is missing, then runs rtl/fpga/build.tcl (synthesis,
# implementation, bitstream, XSA, bit.bin) and prints summary.txt. Exit code = the build's:
# non-zero on a failed run, WNS < 0, WHS < 0 or a missing bitstream.
# Environment: SADIY_VIVADO_DIR (project), SADIY_FPGA_OUT (default zynq-ebaz/build/fpga),
#              SADIY_RTL_SRC_DIR (RTL directory used when the project has to be created).
# Logs: <SADIY_FPGA_OUT>/logs/.
set -euo pipefail
. "$(dirname "${BASH_SOURCE[0]}")/env.sh"
vivado_env

: "${SADIY_FPGA_OUT:=$BUILD_DIR/fpga}"
export SADIY_FPGA_OUT
LOG_DIR="$SADIY_FPGA_OUT/logs"
mkdir -p "$LOG_DIR"
cd "$LOG_DIR"

if [ ! -f "$SADIY_VIVADO_DIR/EBAZ_SAdiy.xpr" ]; then
  echo "build_bit: project missing, creating it in $SADIY_VIVADO_DIR"
  vivado -mode batch -nojournal -log "$LOG_DIR/create_project.log" \
    -source "$RTL_DIR/fpga/create_project.tcl" -tclargs noforce
fi

rc=0
vivado -mode batch -nojournal -log "$LOG_DIR/build.log" -source "$RTL_DIR/fpga/build.tcl" || rc=$?
echo
if [ -f "$SADIY_FPGA_OUT/summary.txt" ]; then cat "$SADIY_FPGA_OUT/summary.txt"; fi
if [ "$rc" -ne 0 ]; then echo "build_bit: FAILED (exit $rc), see $LOG_DIR/build.log" >&2; fi
exit "$rc"
