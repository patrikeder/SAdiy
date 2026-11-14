#!/bin/sh
# Copy the SAdiy Python code to the EBAZ (it is NOT part of the rootfs image).
#   sw/deploy/deploy_to_board.sh <ebaz-ip> [user]        run from anywhere inside the checkout
# Layout on the board (mirrors the repo, so sadiy_ebaz finds rtl/regmap/regmap.toml by itself):
#   /opt/sadiy/src/sadiy/               the BBB code base (hal, drivers, core, server, ui/cli_client)
#   /opt/sadiy/zynq-ebaz/sw/sadiy_ebaz/ EBAZ backends and the PL register layer
#   /opt/sadiy/zynq-ebaz/rtl/regmap/regmap.toml
#   /opt/sadiy/config/                  default.toml
# Run on the board with:  PYTHONPATH=/opt/sadiy/src:/opt/sadiy/zynq-ebaz/sw python3 -m sadiy.server.sweepd ...
# Needs a writable /opt on the board (see README: mount -o remount,rw / if the rootfs is read-only).
# The Qt GUI is left out: it runs on the PC. Python modules on the board: pyzmq, numpy, spidev, tomllib (in the image).
set -e
IP=${1:?usage: deploy_to_board.sh <ebaz-ip> [user]}
USER_=${2:-root}
ROOT=$(cd "$(dirname "$0")/../../.." && pwd)
cd "$ROOT"
paths="src/sadiy config/default.toml"
[ -d zynq-ebaz/sw/sadiy_ebaz ] && paths="$paths zynq-ebaz/sw/sadiy_ebaz"
[ -f zynq-ebaz/rtl/regmap/regmap.toml ] && paths="$paths zynq-ebaz/rtl/regmap/regmap.toml"
[ -d zynq-ebaz/sw/config ] && paths="$paths zynq-ebaz/sw/config"
echo "deploying: $paths"
ex=""
for f in src/sadiy/ui/*.py; do
  case $(basename "$f") in __init__.py|cli_client.py|sweep_client.py) ;; *) ex="$ex --exclude=$f" ;; esac
done
tar -czf - --exclude='__pycache__' --exclude='*.pyc' $ex $paths \
  | ssh "$USER_@$IP" 'mkdir -p /opt/sadiy && cd /opt/sadiy && tar -xzf - && echo "unpacked to /opt/sadiy" && ls /opt/sadiy'
echo "on the board: export PYTHONPATH=/opt/sadiy/src:/opt/sadiy/zynq-ebaz/sw"
