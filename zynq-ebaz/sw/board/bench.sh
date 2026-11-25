#!/bin/sh
# Bench mode: wiring and part tests from the GUI's Pins and Synth tabs (PE4302 via the PCF8574, ADF4351, lock detect).
# Linux owns the pins; the sweep engine is not used. No sweeping in this mode. Run from ~/sadiy on the EBAZ4205.
#   ./bench.sh [-v|-q ...]     then on the PC:  sh zynq-ebaz/sw/pc/gui.sh <this board's ip>
# Checks the PL first (bitstream loaded, pins not held by an engine run), stops with a message when it is not.
. "$(dirname "$0")/common.sh"
cd "$SADIY_HOME" || exit 1
banner
no_other_sweepd
./fpga.sh || exit 1
echo "starting sweepd in bench mode (Ctrl-C stops it; the lines go back to safe)"
as_root python3 -m sadiy.server.sweepd --platform ebaz --bench-only ${SADIY_CONFIG:+--config "$SADIY_CONFIG"} "$@"
exit $?
