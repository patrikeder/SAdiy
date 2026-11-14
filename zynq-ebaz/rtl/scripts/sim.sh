#!/usr/bin/env bash
# Run the xsim testbenches of the RTL lane.
#   sim.sh              all rtl/sim/tb_*.sv
#   sim.sh tb_sweep ... only the named ones
#   SIM_GUI=1 sim.sh tb_sweep    open the waveform GUI for one testbench
# A testbench passes when its log contains "TB PASS" and neither "TB FAIL" nor an xsim error.
# Output: zynq-ebaz/build/sim/<tb>/ (xsim.log, work library). Exit code 0 only if all pass.
set -u
source "$(dirname "${BASH_SOURCE[0]}")/env.sh"
vivado_env

SIM_DIR="$RTL_DIR/sim"
SRCS=("$RTL_DIR"/src/*.sv)
[ -f "$RTL_DIR/regmap/axil_regs.sv" ] && SRCS+=("$RTL_DIR/regmap/axil_regs.sv")

if [ $# -gt 0 ]; then TBS=("$@"); else
  TBS=(); for f in "$SIM_DIR"/tb_*.sv; do [ -e "$f" ] && TBS+=("$(basename "$f" .sv)"); done
fi
[ ${#TBS[@]} -eq 0 ] && { echo "no testbenches found in $SIM_DIR"; exit 1; }

fail=0
for tb in "${TBS[@]}"; do
  run="$BUILD_DIR/sim/$tb"
  rm -rf "$run"; mkdir -p "$run"
  ln -sfn "$SIM_DIR/vectors" "$run/vectors"          # testbenches read "vectors/<file>.hex"
  (
    cd "$run" || exit 1
    xvlog -sv -nolog "${SRCS[@]}" "$SIM_DIR/$tb.sv" > compile.log 2>&1 || { echo "compile failed"; exit 2; }
    xelab -nolog -debug typical -timescale 1ns/1ps "$tb" -s "${tb}_sim" > elab.log 2>&1 || { echo "elaboration failed"; exit 3; }
    if [ "${SIM_GUI:-0}" = 1 ]; then xsim "${tb}_sim" -gui; exit 0; fi
    xsim "${tb}_sim" -nolog -runall > xsim.log 2>&1
  )
  rc=$?
  log="$run/xsim.log"
  if [ $rc -eq 0 ] && grep -q "TB PASS" "$log" && ! grep -Eq "TB FAIL|^(ERROR|FATAL)" "$log"; then
    echo "PASS  $tb"
  else
    echo "FAIL  $tb  (see $run)"
    for l in compile.log elab.log xsim.log; do
      [ -f "$run/$l" ] && grep -E "TB FAIL|ERROR|FATAL|failed" "$run/$l" | head -10
    done
    fail=1
  fi
done
exit $fail
