#!/usr/bin/env bash
# Build the standalone DSP modules (rtl/dsp/) one by one, out of context, for resource and timing numbers.
#   synth_dsp.sh [top ...]        default: all. Output: zynq-ebaz/build/dsp/<top>_*.rpt and summary.txt
# Exit code 1 if a module fails or misses timing at 100 MHz.
set -u
source "$(dirname "${BASH_SOURCE[0]}")/env.sh"
vivado_env
OUT="$BUILD_DIR/dsp"
mkdir -p "$OUT"
TOPS=("$@"); [ ${#TOPS[@]} -eq 0 ] && TOPS=(fft_r2 fir_mac iq_power adc_ad9226 adc_spi_sar)
rc=0
for top in "${TOPS[@]}"; do
  ( cd "$OUT" && vivado -mode batch -nojournal -log "$top.log" -source "$RTL_DIR/dsp/synth_ooc.tcl" -tclargs "$top" "$OUT" >/dev/null 2>&1 )
  line=$(grep "^OOC_DONE" "$OUT/$top.log" | tail -1)
  if [ -z "$line" ]; then echo "FAIL  $top (see $OUT/$top.log)"; rc=1; continue; fi
  echo "${line#OOC_DONE }"
  wns=$(echo "$line" | awk '{print $4}')
  awk -v w="$wns" 'BEGIN{exit !(w < 0)}' && { echo "  timing not met"; rc=1; }
done
cat "$OUT"/*_summary.txt > "$OUT/summary.txt" 2>/dev/null
exit $rc
