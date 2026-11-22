#!/bin/sh
# Pass/fail self-test of the PL sweep path with the engine's test ramp (no RF, no ADC, no ADF4351 writes).
# Run from ~/sadiy on the EBAZ4205:   ./selftest.sh [--sweeps 5] [--points 401 | --fill] [--n-avg 4] [--base 10000] [--wrap] [-v]
# Exit code 0 = PASS, 1 = FAIL, 2 = could not run. Needs sweepd stopped (the engine takes the PE4302 pins for the run and
# gives them back). Specification and criteria: zynq-ebaz/docs/selftest.md. To look at the ramp in the GUI instead:
# ./sweep.sh --test-ramp
. "$(dirname "$0")/common.sh"
cd "$SADIY_HOME" || exit 2
banner
no_other_sweepd
./fpga.sh || exit 2
as_root python3 -m sadiy_ebaz.ramp_test "$@"
exit $?
