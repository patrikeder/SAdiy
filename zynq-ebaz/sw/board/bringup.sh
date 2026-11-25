#!/bin/sh
# The PL bring-up tests (tools/pl_bringup.py) from the deployed software, so there is one copy on the board.
#   ./bringup.sh                run the automatic stages (ident regs gen push owner ctrl lock adc if fe)
#   ./bringup.sh fe if          only these stages;  ./bringup.sh version   the bitstream's ID and VERSION only
#   ./bringup.sh la             the logic-analyzer stages;  ./bringup.sh --help   all stages and options
# Needs the bitstream loaded (./fpga.sh). Run from ~/sadiy.
. "$(dirname "$0")/common.sh"
cd "$SADIY_HOME" || exit 1
banner
as_root python3 "$SADIY_HOME/zynq-ebaz/sw/tools/pl_bringup.py" "$@"
