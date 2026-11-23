# PL engine measurements on the board

Newest first. What was measured, with which setup, and what is still open. Source of the numbers: the user's runs on the
EBAZ4205 with a logic analyzer (recorded by session R from the user's reports, 2026-11-14); no raw captures are in the repo.

The 2026-11-23 entry is map 1.3 (`VERSION` 0x00010003, stage `fe`). Everything below the 2026-11-16 entry was measured with register map 1.0. The 2026-11-16 entry is map 1.2
(`VERSION` 0x00010002): `lock`, `adc` and `if` have run; `owner`, `ce` and `ctrl` have not been repeated on map 1.2.

## 2026-11-23 map 1.3: stage `fe` (user run, `sudo sh ./bringup-pkg/run.sh fe`, script output pasted)

Setup: bitstream built 2026-11-23 20:06 (md5 11e55973d7dd215d71dd5ae105baa832, `VERSION` 0x00010003), loaded with
`fpga.sh --force`; package `bringup-pkg` from main, commit 8c474f6. No ADC module, no ADC pins in this build (data lines tied
off inside the engine). The first attempt ran an old hand-copied `bringup-pkg` (Nov 14, VERSION 0x00010002) and was
discarded; see the log. Result: 19 passed, 0 failed, 0 skipped (ident checks in the same run also passed).

| Check | Measured |
|---|---|
| Reset | `FE_CFG` 0x00010200, `FE_TG_INC` 0x36C8B439, front end off: clock low, no samples counted |
| Tie-off (`FE_TIE` 0x123) | last code 0x123 four times; sample counter advances (counts 6026, 10110, 11852, 16757 between reads: software timing, not a rate); OTR reaches `last_otr` and sticky `otr_seen`; clear drops both and restarts the counter |
| Traffic generator | ramp: codes differ read to read; walking one: exactly one bit set every time, all 12 lines seen (1 .. 2048); constant mode shows `FE_TIE`; front end off stops the counter |
| Pins | source 2 reads 0x800, OTR 0 (nothing wired, as expected) |
| IF path, tie-off stream | result word 0x023FFE00 = Python reference (bit-exact) |
| IF path, OTR | OTR reaches result bit 30 |
| IF path, tone at 50 MS/s | word 0x02BFFED8 (exponent 10, in 9..11, no over-range); a tone two filter nulls away: exponents 10 and 0 (more than 8 lower) |

Read: the clock divider, capture registers, conversion, stream mux, IF path at the 50 MS/s rate and the result word work on the
board with the generator as the data source. The generator and the capture run in the same fabric clock domain, so this does
not say anything about the capture phase against a real converter or about the pad timing: that needs the module. The
bitstream met timing (WNS +1.51 ns) with a thin hold margin (WHS +0.007 ns); the run does not exercise that.

### Same day: full run `sudo sh ./bringup-pkg/run.sh` on map 1.3 (ADF4351 unplugged, ADS1115 connected, input open)

90 passed, 1 failed, 1 skipped. The skip is the interrupt count (no uio line in `/proc/interrupts`, as before). The fail was
`front end off at reset` in stage `fe`: a wrong assumption of the script, not hardware. The sample counter is cleared only by
reset or the `clear` bit and keeps its last value while the front end is off, so it is 0 only on a freshly loaded bitstream
(first run: pass; second run without reload: counter still at the last value). Fixed in `pl_bringup.py` (write `clear` first,
then the counter must stay 0); the model reproduces it with two `fe` stages in one run. Everything else on map 1.3 passed
again: `regs`, `gen` (716 to 756 us per point), `push`, `owner`, `ctrl`, `lock`, `adc` (ACK, 8 conversions; the values are an
open input), `if` (bit-exact, tone 84.08 dB as calculated, second tone 19.99 dB lower, 27 us per point), `fe` (all other checks).

### Same day: sweepd and GUI on map 1.3

`./sweep.sh` (sweepd on the PL engine, commit 8c474f6) with the ADF4351 unplugged and the ADS1115 input open: the normal sweep
ran (401 points, 4 averages, about 7 s per sweep, a sweep every 14 s), every point flagged `no PLL lock` and the RF outputs
stayed off (`ADF4351 did not lock`), 4 to 9 points per sweep flagged overload; the GUI trace showed several peaks that are
noise of the floating input, not signals. With the **Virtual spectrum** button on, the GUI showed 3 peaks, "about where they are
expected" (user report; the dashed expected trace was not reported). The GUI's Device log said "sweepd sent no log" after 5 fetches:
sweepd answered the build query only 8 s after connecting, which fits commands being served between sweeps (hypothesis, L's
side, not confirmed).

### Same day: ADF4351 connected (user runs, outputs pasted)

| Item | Result |
|---|---|
| Bench mode (Linux, PS pins) | LO 100.000 MHz (integer-N, INT 128, VCO 3200 MHz, /32) and 110.700 MHz (fractional-N, INT 141, FRAC 87, MOD 125, VCO 3542.4 MHz): LD 1 at both, frequencies match on the scope (user). Output about 50 mVpp into 50 ohm with everything terminated, i.e. -22 dBm against the -4 dBm setting; the user suspects the probe (a 10:1 setting error would be exactly 20 dB) and sees the expected products at the mixer output. Not resolved, not a finding yet. |
| `sweep.sh` (PL engine) | no `did not lock`, no `read without PLL lock` for the full 30 to 480 MHz sweep (401 points, 4 averages): 3.45 s per sweep (7.47 s while LD was low). Overload flags (126 of 401) are the open ADS1115 input. A 110 kHz span around 255 MHz (502 points, 3 averages, 3.6 s per sweep) also swept without lock flags. |
| `run.sh lock adc` | 17 passed, 0 failed: LD high (`ld_now` 1), sweep finished without `err_lock` or unlocked flags, 439 us per point (waits 20 + 50 + 20 us plus polling); ADS1115 ACK, 8 conversions, I2C pins handed over and back. |
| ADS1115 values | 0.914 V, 0.857 V, last 0.532 V: floating input, no information about scaling. |

Read: the engine's lock wait works against the real ADF4351 LD, with the real PL-driven SPI words and the PL reading the ADS1115. The
ADF4351 register words give the right frequency and lock in both integer-N and fractional-N; the output level is unmeasured
(probe). Nothing here involves RF through the chain, the detector or the AD9226.

Still open: `FE_CFG.phase` against the real module, pins (ADC_PADS build, adapter v2), the ADF4351 output level with a verified probe setting, a sweep against RF. Dropped by the user's decision (2026-11-24): `la` on map 1.3 (SPI is known to work) and the ADS1115 scaling check (the I2C ADC will be removed; the AD9226 replaces it).

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
