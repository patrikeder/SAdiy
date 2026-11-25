---
name: board-test
description: Guide a test of the PL sweep engine on the real EBAZ4205 and evaluate what the user reports (script output, logic analyzer readings). Use when the user is at the bench, pastes pl_bringup output, or asks what to test next.
---

# Testing on the board

You cannot reach the board; the user runs the commands and reports. Package:
`/media/patrik/Workspaces/uC/SAdiy-rtl/zynq-ebaz/build/bringup-pkg/` (make it with
`rtl/scripts/make_bringup_pkg.sh`; copy the whole folder anywhere on the board; run as root).

```
./sadiy_pl_load.sh          # bitstream; never read the registers before this (the CPU stalls)
./run.sh                    # automatic stages, PASS / FAIL per check, exit code
./run.sh la                 # SPI frames for the logic analyzer
./run.sh att | if | fe | ce # single stages: PE4302 via PCF8574, IF path with the generator, ADC front end, CE pin
./sweepd.sh                 # sweepd on the PL engine;  ./sweepd.sh --bench-only  for wiring tests
```

Order for a new bitstream: `run.sh` with the ADF4351 unplugged or CE low (`att` is in it and fails without a PCF8574
on the bus), then `run.sh la`, then with the ADF4351 and the PCF8574 connected `run.sh lock att`, then `sweepd.sh` with the GUI on the PC
(`python -m sadiy.ui.sa_gui --host <ip> --connect`).

Before judging a result, read `zynq-ebaz/docs/ebaz-pl-measurements.md` (what was measured before) and the
stage's code in `zynq-ebaz/sw/tools/pl_bringup.py`.

Facts for the evaluation:
- SPI clock = 100 MHz / (2 x SPI_DIV); every period is a multiple of 20 ns. A frequency that is not (15.62 MHz
  for SPI_DIV 3) comes from the analyzer's sample rate: ask for it, or for the duration of 31 clock periods.
- A word with LE takes 67 x SPI_DIV clocks. LE is low for the whole word.
- Attenuator (PCF8574 on I2C, 100 kHz): where stages switch both ways, one transaction carries two bytes: the first
  (old and new stages in) is on the ports for one byte time (90 us), then the final one; the attenuation never drops
  below the lower of old and new. `T_ATT_GAP_CYC` x 10 ns of hold follows. Decode SCL / SDA on the analyzer.
- `err_nack` (ATT_STAT): wiring, the expander's supply (3.3 V, never 5 V), its address (a PCF8574A is 0x38..0x3F),
  I2C pull-ups. The 2.2 kohm pull-ups on V1..V6 are not seen by it: check V high above 2.3 V with a DMM.
- `if` stage: every result word must equal the Python reference; the first tone lands on point 12, the second
  20 dB lower on point 44.
- `VERSION` tells which bitstream runs: 0x00010000 first, 0x00010001 with the ADS1115 reader and CE,
  0x00010002 with generator and IF path, 0x00010003 with the ADC front end, 0x00020000 with the PE4302 on the PCF8574
  (what the software needs now). A boot image contains the bitstream of its build day.

A FAIL is a hardware finding or a wrong assumption of the script: find out which, do not relax the check.
Write every session into `zynq-ebaz/docs/ebaz-pl-measurements.md` (date, setup, table measured against expected,
what is open), only from what the user reported.
