# Handover F2: PL sweep engine (for S7, S8, S9, S10)

State 2026-11-15: register map 1.2. The first two sections describe the first bitstream (map 1.0); where later
work changed something it is marked. Newest additions are the sections "sweepd on the PL engine" and "Fast path".

Written by session R, 2026-11-14. Behaviour: `rtl-spec.md`. Python side: `handover-F1.md`. Status: `../log_rtl.md`.

## Build

```
cd zynq-ebaz
rtl/scripts/test.sh          # must end with ALL PASSED
rtl/scripts/build_bit.sh     # project in /media/patrik/Workspaces/HW/Vivado/EBAZ_SAdiy, output in build/fpga/
```
Needs Vivado 2025.2 (path in `rtl/scripts/env.sh`). At most 8 jobs. `build/fpga/summary.txt` has timing and
utilisation; the script fails if WNS or WHS is negative.

## For S8: load at runtime (done by session L: `sw/deploy/sadiy_pl_load.sh`, works on the board)

Outdated in the list below: there is no UIO node and no interrupt in use (register access is /dev/mem, completion
is polled), and the boot image now contains the engine bitstream, so a runtime load is only needed for a newer one.

- File: `build/fpga/ebaz_sadiy.bit.bin`. The PS7 settings equal the Phase 1 design, so the Phase 1 boot image
  stays. Copy to `/lib/firmware/` and load through fpga_manager (verify the method on this image).
- Device tree overlay: one `generic-uio` node, `reg = <0x43C00000 0x1000>`, interrupt IRQ_F2P[0] (SPI 29,
  level high; verify the number in the generated device tree), clock FCLK0 must stay enabled.
- The EMIO line map is the Phase 1 map (GPIO 0..5 PE4302, 6 CE, 7 LD; SPI0; I2C0). With `CTRL.pin_owner = 0`
  the board behaves like Phase 1 plus one 10 ns register on the SPI and PE4302 outputs.

## First checks on the board (S8 / S9), in this order

Most of this is automated: `rtl/scripts/make_bringup_pkg.sh` builds `build/bringup-pkg/` (bitstream, load script,
`sadiy`, `sadiy_ebaz`, `regmap.toml`, `pl_bringup.py`, `run.sh`); copy it to the board, load the bitstream, then
`./run.sh` (stages ident regs gen push owner ctrl lock adc if: pass / fail, exit code) and `./run.sh la` (spi att: SPI
frames at several SPI_DIV values and attenuator changes, with the expected LA picture printed and a prompt before
each capture). `./run.sh --model` runs the same code against the PlModel on a PC. Needs Python 3.11+ (tomllib)
or tomli. Steps 1 and 2 below (PS as owner, Phase 1 regression) stay manual. Source: `sw/tools/pl_bringup.py`,
tests: `sw/tests/test_pl_bringup.py`.

1. Read `ID` (offset 0) = `0x53410001`, `VERSION` = `0x00010002` (map 1.2; the first bitstream had `0x00010000`),
   `CAPS` = `0x00640C0C`.
2. With the PS as owner, repeat the Phase 1 checks (SPI frames on the DSLogic, PE4302 walk). Nothing may differ.
3. `PIN_STATE` shows the pad levels and lock detect.
4. Test generator sweep without RF: `DET_CFG = 1`, small table, `start`; results = `N_AVG * (DET_TEST + index)`.
   DSLogic on CLK / DAT / LE: words equal the table, 10 MHz, LE low for the whole word.
5. Attenuator change by the engine on the DSLogic: the make state is visible for `T_ATT_GAP_CYC` clocks.
6. Real sweep with `DET_CFG = 0` (PS pushes ADS1115 samples): compare with the PS-only sweep (S9 parity, +/-0.5 dB).
7. Measure: time per point and its jitter, lock time after R0 (then tighten `T_MIN_US`, `T_LOCK_*`, `T_SETTLE_US`),
   lock timeout with the synthesiser unplugged (`err_lock`, result bit 31), abort.
Write the results to `docs/ebaz-pl-measurements.md`.

## sweepd on the PL engine (register map 1.1, 2026-11-14)

- The bitstream now reads the ADS1115 itself (`DET_CFG.src = 3`, `rtl-spec.md` section 8a), drives CE from
  `ADF_PINS.ce` and muxes the I2C pins between PS I2C0 and its reader. PS push (`src = 0`) is unchanged.
- `sw/sadiy_ebaz/platforms/ebaz_pl.py` is a platform that uses only the registers (/dev/mem): SPI words, PE4302,
  CE, lock detect, detector. `sweepd --platform ebaz` (or `[platform] name = "ebaz-pl"`) starts it; in the
  bring-up package: `./sweepd.sh`. `[platform] detector = "pl" | "ps" | "test"` picks the sample source.
  The RF outputs are enabled only after the PLL locked once with them off. No bench mode on the hardware yet.
- **The bitstream must be the new one** (VERSION 0x00010001): load `ebaz_sadiy.bit.bin` at runtime or rebuild
  BOOT.BIN from the new XSA. PS7 settings did not change (no FSBL / device tree change needed).
- Check first: `./run.sh adc` (I2C acknowledge, codes, hand-over of the bus), optional `./run.sh ce`.
- Tested on the PlModel and in xsim (`tb_adc`), not on the board.

## Fast path without an ADC (register map 1.2, 2026-11-15)

- Sample stream format for every fast ADC, the software-filled generator and the IF path (NCO, mixer, CIC,
  power): `rtl-spec.md` sections 8b and 8c. `DET_CFG.mode = 1` selects the IF path, `DET_CFG.stream = 1` the
  generator. Python: `sw/sadiy_ebaz/ifpath.py` (pattern builder, bit-exact reference, result decoding).
- On the board: `./run.sh if` loads a two-tone pattern, sweeps the NCO across it and compares every result
  word with the reference. Not connected to sweepd yet (no detector kind for it in `ebaz_pl.py`), because
  there is no IF signal to measure until an ADC adapter exists.
- Tested in xsim (`tb_if`, bit for bit) and on the PlModel, not on the board.

## For S10: SPI ADC reader

(The ADS1115 on I2C is read by the PL since map 1.1, see above; this is for a faster SPI ADC later.)
Own module with `valid` and `data[15:0]` (unsigned), instantiated in `rtl/fpga/ebaz_sadiy_top.sv`, connected to
`det_ext_valid / det_ext_data` of `sadiy_top`, selected with `DET_CFG.src = 2`. Samples are taken only while the
sequencer is in SAMPLE, so the reader may free-run. New pins go into `pins.toml` first. `sadiy_top` does not change.

## If something is wrong

RTL files belong to session R: do not patch them from the Linux lane. Write `docs/escalations/NNN.md`
(template in the plan, section 1).
