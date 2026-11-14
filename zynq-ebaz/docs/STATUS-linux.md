# STATUS (session L, Linux) - 2026-11-14

Branch `linux`, worktree `../SAdiy-linux`. Not committed (CLAUDE.md: commit only when asked).

## Done
- Merged main (4c1164f) into `linux`.
- New PetaLinux project `/media/patrik/Workspaces/HW/ZYNQLinux/ebaz4205_sadiy/`, copied from
  `ebaz4205_CANI2C` without build output; local mirrors point at the base build's downloads and
  sstate-cache; `petalinux-config --silentconfig` with the base XSA ran clean (toolchain works). No build run yet.
- S1: `sw/tools/ebaz_baseline.sh` written, syntax-checked, NOT run (needs the board).
- S2: `rtl/vivado/pins.toml`, `gen_xdc.py`, `constraints/ebaz4205.xdc` (generated),
  `constraints/ebaz4205_board.xdc` (Ethernet PHY, copied). Tests: `sw/tests/test_pins_xdc.py` (5 pass).
  Schematic check: DATA2 consistent; DATA1-13 mismatch (D19 vs D20) to resolve before Phase 4.
- S3: Vivado flow RAN (XSA ok, WNS +23.7 ns, 10 LUT) and PetaLinux image BUILT (BOOT.BIN, image.ub, wic). Not booted yet. Files: `rtl/vivado/phase1.tcl`, `phase1_top.v`, `extract_ps7.py` -> `ps7_base.tcl`,
  `sw/deploy/petalinux/system-user.dtsi` (also installed in the new project), `sw/deploy/README.md`.

## Next (needs the user)
1. Write the image to a SECOND SD card (wic or BOOT.BIN+image.ub+boot.scr), keep the current card as fallback.
2. Board IP address after boot (consent for rootfs packages given and applied)
3. Board IP address, to run `ebaz_baseline.sh` (S1) and later the bring-up (S4).
4. S4 bench list: see `docs/ebaz-bringup.md` (to be filled at the bench).

## Blockers / questions to R
- None. R can start F1 now; it needs nothing from L. `pins.toml` and the signal names follow appendix D.
- Phase 1 changes vs the base PS7: FCLK0 50 -> 100 MHz, EMIO GPIO width 4 -> 16, CAN0/CAN1/UART0 EMIO off.
  The base display/CAN nodes are gone from `system-user.dtsi`.


## Update 2026-11-14: platform choice in GUI and CLI
- Done (uncommitted): `sweepd --platform`, GUI Pins tab selector or `sa_gui --platform` (other board hidden), `pinmap_ebaz.py`, EBAZ figures and netlist column, tests. Details in `log_linux.md`.
- Not done: real EBAZ backends in `sweepd` (S5 ebaz-ps, S7 ebaz-pl); `--platform ebaz` works only with `--sim`.

## Update 2026-11-14 (evening): image for R's new hardware
- Image rebuilt from R's engine XSA (SPI1 EMIO, 18 EMIO GPIO), with ST7789 LCD, 3 LEDs and 5 keys in the device tree and the framebuffer console in the kernel. BOOT.BIN holds the engine bitstream. Not booted yet. Details in `log_linux.md` and `docs/ebaz-bringup.md`.

## Update 2026-11-14 (late): ADF4351 CE control from Linux, BBB and EBAZ
- Done: `drivers/synth_ce.py` (`SynthCe`: on / off / release / status, flags that the chip lost its registers after a power-down), `python tools/bringup.py [--platform ebaz] synth-ce on|off|release|read [--dry-run] [--pl-owner]` (BBB P9.27, EBAZ DATA2.13 = EMIO 6 = Linux line 60), `sadiy_ebaz/ce_owner.py`, 12 new tests. Dry-run only; nothing run on a board.
- CE is Linux's today (`adf4351_ce` goes straight from EMIO 6 to the pad, `rtl-spec.md`). The user wants the PL able to take it over through an internal mux, with the Linux EMIO state ignored while it does.
- **For R (contract, nothing is assumed in the RTL yet):** if you add the mux (`ce_pad = engine_owns_ce ? engine_ce : emio_ce`), add a read-only bit **`STATUS.ce_engine`** to `regmap.toml` (1 = the engine's CE reaches the pad). `ce_owner.py` looks for exactly that name; without it Python reports "Linux always". Keep the IOBUF reading the pad, so `emio_tri_i[6]` stays the pad level. Boot default must stay "Linux owns, EMIO tri-stated" (the adapter holds CE high). Say in `rtl-spec.md` whether the owner follows `pin_owner` or has its own bit, and whether the engine drives CE high only during a sweep or all the time.
- Not done: `sweepd` hardware backends do not call `SynthCe` yet (S5/S7); the bench's Pins tab drives CE as an ordinary pin (it knows nothing of the PL owner).
