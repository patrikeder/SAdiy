# RTL lane log (session R)

Worktree `/media/patrik/Workspaces/uC/SAdiy-rtl`, branch `rtl`. Newest entry first. Session L writes
`zynq-ebaz/log_linux.md` in its own worktree. Spec for everything below: `zynq-ebaz/docs/rtl-spec.md`.

## Notes for session L (read this part)

- **User decision 2026-11-14:** session R builds the FPGA hardware for the engine. R's Vivado scripts are in
  `zynq-ebaz/rtl/fpga/` and generate the project `/media/patrik/Workspaces/HW/Vivado/EBAZ_SAdiy`. Your
  `zynq-ebaz/rtl/vivado/**` (Phase 1, `pins.toml`, `gen_xdc.py`) is not touched and `pins.toml` stays the pin
  master. This takes S8's Vivado part from you; the runtime bitstream load and the UIO device tree stay yours.
- The engine design keeps your Phase 1 PS7 settings and EMIO line map (GPIO 0..5 PE4302, 6 CE, 7 LD, SPI0,
  I2C0, ENET0 MII, FCLK0 100 MHz, FCLK1 25 MHz), so a boot image built from your Phase 1 XSA should be able to
  load the engine bitstream at runtime. AXI-lite base of the engine: `0x43C0_0000`, 4 KiB, on M_AXI_GP0;
  interrupt on IRQ_F2P[0].
- The register map differs from plan appendix A / B (generic SPI word table, indirect table / result access,
  PS-pushed detector samples). See `docs/rtl-spec.md` section 11 before starting S7.

## State in one line

**F1 and F2 done and verified in simulation; bitstream built with timing met; nothing run on the board yet. Committed on branch `rtl` (seam commit + zynq-ebaz commit), not pushed, not merged to main.**

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
