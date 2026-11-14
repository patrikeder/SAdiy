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
