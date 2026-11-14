#!/usr/bin/env bash
# Everything that can be checked without hardware, in this order:
#   1. generated files are current (register map outputs, golden vectors)
#   2. pytest (whole repo: BBB code, sadiy_ebaz contracts and model, generator tests)
#   3. verilator lint of the engine (skipped with a note if verilator is not installed)
#   4. all xsim testbenches
# Usage: rtl/scripts/test.sh [--no-sim]     Exit code 0 only if every step passed.
set -u
source "$(dirname "${BASH_SOURCE[0]}")/env.sh"
rc=0
step() { echo; echo "=== $1 ==="; }

step "generated files current (gen.sh --check)"
bash "$SCRIPTS_DIR/gen.sh" --check || { echo "FAIL: run rtl/scripts/gen.sh and review the diff"; rc=1; }

step "pytest"
(cd "$REPO_DIR" && "$PYTHON" -m pytest -q -p no:cacheprovider) || rc=1

step "verilator lint"
if command -v verilator >/dev/null 2>&1; then
  verilator --lint-only -Wall -Wno-SYMRSVDWORD -Wno-DECLFILENAME -Wno-UNUSEDSIGNAL \
    --top-module sadiy_top "$RTL_DIR"/src/*.sv "$RTL_DIR/regmap/axil_regs.sv" || rc=1
else
  echo "verilator not installed: skipped"
fi

if [ "${1:-}" != "--no-sim" ]; then
  step "xsim testbenches"
  bash "$SCRIPTS_DIR/sim.sh" || rc=1
fi

echo
[ $rc -eq 0 ] && echo "ALL PASSED" || echo "FAILED"
exit $rc
