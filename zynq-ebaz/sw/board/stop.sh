#!/bin/sh
# Stop a running sweepd (SIGTERM: it puts the lines back to the safe state before it exits). Run from ~/sadiy.
. "$(dirname "$0")/common.sh"
pids=$(sweepd_pids)
[ -n "$pids" ] || { echo "sweepd is not running"; exit 0; }
for p in $pids; do as_root kill -TERM "$p" && echo "stopped sweepd pid $p"; done
sleep 1
[ -z "$(sweepd_pids)" ] || echo "still running: try again, or: sudo kill -KILL <pid> then ./fpga.sh --force" >&2
exit 0
