# EBAZ4205 bring-up (S4)

Status 2026-11-14: not started. Needs the Phase 1 boot image (S3) and the user at the bench.

## Checklist for the bench session
Do each step with the PE4302 at 31.5 dB (nothing driven) before any RF is connected.

1. Boot the new image from the second SD card; `sh -s < sw/tools/ebaz_baseline.sh`. Expect
   `/dev/spidev0.0`, an I2C adapter, the Zynq gpiochip with 54+16 lines.
2. EMIO line numbering: with `gpioset`/libgpiod toggle line 54 + n and probe the adapter pin
   with a DMM or the DSLogic (n = 0..6 outputs, 7 input).
3. `python tools/bringup.py pe4302-walk` with the mapped lines: detector rises by weight x 24.5 mV.
4. DSLogic on CLK, DAT, LE: `adf4351-pattern` frames decode as in `patterns.py`.
5. ADF4351 at 100 MHz on the MSO5354 (outputs off until enabled after lock).
6. ADS1115 answers at 0x48 (`i2cdetect -y N`).

Results go below (what was measured, instrument, date).
