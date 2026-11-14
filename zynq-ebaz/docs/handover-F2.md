# Handover F2: PL sweep engine (for S7, S8, S9, S10)

Written by session R, 2026-11-14. Behaviour: `rtl-spec.md`. Python side: `handover-F1.md`. Status: `../log_rtl.md`.

## Build

```
cd zynq-ebaz
rtl/scripts/test.sh          # must end with ALL PASSED
rtl/scripts/build_bit.sh     # project in /media/patrik/Workspaces/HW/Vivado/EBAZ_SAdiy, output in build/fpga/
```
Needs Vivado 2025.2 (path in `rtl/scripts/env.sh`). At most 8 jobs. `build/fpga/summary.txt` has timing and
utilisation; the script fails if WNS or WHS is negative.

## For S8: load at runtime (not tested yet)

- File: `build/fpga/ebaz_sadiy.bit.bin`. The PS7 settings equal the Phase 1 design, so the Phase 1 boot image
  stays. Copy to `/lib/firmware/` and load through fpga_manager (verify the method on this image).
- Device tree overlay: one `generic-uio` node, `reg = <0x43C00000 0x1000>`, interrupt IRQ_F2P[0] (SPI 29,
  level high; verify the number in the generated device tree), clock FCLK0 must stay enabled.
- The EMIO line map is the Phase 1 map (GPIO 0..5 PE4302, 6 CE, 7 LD; SPI0; I2C0). With `CTRL.pin_owner = 0`
  the board behaves like Phase 1 plus one 10 ns register on the SPI and PE4302 outputs.

## First checks on the board (S8 / S9), in this order

1. Read `ID` (offset 0) = `0x53410001`, `VERSION` = `0x00010000`, `CAPS` = `0x00640C0C`.
2. With the PS as owner, repeat the Phase 1 checks (SPI frames on the DSLogic, PE4302 walk). Nothing may differ.
3. `PIN_STATE` shows the pad levels and lock detect.
4. Test generator sweep without RF: `DET_CFG = 1`, small table, `start`; results = `N_AVG * (DET_TEST + index)`.
   DSLogic on CLK / DAT / LE: words equal the table, 10 MHz, LE low for the whole word.
5. Attenuator change by the engine on the DSLogic: the make state is visible for `T_ATT_GAP_CYC` clocks.
6. Real sweep with `DET_CFG = 0` (PS pushes ADS1115 samples): compare with the PS-only sweep (S9 parity, +/-0.5 dB).
7. Measure: time per point and its jitter, lock time after R0 (then tighten `T_MIN_US`, `T_LOCK_*`, `T_SETTLE_US`),
   lock timeout with the synthesiser unplugged (`err_lock`, result bit 31), abort.
Write the results to `docs/ebaz-pl-measurements.md`.

## For S10: SPI ADC reader

Own module with `valid` and `data[15:0]` (unsigned), instantiated in `rtl/fpga/ebaz_sadiy_top.sv`, connected to
`det_ext_valid / det_ext_data` of `sadiy_top`, selected with `DET_CFG.src = 2`. Samples are taken only while the
sequencer is in SAMPLE, so the reader may free-run. New pins go into `pins.toml` first. `sadiy_top` does not change.

## If something is wrong

RTL files belong to session R: do not patch them from the Linux lane. Write `docs/escalations/NNN.md`
(template in the plan, section 1).
