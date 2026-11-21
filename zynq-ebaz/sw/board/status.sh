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
echo "--- software copies under $HOME (only the one marked * is used by these scripts)"
find "$HOME" -maxdepth 5 -path '*/sadiy/server/sweepd.py' 2>/dev/null | while read -r f; do
    code=${f%/sadiy/server/sweepd.py}                          # the folder that holds sadiy/
    info=$(cat "$code/BUILD_INFO" 2>/dev/null | head -1)
    [ -z "$info" ] && [ "$(basename "$code")" = src ] && info=$(cat "$code/../BUILD_INFO" 2>/dev/null | head -1)
    commit=$(echo "$info" | sed -n 's/.*"commit": "\([^"]*\)".*/\1/p'); built=$(echo "$info" | sed -n 's/.*"built": "\([^"]*\)".*/\1/p')
    mark=" "; [ "$code" = "$SADIY_HOME/src" ] && mark="*"
    if [ -n "$commit" ]; then what="commit $commit, built $built"; else what="no BUILD_INFO (made before build info, or copied by hand)"; fi
    echo "$mark $code: $what"
done
echo "--- sweepd"
pids=$(sweepd_pids)
if [ -n "$pids" ]; then for p in $pids; do echo "running: pid $p: $(tr '\0' ' ' </proc/$p/cmdline | sed 's/.*sadiy.server.sweepd//')"; done; else echo "not running"; fi
echo "--- network"
for n in /sys/class/net/*; do i=$(basename "$n"); [ "$i" = lo ] || echo "$i: $(ip -4 -o addr show "$i" 2>/dev/null | awk '{print $4}' | tr '\n' ' ')"; done
