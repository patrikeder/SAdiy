---
name: rtl-check
description: Run and interpret the checks of the EBAZ4205 RTL lane (generated files, pytest, lint, xsim testbenches). Use after any change below zynq-ebaz/rtl or zynq-ebaz/sw, or when asked whether the RTL tests pass.
---

# Checking the RTL lane

Work in `/media/patrik/Workspaces/uC/SAdiy-rtl`. Activate the existing environment first:
`. /media/patrik/Workspaces/uC/SAdiy/.venv/bin/activate` (install nothing).

| Command (in `zynq-ebaz/rtl/scripts/`) | Does | Time |
|---|---|---|
| `test.sh` | everything below, must end with `ALL PASSED` | 2 to 3 min |
| `test.sh --no-sim` | without the xsim testbenches | 20 s |
| `gen.sh` / `gen.sh --check` | regenerate / check register files, golden vectors, sine and twiddle tables | seconds |
| `sim.sh tb_name ...` | chosen testbenches; logs in `zynq-ebaz/build/sim/tb_name/` | 10 to 60 s each |
| `SIM_GUI=1 sim.sh tb_name` | waveform window for one testbench | |

Reading a failure:
- **"generated files out of date"**: `regmap.toml`, the model or a reference changed. Run `gen.sh`, look at the
  diff of the generated files, then run the testbenches: changed vectors mean changed behaviour.
- **pytest**: a hard-coded `VERSION`, an offset used as "unused address" or a register mask in
  `sw/tests/contract/test_pl_model.py` after a register map change is a stale expectation; anything else is a
  real difference between model and intent.
- **verilator**: fix every warning in the source; do not add `-Wno-` switches.
- **testbench**: the line `TB FAIL: <reason>` names the check. "reference" in the message means the RTL differs
  from the Python reference: decide from `docs/rtl-spec.md` which one is wrong. An `x` in a compared value
  usually means a missing reset or a memory read before it was written.
- A pytest run that ends with "Fatal Python error: Aborted" in a GUI test is not an RTL problem: see
  `tests/conftest.py`; remove leftover `sweepd --sim` processes whose config is `/tmp/sadiy-sim-*.toml`.

After a new or changed check, prove it: break the RTL on purpose in a scratch copy and see the testbench fail
(agent `rtl-verifier`). Report results with numbers (tests passed, testbenches passed), never just "passes".
