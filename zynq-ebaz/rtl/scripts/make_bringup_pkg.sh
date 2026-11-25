#!/usr/bin/env bash
# Package everything the board needs to run sw/tools/pl_bringup.py: the bitstream, the load script and the
# pure-Python packages (sadiy for the contracts, sadiy_ebaz, regmap.toml). Output: zynq-ebaz/build/bringup-pkg/
# (git-ignored).
#   rtl/scripts/make_bringup_pkg.sh
#   scp -r zynq-ebaz/build/bringup-pkg root@<ip>:/tmp/
# On the board (after loading the bitstream, see sw/deploy/sadiy_pl_load.sh):
#   cd /tmp/bringup-pkg && ./run.sh [stages]          # default: the automatic stages; 'la' for the logic analyzer
#   ./sweepd.sh                                        # sweepd on the PL engine (needs register map 1.1)
set -eu
source "$(dirname "${BASH_SOURCE[0]}")/env.sh"
ROOT="$REPO_DIR"
OUT="$BUILD_DIR/bringup-pkg"
rm -rf "$OUT"; mkdir -p "$OUT"
cp -r "$ROOT/src/sadiy" "$OUT/sadiy"
cp -r "$EBAZ_DIR/sw/sadiy_ebaz" "$OUT/sadiy_ebaz"
cp "$EBAZ_DIR/sw/tools/pl_bringup.py" "$OUT/pl_bringup.py"
(cd "$ROOT" && PYTHONPATH=src python3 -m sadiy.buildinfo write "$OUT/BUILD_INFO") || echo "make_bringup_pkg: no BUILD_INFO (not a git checkout)"
cp "$EBAZ_DIR/rtl/regmap/regmap.toml" "$OUT/regmap.toml"
mkdir -p "$OUT/config" && cp "$ROOT/config/default.toml" "$OUT/config/default.toml"
find "$OUT" -name __pycache__ -type d -prune -exec rm -rf {} +
# Bitstream: BITSTREAM=<file>, else this checkout's build/fpga, else the same path in the sibling RTL worktree (the
# same list as sw/deploy/deploy_to_board.sh: the build output is git-ignored and only exists where Vivado ran).
BIT=""
for cand in "${BITSTREAM:-}" "$BUILD_DIR/fpga/ebaz_sadiy.bit.bin" "$ROOT/../SAdiy-rtl/zynq-ebaz/build/fpga/ebaz_sadiy.bit.bin"; do
  if [ -n "$cand" ] && [ -f "$cand" ]; then BIT="$cand"; break; fi
done
if [ -n "$BIT" ]; then
  cp "$BIT" "$OUT/ebaz_sadiy.bit.bin"; echo "make_bringup_pkg: bitstream $BIT (md5 $(md5sum "$BIT" | cut -d' ' -f1))"
else
  echo "make_bringup_pkg: WARNING no bitstream found (set BITSTREAM=<file> or build one); the package has none"
fi
[ -f "$EBAZ_DIR/sw/deploy/sadiy_pl_load.sh" ] && cp "$EBAZ_DIR/sw/deploy/sadiy_pl_load.sh" "$OUT/"
cat > "$OUT/run.sh" <<'EOS'
#!/bin/sh
# Run the PL bring-up test on the board. Load the bitstream first (./sadiy_pl_load.sh, see sw/deploy/README.md).
cd "$(dirname "$0")"
export PYTHONPATH="$PWD" SADIY_REGMAP_TOML="$PWD/regmap.toml"
exec python3 pl_bringup.py "$@"
EOS
cat > "$OUT/sweepd.sh" <<'EOS'
#!/bin/sh
# sweepd on the EBAZ4205 with the PL sweep engine (registers through /dev/mem, run as root).
#   ./sweepd.sh                 PL engine with the test ramp as detector ([platform] detector = "test"; no ADS1115 since map 2.0)
#   ./sweepd.sh -v              more log
#   ./sweepd.sh --bench-only    wiring tests instead of sweeps: Linux owns the pins (session L's PS backend)
# The PE4302 is written through the PCF8574 ([attenuator] pcf8574_address, default 0x27).
# GUI on the PC: python -m sadiy.ui.sa_gui --host <ip> --connect
cd "$(dirname "$0")"
export PYTHONPATH="$PWD" SADIY_REGMAP_TOML="$PWD/regmap.toml"
exec python3 -m sadiy.server.sweepd --platform ebaz --config "$PWD/config/default.toml" "$@"
EOS
chmod +x "$OUT/run.sh" "$OUT/sweepd.sh"
ls -l "$OUT"
