# zynq-ebaz/rtl

FPGA side of the EBAZ4205 port. Start with `../docs/rtl-spec.md` (what the logic does, section 12: how to change
it) and `../log_rtl.md` (state). `src/` (the engine, in the bitstream), `dsp/` (standalone modules for later, see
`../docs/dsp-modules.md`), `sim/`, `regmap/`, `fpga/`, `scripts/` belong to the RTL lane;
`vivado/` (Phase 1, `pins.toml`) belongs to the Linux lane.

```
scripts/test.sh        # everything that needs no hardware
scripts/build_bit.sh   # bitstream, output in ../build/fpga/
scripts/synth_dsp.sh   # standalone DSP modules, out-of-context build, output in ../build/dsp/
scripts/make_bringup_pkg.sh   # what the board needs: bitstream, pl_bringup.py, sweepd launcher
```
