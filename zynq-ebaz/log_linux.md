# log_linux.md: session L (Linux), append-only, newest entry last

Read by session R to check Linux status. Session R logs in `log_rtl.md`.
Format: `## <date time> <topic>`, then facts. Keep entries short. Details live in `docs/STATUS-linux.md`.

Current state in one line (update at each entry): **Image rebuilt 2026-11-15 14:53 from R's engine XSA of 00:03 (map 1.2) with LCD/LED/key support, new BOOT.BIN not on a card yet. GUI/CLI platform choice (bbb|ebaz) done and dry-tested on the sim, uncommitted. Board boots the Phase 1 image, baseline captured. S8 runtime-load parts prepared (via /dev/mem, no UIO), untested. Phase 1 XSA built, PetaLinux image built (BOOT.BIN, image.ub, wic); nothing tested on the board yet. Waiting for the user to write the SD card and give the board IP.**

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
- `drivers/synth_ce.py`, `hal/linux.py` (R built the CE mux in map 1.1 with other names than requested: `ce_owner.py` now reads `STATUS.pin_owner_act` and needs `ADF_PINS.ce` in the map) (`SysfsGpio(output=None)` looks at a line without changing it, `direction()`, `zynq_gpio_base()`), `hal/fake.py`, `tools/bringup.py synth-ce`, `sadiy_ebaz/ce_owner.py` (reads `STATUS.ce_engine` if the regmap has it). Details and the request to R in `docs/STATUS-linux.md`.
- Tests: `tests/test_synth_ce.py` (10), `zynq-ebaz/sw/tests/test_ce_owner.py` (2); full suite 728 passed.

## 2026-11-15 top on the LCD
- Requested by the user: the login shell on the LCD is unusable (no keyboard, ~30 columns); show `top` continuously instead.
- `sw/tools/ebaz_lcd_top.sh` (install / remove / status / frame / run): swaps the tty1 getty line of `/etc/inittab` for a loop around `top -b -n2` that prints a compact frame (time+load, tasks, CPU, memory, PID %CPU %MEM COMMAND) sized to the console. Runtime change on the SD card's rootfs (no image rebuild); `remove` restores the line. Tests: `sw/tests/test_lcd_top.py` (8, fake `top` in KiB and MiB layouts, install/remove on a copy of inittab). Works on the board (user report 2026-11-15), so the rebuilt image's LCD text console works too.

## 2026-11-15 bench mode on the real EBAZ4205 (PS path)
- Requested by the user: `sweepd --platform ebaz --bench-only` refused to start ("no bench mode on EBAZ4205 hardware yet").
- `sw/sadiy_ebaz/ps_backend.py` (`EbazPsBackend`): EMIO GPIO = sysfs number base+54+n (base found from the 118-line PS chip), `/dev/spidev0.0`, `/dev/i2c-0`, no pin mux, no AIN. `prepare()` runs when bench mode opens: if the FPGA manager says `operating` and the ID register answers, it hands the pins back to Linux (`CTRL.pin_owner = 0` with an abort pulse) when a killed `sweepd` left the engine owning them; otherwise it only warns. `platforms/ebaz.py: build_bench_backend`; `sweepd`: `hardware_backend(cfg, pm)`; `BenchBackend.prepare()` hook; bench refuses `source: ain` on a map without AIN.
- Sweeping (`--platform ebaz` without `--bench-only`) still has no bench: the engine owns the pins while it sweeps. Wiring tests and sweeping are two separate runs of `sweepd`.
- No RTL change is needed: after reset `pin_owner = 0` (PS owns SPI, PE4302, CE, I2C), and LD is read straight from EMIO 7. Tests: `sw/tests/test_ps_backend.py` (15, fake /sys tree and fake register file). Not run on the board.

## 2026-11-15 boot image rebuilt for register map 1.2 (answers R's "for L: new BOOT.BIN")
- The 2026-11-14 BOOT.BIN held R's 17:09 bitstream = map 1.0; the sweep path (`detector = "pl"`) needs map >= 1.1, so docs that said "BOOT.BIN holds the engine bitstream" were incomplete (found by R's alignment check). Fixed in `docs/how-to-start.md`, `STATUS-linux.md`, `ebaz-bringup.md`, `deploy/README.md`.
- Rebuilt with `build_ebaz_sadiy.sh` from `build/fpga/ebaz_sadiy.xsa` of 2026-11-15 00:03 (snapshot `xsa/ebaz_sadiy_20261115_0003.xsa`, now the script's default): config and build succeeded, 8108 of 8249 tasks cached. `ps7_init.c/.h/.tcl` and `ps7_init_gpl.c` are byte-identical to the 17:09 XSA, `system.dtb`, `image.ub` and `boot.scr` unchanged, so only the bitstream in BOOT.BIN changed (checked: a chunk that differs between the two bitstreams is only in the matching BOOT.BIN). `images/linux/system.bit` matches neither XSA's bitstream (dated 2026-11-14 13:00) and is not used by `bootgen.bif` (it takes `project-spec/hw-description/ebaz_sadiy.bit`).
- Old boot files saved in the project's `images/map10-backup/`. Copy `images/linux/BOOT.BIN` (and `image.ub`) to the FAT partition; the rootfs stays. Not booted on the board.

## 2026-11-15 bringup.py synth-ce --pl-owner checks the PL first (R's review point)
- `--pl-owner` opened `/dev/mem` without asking whether a bitstream is loaded; on an unconfigured PL that read stalls the CPU. Now `sadiy_ebaz.devmem.pl_not_ready()` (FPGA manager state, shared with `EbazPsBackend.prepare()`) runs first, before any GPIO line is opened, and the command stops with "PL is <state>: not reading the PL registers". An unreadable state file passes (not a board). Tests: `tests/test_synth_ce.py` (2), `sw/tests/test_ps_backend.py` (1). 791 passed. Not run on the board.

## 2026-11-15 adapter pins in pins.toml (for R: please read; answers R's "L: add them there when known")
- User decision: the adapter's LEDs stay as they are (they can be freed only with a different adapter PCB), so `rtl/vivado/pins.toml` lists them and the AD9226 pins `adc_d[8]` (E19), `adc_d[10]` (H18) and `adc_clk` (K17) have no ball on this adapter. DATA1-15 = `led[0]` (H18), DATA1-20 = `led[1]` (K17), DATA1-18 = `led[2]` (E19). The other AD9226 balls shared with the adapter (H16/H17 UART header, D19/C20/B19/F19 HDMI, D18 buzzer) got a note.
- DATA3 keys and display added: KEY1..5 = T19 P19 U20 U19 V20 = DATA3-18, 15, 17, 20, 19; LCD CS/DC/RES/SCL/SDA = T20 R18 N17 R19 P20 = DATA3-16, 13, 9, 14, 11. Source: the schematic's text layer (ball next to its DATA pin); the same balls are in `BALLS` of `pinmap_ebaz.py`, which came from another source. Not checked by continuity. All new entries are `active = false` (the Phase 1 top level has no such ports; the engine build keeps constraining them in `rtl/fpga/constraints/adapter_ui.xdc`), names equal to the ports there (`led[n]`, `keys[n]`, `lcd_*`), so `gen_pinmap.py` shows them as in use.
- User confirmed on the adapter: the right-hand connector row 3 left (below G19) is J20, not U20; U20 is KEY3. The "verify on the board" notes can go (`docs/pinmap.md`, `gen_pinmap.py`, `log_rtl.md`).
- For R to regenerate (generated or your files, not touched by me): `docs/pinmap.md` and the pin figures (`gen_pinmap.py` needs the Vivado package CSV), `rtl/fpga/constraints/data2_pins.xdc` (its commented DATA1 lines still show adc_d[8], adc_d[10], adc_clk; `check_pins.sh` ignores comments and says identical), `ADC_PROPOSAL` / `DATA1_ON_ADAPTER` in `gen_pinmap.py` if you want the three AD9226 pins marked as unavailable there. Linux side: `pinmap_ebaz.py` (DATA1 roles, new `DATA3_ADAPTER`), the EBAZ Pins tab and `hw/diagrams/ebaz-data1/3-pinout` follow. 791 passed.

