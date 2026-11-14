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
