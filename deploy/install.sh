#!/bin/sh
# First install of SAdiy on a BeagleBone Black. Run as root from the unpacked package:
#   sudo ./install.sh [--enable]
# To update an existing installation use sadiy-update.sh, which can roll back.
# Installs nothing from the network. Missing Python packages are reported, not installed.
# DESTDIR=/some/dir only stages the files (used for testing off the board).
set -eu
HERE=$(cd "$(dirname "$0")" && pwd)
D=${DESTDIR:-}
ENABLE=0
[ "${1:-}" = "--enable" ] && ENABLE=1

if [ -z "$D" ] && [ "$(id -u)" -ne 0 ]; then echo "run as root: sudo $0" >&2; exit 1; fi

# 1. dependencies (report only)
missing=""
python3 -c "import numpy" 2>/dev/null || missing="$missing python3-numpy"
python3 -c "import zmq" 2>/dev/null || missing="$missing python3-zmq"
python3 -c "import spidev" 2>/dev/null || missing="$missing python3-spidev"
python3 -c "import tomllib" 2>/dev/null || python3 -c "import tomli" 2>/dev/null || missing="$missing python3-tomli"
command -v i2cdetect >/dev/null 2>&1 || missing="$missing i2c-tools"
if [ -n "$missing" ]; then
  echo "Missing packages:$missing"
  echo "Install with:  sudo apt install$missing   (then run this script again)"
  [ -z "$D" ] && exit 2
fi

# 2. files (keep existing calibration data and local config)
mkdir -p "$D/opt/sadiy" "$D/etc/sadiy" "$D/etc/systemd/system"
rm -rf "$D/opt/sadiy/src"
cp -r "$HERE/opt/sadiy/src" "$D/opt/sadiy/src"
for d in config deploy tools docs hw; do
  mkdir -p "$D/opt/sadiy/$d"; cp -r "$HERE/opt/sadiy/$d/." "$D/opt/sadiy/$d/"
done
mkdir -p "$D/opt/sadiy/cal"
[ -e "$D/etc/sadiy/local.toml" ] || cp "$HERE/etc/sadiy/local.toml" "$D/etc/sadiy/local.toml"
cp "$HERE/etc/systemd/system/sweepd.service" "$HERE/etc/systemd/system/sadiy-pinmux.service" "$D/etc/systemd/system/"
chmod 755 "$D/opt/sadiy/tools/"*.py "$D/opt/sadiy/deploy/"*.sh

# 3. smoke test (pure Python, touches no hardware)
PYTHONPATH="$D/opt/sadiy/src" python3 "$D/opt/sadiy/tools/bringup.py" pll --mhz 110.7

if [ -z "$D" ]; then
  systemctl daemon-reload
  if [ "$ENABLE" -eq 1 ]; then systemctl enable --now sadiy-pinmux sweepd; else
    echo "Services installed but NOT enabled. Next: the steps in /opt/sadiy/docs/bbb-setup.md from step 4."
  fi
fi
echo "Done."
