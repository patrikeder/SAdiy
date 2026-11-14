#!/usr/bin/env bash
# Usage: rtl/scripts/create_project.sh [--force]
# Creates the Vivado project EBAZ_SAdiy in $SADIY_VIVADO_DIR (default
# /media/patrik/Workspaces/HW/Vivado/EBAZ_SAdiy) with rtl/fpga/create_project.tcl.
# Refuses to overwrite an existing project unless --force is given.
# Environment: SADIY_VIVADO_DIR (project directory), SADIY_RTL_SRC_DIR (RTL directory, default rtl/src).
# Logs and journals: zynq-ebaz/build/fpga/logs/ (not in the source tree).
set -euo pipefail
. "$(dirname "${BASH_SOURCE[0]}")/env.sh"
vivado_env

force=noforce
case "${1:-}" in
  --force) force=force ;;
  "") ;;
  *) echo "usage: $0 [--force]" >&2; exit 2 ;;
esac

LOG_DIR="$BUILD_DIR/fpga/logs"
mkdir -p "$LOG_DIR"
cd "$LOG_DIR"      # vivado drops stray files (webtalk, .Xil) into its working directory
exec vivado -mode batch -nojournal -log "$LOG_DIR/create_project.log" \
  -source "$RTL_DIR/fpga/create_project.tcl" -tclargs "$force"
