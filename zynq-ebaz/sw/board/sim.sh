#!/bin/sh
# Simulated chain on the EBAZ4205 map: no hardware, no root, no bitstream. For trying the GUI against the board's network.
. "$(dirname "$0")/common.sh"
cd "$SADIY_HOME" || exit 1
banner
no_other_sweepd
exec python3 -m sadiy.server.sweepd --sim --platform ebaz ${SADIY_CONFIG:+--config "$SADIY_CONFIG"} "$@"
