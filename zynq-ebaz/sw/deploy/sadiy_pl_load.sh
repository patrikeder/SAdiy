#!/bin/sh
# Load the SAdiy PL engine at runtime and read its ID register. Runs ON the EBAZ as root.
#   sadiy_pl_load.sh [path/to/ebaz_sadiy.bit.bin]   default: next to this script
# No UIO: software reaches the core through /dev/mem at 0x43C00000 (sadiy_ebaz/devmem.py) and polls for done.
# The rootfs may be read-only, so nothing is copied to /lib/firmware: the firmware search path is pointed at
# the directory of the .bit.bin instead.
# UNTESTED on hardware (2026-11-14).
HERE=$(cd "$(dirname "$0")" && pwd)
FPGA=/sys/class/fpga_manager/fpga0
BASE=${SADIY_BASE:-0x43C00000}

BIN=${1:-$HERE/ebaz_sadiy.bit.bin}
[ -f "$BIN" ] || { echo "bitstream not found: $BIN" >&2; exit 1; }
[ -d "$FPGA" ] || { echo "no $FPGA (fpga_manager missing)" >&2; exit 1; }

# 1. bitstream via fpga_manager (full reconfiguration, flags = 0)
echo "$(dirname "$BIN")" > /sys/module/firmware_class/parameters/path
echo 0 > "$FPGA/flags"
echo "$(basename "$BIN")" > "$FPGA/firmware" || { echo "load failed" >&2; cat "$FPGA/state" >&2; exit 1; }
state=$(cat "$FPGA/state")
echo "fpga state: $state"
[ "$state" = "operating" ] || { echo "PL not operating" >&2; exit 1; }

# The Ethernet PHY clock and MII go through the PL: they were interrupted. Restart the link.
if [ -d /sys/class/net/eth0 ]; then
  ip link set eth0 down; sleep 1; ip link set eth0 up
  echo "eth0 restarted (re-run udhcpc if there is no address)"
fi

# 2. ID / VERSION through /dev/mem (only now: reading an unconfigured PL range would stall the CPU)
python3 - "$BASE" <<'PY'
import mmap, os, struct, sys
base = int(sys.argv[1], 0)
fd = os.open("/dev/mem", os.O_RDONLY | os.O_SYNC)
m = mmap.mmap(fd, 0x1000, mmap.MAP_SHARED, mmap.PROT_READ, offset=base)
ident, ver = struct.unpack_from("<II", m, 0)
print("ID      = 0x%08x %s" % (ident, "ok" if ident == 0x53410001 else "UNEXPECTED (want 0x53410001)"))
print("VERSION = 0x%08x" % ver)
PY
