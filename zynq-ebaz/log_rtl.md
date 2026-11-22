# RTL lane log (session R)

Worktree `/media/patrik/Workspaces/uC/SAdiy-rtl`, branch `rtl`. Newest entry first. Session L writes
`zynq-ebaz/log_linux.md` in its own worktree. Spec for everything below: `zynq-ebaz/docs/rtl-spec.md`.

## Notes for session L (read this part)

- **User decision 2026-11-14:** session R builds the FPGA hardware for the engine. R's Vivado scripts are in
  `zynq-ebaz/rtl/fpga/` and generate the project `/media/patrik/Workspaces/HW/Vivado/EBAZ_SAdiy`. Your
  `zynq-ebaz/rtl/vivado/**` (Phase 1, `pins.toml`, `gen_xdc.py`) is not touched and `pins.toml` stays the pin
  master. This takes S8's Vivado part from you; the runtime bitstream load and the UIO device tree stay yours.
- PS7 settings and EMIO line map are the same in both designs (`check_ps7.sh`: identical, 2026-11-15): GPIO 0..5
  PE4302, 6 CE, 7 LD, 8 / 9 LCD, 10..12 LEDs, 13..17 keys, SPI0, SPI1 (LCD), I2C0, ENET0 MII, FCLK0 100 MHz,
  FCLK1 25 MHz. A newer engine bitstream loads at runtime on the current image. AXI-lite base of the engine: `0x43C0_0000`, 4 KiB, on M_AXI_GP0;
  interrupt on IRQ_F2P[0].
- The register map differs from plan appendix A / B (generic SPI word table, indirect table / result access,
  PS-pushed detector samples). See `docs/rtl-spec.md` section 11. Current map: 1.2 (`rtl/regmap/regmap.md`).
- `sweepd --platform ebaz` on hardware uses `sw/sadiy_ebaz/platforms/ebaz_pl.py` (registers through /dev/mem).
  Register access is /dev/mem, no UIO (your decision of 2026-11-14); older text that says UIO is outdated.

## State in one line

**2026-11-15: engine with register map 1.2 (sweep sequencer, ADS1115 reader in the PL, sample generator, IF path) committed and merged to main (77c6d61 / 0681729), bitstream built, timing met. On the board map 1.0 ran first (57 checks passed, SPI clock verified); on 2026-11-16 map 1.2 passed the stages `lock`, `adc` (17/17, ADC input open) and `if` (11/11, bit-exact); `owner`, `ce`, a real analog input and sweepd on the engine are untested there. Standalone DSP modules (`rtl/dsp/`: FFT, FIR, bin power, ADC adapters) are built and tested in isolation, not in the bitstream. Session L's bench mode (`--bench-only`, PS owns the pins) is merged. Not pushed.**

## 2026-11-22 virtual spectrum: three peaks and drift from the engine itself (user request, built with L)

`sadiy_ebaz/virtual_spectrum.py`: `VirtualSweep(offload, detector, cal)` has the call of `OffloadSweep`
(`run_points`) so a SweepEngine takes it as `offload`. The generator plays 4096 samples (25 MS/s) with three tones
plus noise, the IF path steps its NCO over the points (IF_NCO_STEP), the table is measure-only entries (no SPI,
pins unchanged). The display shows peaks at 100 / 200 / 300 MHz of the points' axis at -30 / -45 / -60 dBm on a
-90 dBm floor (CIC R = 128: first null +-195 kHz); volts are built from the detector and cal objects so the normal
path shows exactly those levels. Per sweep the NCO window drifts by up to +-8 points (period 48 sweeps) and
`IF_CIC.skip` cycles through 4, 8, 12, 6, 10, 14 (new noise draw every sweep, peaks stay). `ideal_dbm()` is the
noise-free expected trace (overlay), `verify()` compares result words bit for bit with `ifpath.if_power_ref`,
`state()` gives sweep / drift / skip, `close()` restores DET_CFG, GEN_CFG, IF_NCO(_STEP), IF_CIC, T_MIN/T_SETTLE,
N_AVG (idempotent, never raises). Found while testing: `IF_CIC.skip` is 4 bits, so a skip of 16 or more silently wraps
(the first version used 16 and 20 and showed transients in the skirts); now refused with ValueError. Tests:
`tests/test_virtual_spectrum.py` (19, PL model; four deliberate breakages each fail 1 to 4 of them). Full suite 860
passed. Not run on the board. Expected time per sweep there: about 25 ms of hardware (mean skip 7.3: 60 us a
point) plus about 5 ms readout and the poll.

## 2026-11-22 ramp self-test passed on the board; `RegOffload.last_sweep_s` / `last_read_s`

L ran `selftest.sh --wrap -v` on the board (map 1.2): PASS, 191 of 191 checks. Time: 22.5 to 22.8 ms for 401
points, N_AVG 4, T_MIN = T_SETTLE = 20 us, against 17.7 ms from the point-time model. The difference is the host:
`RegOffload.run()` returns only after the result readout (401 x RESULT_DATA through /dev/mem, about 10 us each) and
`done` is seen at the next 1 ms poll; the sequencer adds only about 0.11 us per point (fabric clock 100 MHz,
checked by the SPI clock on the analyzer). `run()` now stores `last_sweep_s` (start write until done is seen) and
`last_read_s` (readout) so a test can check the hardware floor against the first only
(`tests/test_offload_timing.py`, 4 tests). Prediction to check on the board: `--fill` (4096 points) about 49 ms of
extra time if it is the readout.

## 2026-11-21 sweeps larger than the table run in chunks (user: "yes, do chunking with a test")

Problem seen on the target: a sweep needs more table entries than the core holds (4096; 4001 points = 6865
entries, about 3100 points is the limit for 30..480 MHz, less for narrow spans), so `upload` refused it.
`OffloadSweep.run_points` now splits such a sweep into runs of whole points (`plan_chunks`, uses the core's
`max_entries` and `max_points`), uploads and runs each, and returns one list: the caller sees one sweep
(`OffloadSweep.chunks` = number of runs of the last sweep). The first point of every run carries all six
register words (its table does not know what the run before sent), the PE4302 level is applied again at the
start of each run (same value, no change). A sweep that fits behaves as before (table uploaded once, cached); a
chunked sweep uploads every table at every sweep. SWEEP_COUNT counts one per run. A point that does not fit alone
raises ValueError. `platform.build_table` is now `point_words` + `table_from_words` (same output).
`tests/test_offload_chunking.py` (14 tests: planner, boundaries lose/repeat no point, result memory limit, equal to
the one-table result on the PL model, re-upload, plan cache, incomplete run); three deliberate breakages of the
planner fail 6, 7 and 0 (equivalent mutant: the upload guard exists twice) of them. Full suite 837 passed.
Not run on the board; the gap between runs (upload plus start, a few ms by estimate, not measured) is the cost.
`sweepd.py` `points_max: 4001` (session L's file) now holds for every span.

## 2026-11-21 block diagram redrawn with the Verilog hierarchy

`docs/blockdiagram.svg` (from `rtl/scripts/gen_blockdiagram.py`, rewritten) now shows the hierarchy as frames
(`ebaz_sadiy_top`, `u_engine : sadiy_top`, `u_bd : ebaz_sadiy_bd`, `u_if : if_power`), every engine instance
including the inline logic (synchronisers, I2C handover, selectors, irq gate) and the IF chain, and a 2 to 3 word
name on every wire, coloured by kind. Kept from the old drawing: devices outside the FPGA, FPGA pins, EMIO line
numbers, DDR/MIO note, "not built yet". No RTL change.

## 2026-11-16 bench mode on the board works with the map 1.2 engine (report from L, user gave no numbers)

- L reports (from the user): `sweepd --platform ebaz --bench-only` + GUI on the PC: ADF4351 frequencies, PE4302 attenuation
  and ADS1115 values all worked; the pins came back to Linux as expected. Engine needed no change. Not reported yet: lock
  detect per frequency, output frequency and level, PE4302 weights and polarity, DMM comparison of the ADC, `synth-ce`.
- L's main is edfddfc (823 tests): board scripts in `zynq-ebaz/sw/board/`, `sw/tools/ebaz_pl_probe.py`, `sadiy/buildinfo.py`
  (BUILD_INFO via `make_bringup_pkg.sh`), `deploy_to_board.sh` also copies the bitstream. Still to do on R's side when
  the user says so: `git merge main` in SAdiy-rtl and remake the bring-up package. `on_wait` hook: waits for the user.
- User, same day: ADF4351 output frequencies match what was set (no numbers given); output levels not measured yet, expected
  "not far off".
- Nothing committed for this entry.

## 2026-11-16 map 1.2 on the board: stage `if` passes (11/11), DSP chain bit-exact

- `sudo ./run.sh if`: 11 passed, 0 failed. 56 points of the IF sweep (generator 25 MSPS, two tones, CIC R = 16) equal the
  Python reference word for word; first tone 84.08 dB (calculated 84.08), second 19.99 dB lower, no over-range flag; 28 us
  per point incl. Python polling (7.7 us filter time). The 42 dB trace range belongs to the synthetic pattern.
- Open: `owner` / `ctrl` / `ce` on map 1.2, LA frames, `sweepd --platform ebaz`, a converter on real pins. Details in
  `docs/ebaz-pl-measurements.md`. Nothing committed for this entry.

## 2026-11-16 first run of map 1.2 on the board: `lock` and `adc` pass (17/17)

- User ran `sudo ./run.sh lock adc` on the board (VERSION 0x00010002): 17 passed, 0 failed. LD wait 447 us per point
  incl. Python polling; the ADS1115 reader in the PL took 8 conversions, 1.78 ms per sample, no NACK, pin ownership
  switches correctly (`i2c_pl` 0 / 1 / 0). Details and the open points in `docs/ebaz-pl-measurements.md`.
- The ADS1115 input was open, so the codes (and the 424-code difference between the two points) mean nothing; the run
  proves I2C addressing, timing, ACK and ownership only. Check values with a known voltage on the input.
- Open: `if`, `owner`, `ce` on map 1.2; LA
  frames; LD timeout path; `sweepd --platform ebaz` on the engine. Nothing committed for this entry.

## 2026-11-15 adapter pins from L's pins.toml (not merged yet), AD9226 pins stay a proposal

- L's `pins.toml` (worktree `SAdiy-linux`, uncommitted when read) lists the adapter LEDs as `led[0..2]` (H18, K17,
  E19), keys and display as DATA3 entries, and notes the AD9226 balls shared with the adapter. User decision: the
  LEDs stay, so `adc_d[8]`, `adc_d[10]` and `adc_clk` have no DATA1 ball on this adapter. The user will probably
  replace the adapter later; **ADC_PROPOSAL in `gen_pinmap.py` stays a proposal**, nothing about the LED/key/HDMI
  assignment is hard-wired beyond `adapter_ui.xdc` and the PS7/EMIO settings.
- Confirmed by the user: right connector row 3 left is **J20** (not U20; U20 is KEY3). The "verify" notes are gone from
  `gen_pinmap.py`; the older entries below still show them (history).
- `gen_pinmap.py` got `PINS_TOML=<file>` to read a pins.toml other than the worktree's (used with L's file until it is
  merged); text updated (DATA3 now mapped, LED decision, proposal not final). Regenerated `docs/pinmap.md` and
  `docs/pinmap.svg` (`--check`: current with L's file). The snapshot `rtl/fpga/constraints/data2_pins.xdc` is now a copy
  of L's generated `ebaz4205.xdc` (`check_pins.sh`: identical). `pinmap-fpga.svg` and `pinmap-adapter.svg` did not change.
- After L merges: run `gen_pinmap.py` without `PINS_TOML` (same output expected). Nothing committed.

## 2026-11-15 review of session L's bench mode (5128b56), merged (for L: one change in your file)

- Reviewed `ps_backend.py`, `ce_owner.py`, the `sweepd.py` / `bench.py` / `hal/base.py` changes: consistent with the
  RTL. `release_pl_pins` (pin_owner = 0 plus abort) is what the pin mux expects; the I2C pins follow within one
  ADS1115 transaction (a few hundred microseconds) because `i2c_pl` only changes while the reader is idle.
- Changed in `ce_owner.py` (+ test): the probe now asks the core's `VERSION` once. Your check used the software's
  regmap only, so with the map 1.0 bitstream of the first boot image and a newer checkout it reported "engine owns
  CE" although that bitstream has no CE mux.
- No RTL change needed. When the sweeping sweepd ends the engine keeps the pins on purpose (CE stays driven);
  documented in `handover-F2.md`.
- Your `tests/conftest.py` (collect GUI garbage) also cures the abort of the GUI smoke test I saw in this worktree.
- Checked: 788 pytest, lint, 10 of 10 testbenches.

## 2026-11-15 standalone DSP modules in `rtl/dsp/` (not in the bitstream)

- User: start the FFT and the RBW filter and other modules needed later, build and test them in isolation,
  document the interface. Done: `fft_r2` (4 .. 4096 points, Hann in the frequency domain), `fir_mac` (complex
  FIR, 64 taps, decimation), `iq_power` (bin power as mantissa / exponent), `adc_ad9226`, `adc_spi_sar`
  (ADC pins to the sample stream). Interfaces and the integration steps: `docs/dsp-modules.md`.
- Each has a bit-exact reference in `sw/sadiy_ebaz/dspref.py`, a testbench `rtl/sim/tb_dsp_*.sv` (vectors from
  `rtl/dsp/gen_dsp.py`, part of `gen.sh`) and an out-of-context build (`rtl/scripts/synth_dsp.sh`): all meet
  100 MHz (worst: FFT +1.60 ns); together about 1300 LUT, 8 BRAM tiles, 10 DSP. Five deliberate faults in FFT
  and FIR are caught.
- The engine and its bitstream are unchanged by this (commit 77c6d61 is what is on main). `sim.sh` compiles
  `dsp/*.sv` too; `test.sh` lints the five tops.
- Not done: integration (list in `dsp-modules.md`), the ADC adapters against real parts (SPI timing is from
  memory of the AD7685 class: verify), anything on the board.

## 2026-11-15 register map 1.2: sample stream format, generator, IF fast path (no ADC needed)

- User: build the fast path without the ADC adapter, with a signal format every ADC option converts to and a
  data generator fed by software. Done: stream format (valid, signed 16 bit, ovr; spec 8b), `sample_gen.sv`
  (4096-sample pattern RAM written by the PS), `if_power.sv` (NCO, mixer, 3-stage CIC by R, power sum as
  mantissa / exponent, over-range in result bit 30; spec 8c), `nco_rom.sv` (generated). `DET_CFG.mode / stream`,
  `GEN_*`, `IF_*` registers. `det_ext_data` is now two's complement and has `det_ext_ovr`.
- Python: `sw/sadiy_ebaz/ifpath.py` is the bit-exact reference; the PL model uses it; `tb_if` compares RTL and
  reference word for word (3 scenarios pass; 5 deliberate faults caught, a 1 LSB phase increment error is below
  the table resolution). Bring-up stage `if` does the same comparison on the board.
- Not done: sweepd does not use the IF path yet; no FFT, no FIR after the CIC; no ADC adapter (AD9226 pins are
  still open). Nothing of this has run on the board.

## 2026-11-14 register map 1.1: ADS1115 reader in the PL, CE, register-only sweepd platform (for L: read)

- User: implement what is missing so sweepd runs, and read the detector in the PL (no software in the loop), keep
  PS push for bring-up. First board run of map 1.0 before this: 57 checks passed (`docs/ebaz-pl-measurements.md`).
- RTL: `ads1115_reader.sv` (I2C master, single shot per sample) = `DET_CFG.src = 3`; `ADC_CFG`, `ADC_I2C_DIV`,
  `ADC_T_CONV_US`, `ADC_STAT`, `ADF_PINS.ce`; CE and the I2C pins now go through `pin_mux` (PS I2C0 keeps the
  bus unless the engine owns the pins and src = 3). VERSION = 0x00010001. Spec sections 8a and 9.
- Built: WNS +1.91 ns, 1172 LUT (6.7 %), 1374 FF (3.9 %), 8.5 BRAM tiles (14 %), 0 critical warnings.
  **PS7 unchanged**: the new `ebaz_sadiy.bit.bin` loads at runtime on the current image, or put the new XSA /
  bitstream into BOOT.BIN (L).
- Software: `sw/sadiy_ebaz/platforms/ebaz_pl.py` (+ alias `ebaz.py`), `RegOffload.send_words / read_detector /
  configure_adc / set_ce / estimated_s`, `OffloadSweep` re-uploads after single actions. `sweepd --platform ebaz`
  on hardware now starts this backend (was: exit). No bench mode on EBAZ hardware yet (bench = None).
  L: I changed `src/sadiy/server/sweepd.py` (main) and `tests/test_gen_diagrams.py` (the "refuses ebaz" test now
  checks a clean failure without the board). S5's PS-only backend is no longer needed for sweeps.
- Verified: `test.sh` (723 pytest, lint, 5 of 5 testbenches incl. new `tb_adc`; 4 deliberate RTL faults in the
  reader are caught). Not verified: anything of this on the board (I2C levels and timing with the real ADS1115,
  CE with the adapter's jumper, sweepd end to end).
- Board: `rtl/scripts/make_bringup_pkg.sh`, then `./run.sh adc`, then `./sweepd.sh`.

## 2026-11-14 board bring-up script (user connected board + logic analyzer)

- `sw/tools/pl_bringup.py` (stages ident regs gen push owner ctrl lock; spi att for the LA), packaged by
  `rtl/scripts/make_bringup_pkg.sh` into `build/bringup-pkg/` with `run.sh`. Tests: `sw/tests/test_pl_bringup.py`
  (correct model passes, wrong results / lock flags / foreign core are detected). Usage: `handover-F2.md`.
  Not run on the board yet. Results go into `docs/ebaz-pl-measurements.md`.

## 2026-11-14 adapter LCD (ST7789), keys, LEDs for Linux, no PL logic (for session L: action needed)

- User: the LCD is a Sitronix ST7789, Linux should drive it, PL resources not wanted. Done in `rtl/fpga/`: PS SPI1 on
  EMIO (SCLK, MOSI, SS0 -> pads R19, P20, T20), EMIO GPIO 8 = `lcd_dc` (R18), 9 = `lcd_res` (N17). Linux GPIO lines
  62 / 63 (54 + n). LUT count unchanged (993), timing met (WNS +2.99 ns), pins placed on the right balls.
- Same day, user: keys and LEDs also for Linux. Adapter LEDs = EMIO 10..12 (Linux lines 64..66, OBUFT), keys = EMIO
  13..17 (lines 67..71, raw active-low pad level); `adapter_ui.sv` removed, no PL logic. EMIO width 16 -> 18. LUT 996,
  WNS +2.87 ns, pins verified in the placed IO report.
- **PS7 now differs from your Phase 1 by four keys:** `PCW_SPI1_PERIPHERAL_ENABLE=1`, `PCW_SPI1_SPI1_IO=EMIO`,
  `PCW_GPIO_EMIO_GPIO_WIDTH=18`, `PCW_GPIO_EMIO_GPIO_IO=18`. `check_ps7.sh` reports exactly these. Your boot image (FSBL / ps7_init / device tree) needs the same change, plus
  SPI1_MISO_I = 0 and SPI1_SS_I = 1 tie-offs (and the GPIO_0 port 18 bits wide), then an XSA and PetaLinux rebuild. Details, device-tree snippet and
  risks (panel size / RAM offset unknown): `docs/lcd-st7789.md`. Not tested on the board.

## 2026-11-14 adapter board: display, keys, LEDs for the PL (for session L: please read)

- User photo `docs/20261114_134742.heic` (main checkout) = HelloFPGA adapter "EBAZ4205_ZJB05". Its right-hand 2x10
  connector carries all 14 DATA2 control balls plus M19, N20, P18, M17 (DATA3), GND and 3V3. Table:
  `docs/pinmap.md`. Row 3 left reads "U20" on the silk but must be J20 (U20 is KEY3): verify on the board.
- New in `rtl/fpga/`: `constraints/adapter_ui.xdc` (LCD CS T20, DC R18, SCL R19, SDA P20, RES N17 (later moved to PS SPI1 / EMIO, see above); KEY1..5 T19, P19,
  U20, U19, V20 with pull-up; LED1..3 H18, K17, E19), `adapter_ui.sv`, ports in `ebaz_sadiy_top.sv`. Not driven yet.
  Rebuilt: all 13 pins placed on these balls, timing unchanged (WNS +3.36 ns), 0 critical warnings.
- These pins are NOT in `rtl/vivado/pins.toml` (the DATA1..3 connector pin numbers are not known). L: add them there
  when known, or tell me to keep them in `adapter_ui.xdc`. Your Phase 1 design is unaffected.
- CONFLICT: with this adapter H18, K17, E19 (LEDs), H16 / H17 (UART header), D19, C20, B19, F19 (HDMI) and D18
  (buzzer) are wired on the adapter, and all are planned `adc_*` balls on DATA1. The AD9226 cannot use DATA1 on this
  adapter. Free balls on the right connector: J18, M19, N20, P18, M17.

## 2026-11-14 F1 + F2 finished

Done
- Spec `docs/rtl-spec.md` (behaviour, register rules, how to change things: section 12). Handovers:
  `docs/handover-F1.md` (Python contracts, for S5 / S7 / S13), `docs/handover-F2.md` (build, load, what to measure).
- Register map `rtl/regmap/regmap.toml` v1.0 and generator `gen_regs.py` -> `axil_regs.sv`, `regs.py`, `regs.h`, `regmap.md`.
- RTL `rtl/src/`: `sadiy_top`, `sweep_seq`, `adf4351_spi`, `pe4302_mbb`, `det_sampler`, `pin_mux`, `sdp_ram`.
- Testbenches `rtl/sim/tb_*.sv` (4) and golden vectors from the Python drivers and model (`rtl/sim/vectors/`).
- Python (F1): `sw/sadiy_ebaz/` (contracts, `PlModel`, `RegOffload`, `OffloadSweep`, `platforms/fake_pl`), contract
  tests in `sw/tests/`, seam 1 in `core/sweep.py`, `server/sweepd.py`, `pyproject.toml`, `.gitignore`.
- Vivado: scripts in `rtl/fpga/`, project generated at `/media/patrik/Workspaces/HW/Vivado/EBAZ_SAdiy`.
  From EBAZ_extender only the PS7 settings and the Ethernet part (MII on EMIO, MDIO, 25 MHz PHY clock,
  constraints) were taken; no CAN, display, keys, LEDs, AXI GPIO or ILA.

Verified (run today)
- `rtl/scripts/test.sh`: generated files current, pytest 642 passed, verilator lint clean, xsim 4 of 4 testbenches pass.
  `tb_sweep` compares SPI words and results with the Python model's vectors. Breaking the RTL on purpose in
  9 ways made a testbench fail each time.
- `rtl/scripts/build_bit.sh`: WNS +3.36 ns, WHS +0.04 ns at 100 MHz; 992 LUT (5.6 %), 1181 FF (3.4 %),
  8.5 BRAM tiles (14 %), 0 DSP; 0 critical warnings. Outputs in `zynq-ebaz/build/fpga/` (git-ignored):
  `ebaz_sadiy.bit`, `ebaz_sadiy.bit.bin`, `ebaz_sadiy.xsa`, reports, `summary.txt`.
- `check_ps7.sh`: PS7 settings identical to L's Phase 1 (509 keys). `check_pins.sh`: pin snapshot identical to L's XDC.

Not verified
- Nothing has run on the board: runtime load of `ebaz_sadiy.bit.bin`, register access through UIO, the pins.
- ADF4351 timing on real hardware (SPI at 10 MHz, lock times). The timing register reset values are guesses.
- `Adf4351.registers()` contents are still unchecked against the datasheet (repo-wide open point, not RTL).

Open points / decisions for the user
- Merge: `git merge rtl` in the main checkout unblocks session L's S5 / S7 / S13 (sync point P1).
- L's `pins.toml` / XDC are not in this branch yet; the build uses a snapshot (`rtl/fpga/constraints/data2_pins.xdc`)
  until `linux` is merged, then the master file automatically.
- F3 (Stage B numerics) not started.

Scripts (`rtl/scripts/`, all take no arguments unless noted)
| Script | Does |
|---|---|
| `gen.sh [--check]` | regenerate register files and golden vectors (or check they are current) |
| `sim.sh [tb ...]` | xsim testbenches; `SIM_GUI=1 sim.sh tb_sweep` opens waveforms |
| `test.sh [--no-sim]` | gen check, pytest, lint, all testbenches |
| `create_project.sh [--force]` | create the Vivado project |
| `build_bit.sh` | synthesis to bitstream, `.bit.bin`, XSA, `summary.txt`; non-zero exit if timing fails |
| `check_pins.sh`, `check_ps7.sh` | compare pins / PS7 settings with session L's files |

## 2026-11-14 start
- Merged main (4c1164f) into `rtl` (fast-forward).
