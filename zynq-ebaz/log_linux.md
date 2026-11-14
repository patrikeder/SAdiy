# log_linux.md: session L (Linux), append-only, newest entry last

Read by session R to check Linux status. Session R logs in `log_rtl.md`.
Format: `## <date time> <topic>`, then facts. Keep entries short. Details live in `docs/STATUS-linux.md`.

Current state in one line (update at each entry): **Image rebuilt 2026-11-14 18:32 from R's engine XSA with LCD/LED/key support, not booted yet. GUI/CLI platform choice (bbb|ebaz) done and dry-tested on the sim, uncommitted. Board boots the Phase 1 image, baseline captured. S8 runtime-load parts prepared (via /dev/mem, no UIO), untested. Phase 1 XSA built, PetaLinux image built (BOOT.BIN, image.ub, wic); nothing tested on the board yet. Waiting for the user to write the SD card and give the board IP.**

---

## 2026-11-14 start of session L
- Worktree `/media/patrik/Workspaces/uC/SAdiy-linux`, branch `linux`, merged main (4c1164f). Nothing committed yet.
- S1 to S3 files written under `zynq-ebaz/` (see `docs/STATUS-linux.md`). R does not need any of them for F1.
- Contract unchanged: signal names `adf4351_clk/dat/le/ce/ld`, `pe4302_v[5:0]`, `i2c_scl/sda` as in appendix D. Master pin list is `rtl/vivado/pins.toml`.

## 2026-11-14 PetaLinux project created
- Project: `/media/patrik/Workspaces/HW/ZYNQLinux/ebaz4205_sadiy/` (copy of `ebaz4205_CANI2C`, PetaLinux 2025.2, kernel 6.12.40). Only session L touches it; one build at a time.
- Rootfs packages enabled with the user's consent: python3-pyzmq, python3-numpy, python3-spidev, libgpiod, libgpiod-tools. Python 3, i2c-tools, openssh were already in.
- Kernel already has spidev, i2c-dev, gpio cdev, UIO, FPGA manager, DT overlays (checked in the base build's .config). No kernel change needed.

## 2026-11-14 Phase 1 Vivado flow runs
- Vivado 2025.2 is at `/media/patrik/Workspaces/Tools/HW/Xilinx/2025.2/Vivado/` (`source settings64.sh`).
- `rtl/vivado/phase1.tcl` ran in batch to an XSA: `zynq-ebaz/build/phase1/ebaz4205_sadiy.xsa` (git-ignored once seam 1 adds `zynq-ebaz/build/`; until then it shows as untracked, do not commit it).
- Timing met (WNS +23.7 ns), 10 LUT, 0 BRAM (Phase 1 has no custom logic). No critical warnings after fixing a stale net name in `ebaz4205_board.xdc`.
- Fixed on the way: `extract_ps7.py` now skips `PCW_MIO_TREE_*` (derived, stored as a list in the BD JSON).
- PS7 in the XSA, verified in the .hwh: FCLK0 100 MHz, EMIO GPIO width 16, EMIO SPI0 and I2C0 on, CAN0/CAN1/UART0 off, M_AXI_GP0 on, IRQ_F2P on, SD0 on MIO, ENET0 on EMIO.
- For R: PS clock and AXI GP0 are in place for Phase 2. The AXI base address will be assigned by L when the engine is added (nothing to hard-code in RTL).

## 2026-11-14 PetaLinux build started
- `ebaz4205_sadiy/build_ebaz_sadiy.sh` (copy in `sw/deploy/petalinux/`): config with the new XSA, build, BOOT.BIN, wic. Log in the L scratchpad.
- Next: SD card on a second card (current card stays the fallback), boot, `ebaz_baseline.sh`, then S4 at the bench with the user.

## 2026-11-14 PetaLinux image built
- Build succeeded (about 10 min, mostly cache hits). Output in `/media/patrik/Workspaces/HW/ZYNQLinux/ebaz4205_sadiy/images/linux/`: `BOOT.BIN` (contains the Phase 1 bitstream), `image.ub`, `boot.scr`, `petalinux-sdimage.wic` (6 GB).
- Device tree checked in `system.dtb`: spi0 okay with `spidev@0` (10 MHz), i2c0 okay (100 kHz), gpio@e000a000, can0/can1 disabled.
- Rootfs manifest has python3 3.12.11, pyzmq 25.1.2, numpy 1.26.4, spidev 3.6, libgpiod 2.1.2 + tools, i2c-tools, openssh-sshd.
- Not tested: boot, Ethernet PHY on EMIO with the new design, device nodes, GPIO line numbers. Needs the SD card and the user.
- The `bootgen` line was removed from `build_ebaz_sadiy.sh` (it ran before `bootgen.bif` existed; `petalinux-package --boot` already writes BOOT.BIN).

## 2026-11-14 S8 runtime part (after R's first bitstream)
- Seen: R's `build/fpga/ebaz_sadiy.bit.bin` (WNS +3.36 ns, 992 LUT, 8.5 BRAM). Header and sync word of the .bit.bin look right for fpga_manager.
- **User decision: register access through /dev/mem, no UIO** (handover-F1/F2 and `reg_offload.py` mention UIO; R: please treat that as outdated, no overlay or interrupt). Kernel has `CONFIG_DEVMEM=y`, no STRICT_DEVMEM. Completion is polled. I tried UIO first and reverted it (kernel fragment, bootargs, overlay); the image has no UIO changes.
- Written: `sw/sadiy_ebaz/devmem.py` (`DevMemRegs`, the `reg_read` / `reg_write` pair for `RegOffload`; base 0x43C00000 from handover-F2), 4 tests on a file backing, `sw/deploy/sadiy_pl_load.sh`, `make_engine_package.sh`, `deploy_to_board.sh` (Python code goes to ~/sadiy over ssh as user petalinux; it is not in the rootfs).
- Rootfs facts: sysvinit (no systemd), python3 3.12 + tomllib + pyzmq + numpy + spidev, root mounted `ro` on the cmdline (remount rw to deploy).
- Risk: runtime reconfiguration interrupts the Ethernet PHY clock and MII (they run through the PL). The script bounces eth0; fallback is a BOOT.BIN with the engine bitstream baked in.
- Still needs the SD card, the board IP and the user. R's checks 1 to 7 in handover-F2 are the S9 list; S9 needs the board and DSLogic.
- Fallback boot file built: `images/linux/BOOT_engine.BIN` (engine bitstream baked in; copy to the SD FAT partition as BOOT.BIN). Image rebuilt without UIO: wic/BOOT.BIN/image.ub current.

## 2026-11-14 merged to main
- `linux` merged into `main` (8a21902) at the user's request: Phase 1 flow, pins.toml, deploy scripts, devmem.py, logs. Session R: `git merge main` to get `pins.toml`/`gen_xdc.py` (your `check_pins.sh` then uses the master file). Session L continues on `linux`.

## 2026-11-14 image review before the first boot
- Logins: root locked (`*`, try root/root on UART), user `petalinux` with empty expiring password: first login on the UART, then ssh; sudo present. Deploy scripts now use user petalinux and ~/sadiy.
- Not in the image: SAdiy code (deploy_to_board.sh), init script for sweepd (S5, sysvinit), python gpiod bindings (C lib and tools only; sysfs GPIO is on), engine bitstream (runtime load or BOOT_engine.BIN).

## 2026-11-14 first boot, baseline captured (S1)
- Board boots the Phase 1 image from SD; baseline in `docs/ebaz-baseline.md` (run by the user, L has no ssh key yet). PL operating, Ethernet up (192.168.88.244, interface enx000a35001e53), spidev0.0, i2c-0, gpiochip0 (base 512, 118 lines) present, Python modules zmq/numpy/spidev/tomllib ok.
- Findings: dev nodes are root-only; no python gpiod/smbus; root fs `ro`; eth0 is renamed by udev (load script fixed). Next: read-only GPIO/I2C checks, then S4 at the bench.

## 2026-11-14 ssh key access, code deployed
- L has key access (petalinux, key ~/.ssh/id_ebaz on the dev PC). `sudo` asks for a password, so L cannot use the root-only /dev nodes, /dev/mem or fpga_manager yet.
- Deployed `src/sadiy` and `config/` to ~/sadiy on the board (rootfs is rw after all). `sweepd --sim` runs there (zmq, numpy ok): 401 points, 0.60 s per sweep, ports 5556/5557. `sadiy_ebaz` not deployed yet (it is on the rtl branch).
- Next: S4 read-only checks (gpioinfo, i2cdetect) need root.

## 2026-11-14 S4 part 1 results
- EMIO readback test ALL PASS (n = 0..6, offsets 54 + n, sysfs 512 + 54 + n); all EMIO lines are inputs after boot; LD reads 0. I2C scan inconclusive (nothing wired, Quick Write unsupported). Details in `docs/ebaz-bringup.md`.
- Pin location on the DATA2 header, SPI frames on the DSLogic and everything with the adapter still need the user at the bench.

## 2026-11-14 platform choice in GUI and CLI (uncommitted on `linux`)
- Requested by the user: BBB or EBAZ selectable in the GUI or on the command line; a command line choice hides the other platform; figures updated.
- New: `src/sadiy/pinmap_ebaz.py` (EBAZ4205 `PinMap`), `platforms.py`, `Layout`/`PinMap`/`BBB` in `pinmap.py`, `ebaz` column and `note_bbb`/`note_ebaz` in `NETS`. `[platform] name` in `config/default.toml`.
- `sweepd --platform bbb|ebaz`: status and bench_open carry `platform`; `Bench(platform=...)`; `fake_backend("ebaz")` has no pin mux. Real hardware on ebaz exits with a message (S5/S7 not done).
- GUI: `sa_gui --platform` fixes the board (selector hidden, other board not drawn); otherwise a selector in the Pins tab that follows sweepd; bench mode is refused when GUI and sweepd disagree. `tools/bringup.py --platform ebaz gpio-map` prints EMIO offsets.
- Figures: `ebaz-wiring` and `ebaz-data1/2/3-pinout` (svg + png) and an EBAZ column in `hw/netlist.md`; `gen_diagrams.py --platform` writes one platform only. Existing BBB/RPi SVGs are byte-identical to before (checked).
- Dry tested: 695 tests pass (new: `test_platforms.py`, `test_platform_gui_smoke.py`, `test_gen_diagrams.py`); real `sweepd --sim --platform ebaz|bbb` over ZeroMQ: status, bench_open, pin reads, attenuator, cross-platform pin ids refused. Nothing run on the board.
- For R: nothing changes in the contract. `pinmap_ebaz.py` copies balls from `pins.toml`; a test fails if they diverge.

## 2026-11-14 image rebuilt for R's new hardware (LCD, LEDs, keys), not booted yet
- R's XSA of 17:09 (`build/fpga/ebaz_sadiy.xsa`, PS7 with SPI1 on EMIO and 18 EMIO GPIO) is now the hardware description of the PetaLinux project (snapshot `xsa/ebaz_sadiy_20261114_1709.xsa`). So **BOOT.BIN contains R's full bitstream** (verified: the whole `.bit.bin` is inside), FSBL/ps7_init match the PS7, and the engine registers at 0x43C00000 exist from boot (the runtime load is only needed to swap bitstreams). Phase 1 files are in `images/phase1-backup/`.
- Device tree (`sw/deploy/petalinux/system-user.dtsi`): `&spi1` with `sitronix,st7789v` (DC line 62, RES line 63, 240x240 guessed, rotate 0), `gpio-leds` (lines 64..66), `gpio-keys` (67..71). Checked in the compiled `system.dtb`. dt-bindings macros are not available in this recipe: numeric values with comments.
- Kernel: new fragment `sw/deploy/petalinux/kernel/user_lcd.cfg` (`FRAMEBUFFER_CONSOLE`, fonts). fbtft ST7789V, `LEDS_GPIO`, `KEYBOARD_GPIO` were already on; checked in the build's `.config`. Console on the LCD is tty1, serial stays ttyPS0.
- `sw/tools/ebaz_lcd_test.py` (info, bars, clear, leds, keys) with 6 tests on a file backing; `docs/ebaz-bringup.md` has the checks to do after booting.
- Phase 1 flow brought in line (`phase1.tcl`: SPI1 EMIO, 18 GPIO, tie-offs; `phase1_top.v`): LCD pads are not wired in Phase 1, so only the engine image shows anything on the panel.
- SD card: copy `BOOT.BIN` and `image.ub` to the FAT partition (boot.scr unchanged); the rootfs (and `~/sadiy`) stays. The new wic is built too.
- Open (needs the board): panel size, colour order (`bgr`), RAM offset, LED polarity. Nothing is tested on hardware.

## 2026-11-14 ADF4351 CE control (BBB and EBAZ)
- Requested by the user: CE support in the Python control scripts on both targets; the RTL may take CE over through an internal mux that ignores the Linux state.
- `drivers/synth_ce.py`, `hal/linux.py` (`SysfsGpio(output=None)` looks at a line without changing it, `direction()`, `zynq_gpio_base()`), `hal/fake.py`, `tools/bringup.py synth-ce`, `sadiy_ebaz/ce_owner.py` (reads `STATUS.ce_engine` if the regmap has it). Details and the request to R in `docs/STATUS-linux.md`.
- Tests: `tests/test_synth_ce.py` (10), `zynq-ebaz/sw/tests/test_ce_owner.py` (2); full suite 728 passed.
