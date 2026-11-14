# zynq-ebaz/rtl

FPGA side of the EBAZ4205 port. Start with `../docs/rtl-spec.md` (what the logic does, section 12: how to change
it) and `../log_rtl.md` (state). `src/`, `sim/`, `regmap/`, `fpga/`, `scripts/`, `tests/` belong to the RTL lane;
`vivado/` (Phase 1, `pins.toml`) belongs to the Linux lane.

```
scripts/test.sh        # everything that needs no hardware
scripts/build_bit.sh   # bitstream, output in ../build/fpga/
```
