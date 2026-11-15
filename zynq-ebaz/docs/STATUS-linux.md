# STATUS (session L, Linux) - 2026-11-14

Branch `linux`, worktree `../SAdiy-linux`; everything below is committed on `main` (CE control, `4beac24`). The newer updates further down take precedence over this block.

## Done
- PetaLinux project `/media/patrik/Workspaces/HW/ZYNQLinux/ebaz4205_sadiy/` (not in git; mirrored files in `sw/deploy/petalinux/`). Image built three times; the first (Phase 1) booted on the board on 2026-11-14 (`ebaz-baseline.md`: kernel 6.12.40, Ethernet 100 Mbit, Python with zmq, numpy, spidev).
- S1: `sw/tools/ebaz_baseline.sh` RAN (result in `docs/ebaz-baseline.md`).
- S2: `rtl/vivado/pins.toml`, `gen_xdc.py`, constraints (generated). Tests: `sw/tests/test_pins_xdc.py`. Schematic check: DATA2 consistent; DATA1-13 mismatch (D19 vs D20) to resolve before Phase 4.
- S3: Vivado Phase 1 flow ran (XSA ok, WNS +23.7 ns); image built. Phase 1 files kept in `images/phase1-backup/`.
- S4 (partly): EMIO readback of V1..V6 and CE passes, LD reads 0 with nothing connected (`docs/ebaz-bringup.md`).
- Python deploy: `sw/deploy/deploy_to_board.sh` (sadiy, sadiy_ebaz, `tools/bringup.py`, `sw/tools`); not run yet.

## Next (needs the user at the board or bench)
1. Boot the rebuilt image (copy `BOOT.BIN` and `image.ub`; the rootfs stays): LCD, LEDs, keys (`docs/ebaz-bringup.md`). For a usable LCD: `sudo sh ebaz_lcd_top.sh install` shows `top` on it instead of the login prompt (written 2026-11-15, works on the board).
2. S4 rest: pin locations on DATA2, SPI frames on the logic analyzer, adapter connected, `synth-ce`, PE4302 walk, ADF4351 at 100 MHz, ADS1115.
3. Then S5 (`ebaz-ps` backend, sysvinit script for `sweepd`) and S7 (`ebaz-pl`, `/dev/mem` registers).

## Blockers / questions to R
- None open. (The CE mux asked for below was built by R in register map 1.1, with `pin_owner_act` as the owner bit and `ADF_PINS.ce` as the engine's level; `ce_owner.py` follows that.)

## Update 2026-11-14: platform choice in GUI and CLI
- Done (uncommitted): `sweepd --platform`, GUI Pins tab selector or `sa_gui --platform` (other board hidden), `pinmap_ebaz.py`, EBAZ figures and netlist column, tests. Details in `log_linux.md`.
- Superseded by the 2026-11-15 updates below: R's PL backend sweeps on the real board and `--bench-only` gives Linux the pins; neither has run on the board.

## Update 2026-11-14 (evening): image for R's new hardware
- Image rebuilt from R's engine XSA (SPI1 EMIO, 18 EMIO GPIO), with ST7789 LCD, 3 LEDs and 5 keys in the device tree and the framebuffer console in the kernel. BOOT.BIN (rebuilt 2026-11-15 14:53 from R's XSA of 2026-11-15 00:03) holds the engine bitstream of register map 1.2; the card of 2026-11-14 had map 1.0 (no ADS1115 reader, no CE / I2C mux), with which only `--bench-only` and detector `ps` / `test` work. Not booted yet. Details in `log_linux.md` and `docs/ebaz-bringup.md`.

## Update 2026-11-15: bench mode on the real board
- `sweepd --platform ebaz --bench-only` now works on the board (Pins tab, raw ADF4351 / PE4302 / ADS1115 access, patterns) with Linux owning the pins: `sw/sadiy_ebaz/ps_backend.py`. It hands the pins back from the PL engine if needed. No RTL change required. Not run on the board yet. While `sweepd` sweeps (`--platform ebaz` without `--bench-only`) there is still no bench mode.

## Update 2026-11-14 (late): ADF4351 CE control from Linux, BBB and EBAZ
- Done: `drivers/synth_ce.py` (`SynthCe`: on / off / release / status, flags that the chip lost its registers after a power-down), `python tools/bringup.py [--platform ebaz] synth-ce on|off|release|read [--dry-run] [--pl-owner]` (BBB P9.27, EBAZ DATA2.13 = EMIO 6 = Linux line 60), `sadiy_ebaz/ce_owner.py`, 12 new tests. Dry-run only; nothing run on a board.
- CE is Linux's today (`adf4351_ce` goes straight from EMIO 6 to the pad, `rtl-spec.md`). The user wants the PL able to take it over through an internal mux, with the Linux EMIO state ignored while it does.
- **For R (superseded 2026-11-15, R built the mux in map 1.1 under other names; see the bench update below):** if you add the mux (`ce_pad = engine_owns_ce ? engine_ce : emio_ce`), add a read-only bit **`STATUS.ce_engine`** to `regmap.toml` (1 = the engine's CE reaches the pad). `ce_owner.py` looks for exactly that name; without it Python reports "Linux always". Keep the IOBUF reading the pad, so `emio_tri_i[6]` stays the pad level. Boot default must stay "Linux owns, EMIO tri-stated" (the adapter holds CE high). Say in `rtl-spec.md` whether the owner follows `pin_owner` or has its own bit, and whether the engine drives CE high only during a sweep or all the time.
- Not done: `sweepd` hardware backends do not call `SynthCe` yet (S5/S7); the bench's Pins tab drives CE as an ordinary pin (it knows nothing of the PL owner).
