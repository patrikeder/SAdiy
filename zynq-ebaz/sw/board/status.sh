#!/bin/sh
# One look at the board: software build, PL, device nodes, running sweepd, network. Read-only. Run from ~/sadiy.
. "$(dirname "$0")/common.sh"
cd "$SADIY_HOME" || exit 1
banner
echo "--- PL"
probe || true
echo "--- devices"
for f in /dev/spidev0.0 /dev/i2c-0 /dev/mem; do [ -e "$f" ] && echo "ok       $f" || echo "MISSING  $f"; done
for g in /sys/class/gpio/gpiochip*; do [ -d "$g" ] && echo "gpiochip $(basename "$g"): $(cat "$g/ngpio" 2>/dev/null) lines, base $(cat "$g/base" 2>/dev/null)"; done
echo "--- sweepd"
pids=$(sweepd_pids)
if [ -n "$pids" ]; then for p in $pids; do echo "running: pid $p: $(tr '\0' ' ' </proc/$p/cmdline | sed 's/.*sadiy.server.sweepd//')"; done; else echo "not running"; fi
echo "--- network"
for n in /sys/class/net/*; do i=$(basename "$n"); [ "$i" = lo ] || echo "$i: $(ip -4 -o addr show "$i" 2>/dev/null | awk '{print $4}' | tr '\n' ' ')"; done
