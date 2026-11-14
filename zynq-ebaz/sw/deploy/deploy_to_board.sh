#!/bin/sh
# Copy the SAdiy Python code to the EBAZ (it is NOT part of the rootfs image).
#   sw/deploy/deploy_to_board.sh <ebaz-ip> [user]        run from anywhere inside the checkout (default user: petalinux)
# Layout on the board, under ~/sadiy of the login user (mirrors the repo, so sadiy_ebaz finds regmap.toml itself):
#   ~/sadiy/src/sadiy/               the BBB code base (hal, drivers, core, server, ui/cli_client)
#   ~/sadiy/zynq-ebaz/sw/sadiy_ebaz/ EBAZ backends and the PL register layer
#   ~/sadiy/zynq-ebaz/rtl/regmap/regmap.toml
#   ~/sadiy/config/                  default.toml
#   ~/sadiy/tools/bringup.py         gpio-map, synth-ce, pe4302-walk ... (run from ~/sadiy)
#   ~/sadiy/zynq-ebaz/sw/tools/      pl_bringup.py, ebaz_lcd_test.py, ebaz_s4_*.sh, ebaz_baseline.sh
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
echo "deploying: $paths"
ex=""
for f in src/sadiy/ui/*.py; do
  case $(basename "$f") in __init__.py|cli_client.py|sweep_client.py) ;; *) ex="$ex --exclude=$f" ;; esac
done
tar -czf - --exclude='__pycache__' --exclude='*.pyc' $ex $paths \
  | ssh "$USER_@$IP" 'mkdir -p ~/sadiy && cd ~/sadiy && tar -xzf - && echo "unpacked to ~/sadiy" && ls ~/sadiy'
echo "on the board: export PYTHONPATH=~/sadiy/src:~/sadiy/zynq-ebaz/sw"
