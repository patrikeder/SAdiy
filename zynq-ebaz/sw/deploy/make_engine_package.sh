#!/bin/sh
# Collect what the board needs for the runtime load into zynq-ebaz/build/engine-pkg/ (git-ignored):
# the bit.bin from the RTL build and the load script.
#   scp -r build/engine-pkg root@<ip>:/tmp/      (or any writable place)
set -e
cd "$(dirname "$0")/../.."
BIN=${1:-build/fpga/ebaz_sadiy.bit.bin}
[ -f "$BIN" ] || { echo "missing $BIN (build with rtl/scripts/build_bit.sh in the RTL worktree, or pass a path)" >&2; exit 1; }
OUT=build/engine-pkg
rm -rf "$OUT"; mkdir -p "$OUT"
cp "$BIN" "$OUT/ebaz_sadiy.bit.bin"
cp sw/deploy/sadiy_pl_load.sh "$OUT/"
chmod +x "$OUT/sadiy_pl_load.sh"
ls -l "$OUT"
