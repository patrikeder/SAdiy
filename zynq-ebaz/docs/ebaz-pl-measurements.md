# PL engine measurements on the board

Newest first. What was measured, with which setup, and what is still open. Source of the numbers: the user's runs on the
EBAZ4205 with a logic analyzer (recorded by session R from the user's reports, 2026-11-14); no raw captures are in the repo.

Everything below was measured with register map 1.0. Maps 1.1 (ADS1115 reader in the PL, CE) and 1.2 (generator,
IF path) have not run on the board: `./run.sh adc if` is the first check.

## 2026-11-14 first load and run

Setup: bitstream `ebaz_sadiy.bit.bin` loaded with `sadiy_pl_load.sh`, `pl_bringup.py` from `build/bringup-pkg`, logic analyzer
on the engine pins. LCD and keys of the adapter already worked.

| Item | Result |
|---|---|
| `pl_bringup.py` automatic stages (ident, regs, gen, push, owner, ctrl, lock) | all checks passed (57 checks reported) |
| Logic analyzer, general | "looks good" (user) |
| SPI_DIV 3, expected 16.67 MHz | analyzer showed 15.62 MHz. A 64 ns period is impossible for the RTL (periods are multiples of 20 ns); 15.625 = 125 / 8 fits a 125 MHz analyzer sample rate rounding 7.5 samples up. Treated as measurement quantisation. |
| SPI_DIV 5, expected 10 MHz | 10 MHz |
| SPI_DIV 10, expected 5 MHz | exactly 5 MHz |

Not yet recorded (open): SPI_DIV 2 (25 MHz) reading, analyzer sample rate, LE / CLK setup and hold times against the ADF4351
datasheet, attenuator make-before-break captures (`att` stage), lock time and per-point time (`lock`, `gen` timing lines),
interrupt count, timeout and abort behaviour on the analyzer, real sweep against the PS-only sweep (S9 parity).
The 15.62 MHz reading should be re-checked with an analyzer sample rate of 500 MHz or more (or by timing 31 clock periods
of one word: 1860 ns at SPI_DIV 3).
