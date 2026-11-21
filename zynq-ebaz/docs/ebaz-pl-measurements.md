# PL engine measurements on the board

Newest first. What was measured, with which setup, and what is still open. Source of the numbers: the user's runs on the
EBAZ4205 with a logic analyzer (recorded by session R from the user's reports, 2026-11-14); no raw captures are in the repo.

Everything below the 2026-11-16 entry was measured with register map 1.0. The 2026-11-16 entry is map 1.2
(`VERSION` 0x00010002): `lock`, `adc` and `if` have run; `owner`, `ce` and `ctrl` have not been repeated on map 1.2.

## 2026-11-16 map 1.2: stage `if` (user run, `sudo ./run.sh if`, script output pasted)

Setup: map 1.2 bitstream, no ADC and no analog input needed (the sample generator feeds the IF path). Result:
**11 passed, 0 failed, 0 skipped.**

| Item | Result |
|---|---|
| Pattern | 1024 samples written through `GEN_ADDR`/data, address wrapped to 1024 |
| Setup of the test | generator 25.00 MSPS, tones at bins 100 and 260 of 1024 (2441.4 kHz and 6347.7 kHz, second 20 dB lower), CIC R = 16 (RBW about 1562 kHz), 56 points of 5 bins |
| Sweep | 56 points finished, no over-range flag |
| DSP chain | **every result word equals the Python reference** (bit-exact: NCO, mixer, 3-stage CIC, I^2+Q^2, exponent/mantissa on the real fabric) |
| Tone levels | strongest point is the first tone (point 12); 84.08 dB against 84.08 dB calculated (within 0.2 dB); second tone 19.99 dB lower (within 1 dB) |
| Trace | lower quartile 42.6 dB, i.e. 42 dB between the tone and the typical floor of this synthetic signal (quantisation of the 16 bit pattern and filter leakage, not analog noise) |
| Time | 28 us per point including Python polling; filter time alone 7.7 us per point |

Read: the IF path of register map 1.2 (sample generator, `if_power`, result memory, sweep sequencer in IF mode) works on
the board and matches the reference exactly, so what is left for the IF path is the analog side (ADC adapter,
input filter, real signal). The 42 dB figure belongs to the test pattern; it says nothing about the receiver.
STATUS before the run showed `pin_owner_act` 0 (PS owned the pins, the previous stage had released them).

Still open: `owner`, `ctrl`, `ce` stages on map 1.2, analyzer frames, a real sweep with `sweepd --platform ebaz`
(detector `pl`) and, for the IF path, a converter (`adc_ad9226` or `adc_spi_sar`) on real pins.

## 2026-11-16 map 1.2: stages `lock` and `adc` (user run, `sudo ./run.sh lock adc`, script output pasted)

Setup: map 1.2 bitstream, ADF4351 and ADS1115 connected, **ADS1115 input open (nothing on the input, user, 2026-11-16)**, no logic analyzer reading reported for this run. Result:
**17 passed, 0 failed, 0 skipped** (ident 4, lock 5, adc 8 checks as printed).

| Item | Result |
|---|---|
| Identity | ID 0x53410001, VERSION 0x00010002, fabric clock 100 MHz, CAPS 0x00640C0C (table and results 4096) |
| `lock` | engine takes the pins; LD reads 1 before and after; 2 points finished, no `err_lock`, no result flagged unlocked; 447 us per point (the engine waits 20 + 50 + 20 us; the rest is Python polling) |
| `adc` config | 0xC3E3 (single shot, OS set), address 0x48, I2C 357 kHz, conversion wait 1429 us |
| `adc` pin ownership | PS owns I2C before (`i2c_pl` 0), bus idle (SCL, SDA high), reader owns it during the sweep (1), PS again afterwards |
| `adc` readings | 2 points x 4 samples = 8 conversions read by the PL, ADS1115 acknowledged (no `err_nack`). Point 0 mean code 5196.0 = 0.6495 V, point 1 mean 5620.0 = 0.7025 V (424 codes apart), last conversion register 0x1430 = 5168 = 0.6460 V. Codes in range. **Values are meaningless: the input was open (floating).** |
| Time per sample | 1.78 ms including Python polling (1429 us conversion wait + about 252 us on the bus) |

Read: the PL sweep with the LD wait and the I2C reader in the PL work on the board, so register map 1.1 (ADS1115 reader,
`pin_mux`, CE) is confirmed for these two stages. The conversion values (and the 424-code difference between the two
points) say nothing about the chain: the ADS1115 input was open, so the codes are a floating input. The run proves
addressing, timing, ACK and pin ownership only. A reading check needs a known voltage on the input (or the detector).

Still open from this run: I2C frames and LD frames on the analyzer (`LA` lines were printed, nothing reported), the LD
timeout path (make LD low and rerun `lock`), the stages `owner` / `ce` / `if` on map 1.2, the SPI_DIV points listed
below, an actual sweep with `sweepd --platform ebaz`.

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
