---
name: fpga-bitstream
description: Build the EBAZ4205 bitstream, read timing and utilisation, and prepare the package for the board. Use when asked for a bitstream, FPGA usage numbers, or files to copy to the board.
---

# Bitstream and board package

Work in `/media/patrik/Workspaces/uC/SAdiy-rtl/zynq-ebaz`. Vivado 2025.2 (path in `rtl/scripts/env.sh`).
Only one Vivado build at a time. Run builds in the background and wait for the notification.

1. `rtl/scripts/test.sh` must pass first.
2. `rtl/scripts/create_project.sh --force` when source files were added or removed, or the block design, PS7
   settings or constraints changed. The project is `/media/patrik/Workspaces/HW/Vivado/EBAZ_SAdiy` (generated,
   not in git; the user may have it open in the Vivado GUI: ask before recreating it).
3. `rtl/scripts/build_bit.sh` (6 to 10 minutes). It fails when timing is not met.
4. Read `build/fpga/summary.txt`: WNS and WHS not negative, 0 critical warnings. Give LUT, FF, block RAM tiles
   and DSP with percent (XC7Z010: 17600 LUT, 35200 FF, 60 tiles, 80 DSP); slices are in
   `EBAZ_SAdiy.runs/impl_1/ebaz_sadiy_top_utilization_placed.rpt`.
5. `rtl/scripts/check_ps7.sh` must say IDENTICAL. If it lists keys, the boot image of session L no longer fits
   the bitstream: tell the user and write the keys into `log_rtl.md` under "for L".
6. For a pin change, confirm the balls in `EBAZ_SAdiy.runs/impl_1/ebaz_sadiy_top_io_placed.rpt`.
7. `rtl/scripts/make_bringup_pkg.sh`: `build/bringup-pkg/` holds everything the board needs (it has no fixed
   paths; copy the whole folder). Rebuild it after every new bitstream.
8. Log entry in `log_rtl.md` with date, WNS, utilisation, register map version.

Standalone modules in `rtl/dsp/` are not part of the bitstream: `rtl/scripts/synth_dsp.sh [top]` builds them
out of context and prints one line per module (WNS, LUT, FF, RAM, DSP).

Timing fails: report source and destination of the worst path from
`EBAZ_SAdiy.runs/impl_1/ebaz_sadiy_top_timing_summary_routed.rpt`; the fix is a register stage or a simpler
expression in the RTL, never a relaxed constraint.
