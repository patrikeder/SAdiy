#!/bin/sh
# Copy the SAdiy Python code to the EBAZ (it is NOT part of the rootfs image).
#   sw/deploy/deploy_to_board.sh <ebaz-ip> [user]        run from anywhere inside the checkout (default user: petalinux)
# Layout on the board, under ~/sadiy of the login user (mirrors the repo, so sadiy_ebaz finds regmap.toml itself):
#   ~/sadiy/src/sadiy/               the BBB code base (hal, drivers, core, server, ui/cli_client)
#   ~/sadiy/zynq-ebaz/sw/sadiy_ebaz/ EBAZ backends and the PL register layer
#   ~/sadiy/zynq-ebaz/rtl/regmap/regmap.toml
#   ~/sadiy/config/                  default.toml
#   ~/sadiy/BUILD_INFO               commit, branch, time of this copy (every program prints it when it starts)
#   ~/sadiy/tools/bringup.py         gpio-map, synth-ce, pe4302-walk ... (run from ~/sadiy)
#   ~/sadiy/zynq-ebaz/sw/tools/      pl_bringup.py, ebaz_pl_probe.py, ebaz_lcd_test.py, ebaz_s4_*.sh, ebaz_baseline.sh
#   ~/sadiy/{fpga,bench,sweep,sim,status,stop}.sh   the day-to-day scripts (from zynq-ebaz/sw/board/), run from ~/sadiy
#   ~/sadiy/fpga/                    ebaz_sadiy.bit.bin (the engine bitstream, see BITSTREAM below) and sadiy_pl_load.sh
# BITSTREAM=<file> picks the bitstream; default: zynq-ebaz/build/fpga/ebaz_sadiy.bit.bin of this checkout, else the one of
# the RTL worktree next to it (../SAdiy-rtl). Without any, the code is deployed and ./fpga.sh says what is missing.
# Run on the board with:  PYTHONPATH=~/sadiy/src:~/sadiy/zynq-ebaz/sw python3 -m sadiy.server.sweepd ...
# (root is locked in the image, work as petalinux and use sudo for /dev/mem, GPIO and fpga_manager access).
# Needs a writable home on the board (see README: sudo mount -o remount,rw / if the rootfs is read-only).
# The Qt GUI is left out: it runs on the PC. Python modules on the board: pyzmq, numpy, spidev, tomllib (in the image).
set -e
IP=${1:?usage: deploy_to_board.sh <ebaz-ip> [user]}
USER_=${2:-petalinux}
ROOT=$(cd "$(dirname "$0")/../../.." && pwd)
cd "$ROOT"
paths="src/sadiy config/default.toml"
[ -d zynq-ebaz/sw/sadiy_ebaz ] && paths="$paths zynq-ebaz/sw/sadiy_ebaz"
[ -f zynq-ebaz/rtl/regmap/regmap.toml ] && paths="$paths zynq-ebaz/rtl/regmap/regmap.toml"
[ -d zynq-ebaz/sw/config ] && paths="$paths zynq-ebaz/sw/config"
[ -f tools/bringup.py ] && paths="$paths tools/bringup.py"
[ -d zynq-ebaz/sw/tools ] && paths="$paths zynq-ebaz/sw/tools"
PYTHONPATH=src python3 -m sadiy.buildinfo write BUILD_INFO || rm -f BUILD_INFO     # which commit the board gets (BUILD_INFO is git-ignored)
[ -f BUILD_INFO ] && paths="$paths BUILD_INFO"
STAGE=$(mktemp -d)
trap 'rm -rf "$STAGE" BUILD_INFO' EXIT
if [ -d zynq-ebaz/sw/board ]; then cp zynq-ebaz/sw/board/*.sh "$STAGE"/ && chmod +x "$STAGE"/*.sh; fi
mkdir -p "$STAGE/fpga"
[ -f zynq-ebaz/sw/deploy/sadiy_pl_load.sh ] && cp zynq-ebaz/sw/deploy/sadiy_pl_load.sh "$STAGE/fpga/"
bit=""
for c in "${BITSTREAM:-}" zynq-ebaz/build/fpga/ebaz_sadiy.bit.bin ../SAdiy-rtl/zynq-ebaz/build/fpga/ebaz_sadiy.bit.bin; do
  if [ -n "$c" ] && [ -f "$c" ]; then bit=$c; break; fi
done
if [ -n "$bit" ]; then
  cp "$bit" "$STAGE/fpga/ebaz_sadiy.bit.bin"
  echo "bitstream: $bit ($(date -r "$bit" '+%Y-%m-%d %H:%M'), sha256 $(sha256sum "$bit" | cut -c1-12))"
else
  echo "bitstream: none found (set BITSTREAM=<ebaz_sadiy.bit.bin>); the board keeps the one it has, ./fpga.sh will tell"
fi
echo "deploying: $paths"
ex=""
for f in src/sadiy/ui/*.py; do
  case $(basename "$f") in __init__.py|cli_client.py|sweep_client.py) ;; *) ex="$ex --exclude=$f" ;; esac
done
tar -czf - --exclude='__pycache__' --exclude='*.pyc' $ex $paths -C "$STAGE" . \
  | ssh "$USER_@$IP" 'mkdir -p ~/sadiy && cd ~/sadiy && tar -xzf - && printf "export PYTHONPATH=\$HOME/sadiy/src:\$HOME/sadiy/zynq-ebaz/sw\n" > env.sh && echo "unpacked to ~/sadiy" && ls ~/sadiy'
echo "on the board, from ~/sadiy: ./status.sh | ./fpga.sh | ./bench.sh | ./sweep.sh | ./sim.sh | ./stop.sh   (. ~/sadiy/env.sh sets PYTHONPATH for python -m ...)"
