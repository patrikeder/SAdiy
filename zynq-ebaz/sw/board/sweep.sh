#!/bin/sh
# Sweep with the PL engine (detector read in the PL). Run from ~/sadiy on the EBAZ4205.
#   ./sweep.sh [-v|-q ...]     then on the PC:  sh zynq-ebaz/sw/pc/gui.sh <this board's ip>
# Needs register map 1.1 or newer in the PL and the deployed software of the same map (checked). No bench mode in
# this run (the engine owns the pins): use ./bench.sh for wiring tests.
. "$(dirname "$0")/common.sh"
cd "$SADIY_HOME" || exit 1
banner
no_other_sweepd
./fpga.sh || exit 1
echo "starting sweepd with the PL engine (Ctrl-C stops it)"
as_root python3 -m sadiy.server.sweepd --platform ebaz ${SADIY_CONFIG:+--config "$SADIY_CONFIG"} "$@"
exit $?
