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

## 2026-11-16 build identity in every start (user: "add a version info to the ebaz and other scripts when starting")
- `sadiy/buildinfo.py`: one line (version, commit, branch, uncommitted changes, build time) from a `BUILD_INFO` file next to the copy, else from git, else "build unknown". Printed by `sweepd` (log line `build: ...`, also in `status["build"]`), `cli_client`, `tools/bringup.py` (stderr), `pl_bringup.py` (with the path and version of the `regmap.toml` it reads); the GUI notes the server build in the Device log once per connection and warns on a different commit or a server without build info. Written by `deploy_to_board.sh`, `make_bbb_package.py` and `rtl/scripts/make_bringup_pkg.sh` (R's file: one added line, for R to look at). `BUILD_INFO` is git-ignored.
- Found on the way: a bring-up package on the board (R's `make_bringup_pkg.sh` of 2026-11-15 00:04) carries its own old copy of `sadiy`: its sweepd printed "no bench mode ... the PL engine owns the pins", wording that current code no longer has. With the build line such a copy shows itself at once.
- `sadiy_ebaz/regmap_toml.py` also finds `regmap.toml` next to the package (package layout), so `python pl_bringup.py` works without `run.sh`. `tools/bringup.py` prefers its own checkout's `src` over an installed copy when PYTHONPATH is not set. 806 passed. Not run on the board.
- Open: while a sweep takes seconds (3.47 s with the PL engine) `sweepd` answers commands only between sweeps (`sweepd.py` main loop), the GUI's `log` fetch waits 150 ms: the Device log warning "sweepd sent no log: it may be an older version" can be a false alarm.

## 2026-11-16 day-to-day scripts for the board (user: "scripts to initialize FPGA, start bench mode, sweep etc. from the base directory")
- `zynq-ebaz/sw/board/` -> `~/sadiy/` (flat, by `deploy_to_board.sh`): `fpga.sh` (load the bitstream only when the PL has none or the wrong map; `--force`, `status`), `bench.sh` (`sweepd --bench-only` after `fpga.sh`), `sweep.sh` (PL engine), `sim.sh`, `status.sh` (build, PL, device nodes, sweepd, network), `stop.sh`, `common.sh`; PC side `zynq-ebaz/sw/pc/gui.sh <ip>|--sim`. `sw/tools/ebaz_pl_probe.py` is the read-only PL check (state, ID, map version against the software's `regmap.toml`, pin owner; reads registers only when the FPGA manager says operating).
- `deploy_to_board.sh` also puts `fpga/ebaz_sadiy.bit.bin` (BITSTREAM=<file>, else `zynq-ebaz/build/fpga/` of the checkout, else `../SAdiy-rtl/zynq-ebaz/build/fpga/`) and `fpga/sadiy_pl_load.sh` on the board and prints which bitstream (date, sha256) it took.
- Process matching of `stop.sh` / the "already running" check accepts only python, sudo or env processes (a shell or editor that mentions `sadiy.server.sweepd` in its command line is never touched; found when a test run killed its own parent shell). Tests: `sw/tests/test_board_scripts.py` (probe exit codes, deploy layout through a stub ssh, scripts on a fake PL). 823 passed. Not run on the board.

## 2026-11-16 bench mode worked on the board (user report)
- With the scripts of the entry above (`./bench.sh`, GUI on the PC), map 1.2 loaded: setting ADF4351 frequencies, setting the attenuation and getting ADS1115 values worked. The user gave no numbers; not reported: lock detect at each frequency, measured output frequency and level, PE4302 weights and polarity, DMM comparison of the ADC, patterns, `synth-ce`. Docs updated from this (how-to-start, gui.md, STATUS-linux, CLAUDE.md, README). Open: those details when the user has them, then the first sweep against real RF.

## 2026-11-16 01:11 first sweeps on the board (user pasted the sweepd log; build 9f69785 from main, map 1.2, detector pl)
- Facts from the log: `sweepd --platform ebaz` ran about 9 minutes; sweeps of 30 to 480 MHz, 401 points, 4 averages took 3.0 to 3.5 s; zoom down to 254.89 to 255.11 MHz and back, `set` commands and Stop all accepted; no `unlocked`, `overload`, `safe state` or error line at any point, so lock detect passed on every point of every sweep (no "no lock detect available" either). "No bench mode ... while sweeping" is the expected warning.
- Attenuation moved by itself: `auto_atten` is on by default, so the value set in the GUI is only the start (10 dB), `next_atten_db` then aims the sweep peak at -15 dBm detector level and the log shows 31.5, 22.0, 10.0, 31.5 dB. Without a detector calibration (`cal/*.json`) and with no IF filter the dBm values are placeholders; what was connected to the RF input, and what the trace showed, was not reported.
- Sweep time: 3.0 s for sweeps announced after an attenuation change (31.5 / 22 dB) and 3.45 to 3.54 s for sweeps announced after a start/stop change. 401 points x 4 averages = 1604 reads: 3.0 s is 1.87 ms per read, about the ADS1115 sample time plus lock wait of R's numbers. The extra 0.45 s on a retune is a guess (plan and upload of the point table); `sweepd -vv` logs `sweep n: x s` for every sweep and tells.
- A command takes up to one sweep to show (zoom at 01:14:22 took effect at 01:14:26): known, `sweepd` answers commands only between sweeps; the `on_wait` hook proposed by R is not built.

## 2026-11-17 "No module named 'sadiy.server'" on the board
- Cause (reproduced on the PC with the same message): a shell without PYTHONPATH (env.sh not sourced), cwd `~` which holds the plain folder `~/sadiy`: Python takes it as a namespace package `sadiy` without `server`. The deployed scripts (`./bench.sh` etc., main edfddfc) set PYTHONPATH themselves and work from any directory by path; they were not on the board yet (the board still ran build 9f69785 from before the scripts).
- Added: `zynq-ebaz/sw/board/README.txt` (deployed as `~/sadiy/README.txt`: what to run, where files are, this trap); `status.sh` lists all copies of sadiy under `~` with their build and marks the one in use; `buildinfo.search_paths`: a bring-up package without `BUILD_INFO` no longer borrows the one of `~/sadiy` around it. 827 passed. Not run on the board.

## 2026-11-21 ramp self-test (user: "build a test mode to use the test ramp in the HW ... pass/fail test", agreed with R)
- `sadiy_ebaz/ramp_test.py` + `board/selftest.sh` (`python -m sadiy_ebaz.ramp_test [--model]`, exit 0 PASS / 1 FAIL / 2 not runnable): uploads `points` measure-only entries (W1 = 0xC00: no SPI, skip_lock), `DET_CFG.src = 1`, mode 0, runs several sweeps through `RegOffload` and checks sums against `N_AVG * ((base + (i & 0xFF)) & 0xFFFF)`, STATUS, POINT_COUNT / ENTRY_INDEX / SWEEP_COUNT delta, FIRST_ERR_INDEX = 0, result bits 31:28 = 0, determinism over sweeps and a time window (hardware floor to 2x + 50 ms). A failure names the first wrong index and guesses the cause (stuck, wrong N_AVG/base, shifted). Pin neutral: PE4302.manual and ADF_PINS.ce preset to what the pads show; pins given back and soft_reset at the end. `sweepd --test-ramp` (= `[platform] detector = "test"`, `./sweep.sh --test-ramp`) shows the ramp in the GUI. Spec and criteria: `zynq-ebaz/docs/selftest.md`.
- Interface answers from R (from the RTL, not the board): formula exact for N_AVG 1..4095 and any base; mode must be 0; `i` = result index (measure entries only) restarts per start; skip_lock on every entry means err_lock never; no dummy sweep after table or base change; spi_en = 0 with measure = 1 legal; `pin_owner = 1` needed before `start` (taking and starting in one write is refused); SWEEP_COUNT counts normal ends only; point time = T_MIN + T_SETTLE + N_AVG + 0.11 us. Tests: `sw/tests/test_ramp_test.py` (model: pass; seeded faults fail with the index named), board script tests. Not run on the board.
- Review by R (same day): time floor is a hard lower bound (no case where the engine is faster) and stays; added R's three points: the test writes T_MIN_US / T_SETTLE_US = 20 / 20 itself and restores N_AVG, DET_CFG, DET_TEST, T_*, ADF_PINS, PE4302; a poison sweep (`base ^ 0x5555`) and a different DET_TEST.base per checked sweep (the result memory is not cleared by start, so same-base sweeps or a second `selftest.sh` run could pass on stale data; the last of 3+ sweeps repeats the first base and must equal it); `--fill` (4096 points) and the pin neutrality check (PIN_STATE.pe_out / ce against the pads before the run). 860 tests pass. Not run on the board.

## 2026-11-21 self-test in the GUI (user: "add the test described as larger change to the advanced tab")
- `sweepd` command `selftest` (+ `status.selftest_available`, protocol.py): runs `OffloadSweep.self_test` -> `ramp_test.run_on_core(release=False)` between two sweeps; sweeping continues, the engine keeps its pins (no soft_reset / release, PE4302 and ADF_PINS not written back), N_AVG / DET_CFG / DET_TEST / T_* restored, sweep table re-uploaded at the next sweep. Parameters validated, tests over 30 s refused, verdict in the Device log. `ramp_test.main` now uses `run_on_core(release=True)` too (the CLI is unchanged for the user).
- GUI Advanced tab: box "Ramp self-test" (Sweeps, Wrap run, Full memory, PASS/FAIL label, report). No freeze while the answer waits for the sweep in progress: `SweepClient.request_async` / `AsyncRequest` (own REQ socket, polled by a 200 ms timer), Qt-free `ui/selftest_core.py`. Disconnect cancels. Docs: `docs/gui.md`, `zynq-ebaz/docs/selftest.md`. Tests: `tests/test_selftest_core.py` (incl. a real REP socket), `sw/tests/test_sweepd_selftest.py`, `sw/tests/test_selftest_gui.py`.
- Assumption to confirm with R: with `pin_owner_act = 1` and the engine idle, writing DET_CFG src 3 -> 1 -> 3 (I2C pins handed to the PS and back by `i2c_pl`) and T_MIN / T_SETTLE / DET_TEST / N_AVG is legal and leaves the ADS1115 reader in a state where the next sweep works. Not run on the board.
- R's answer (from the RTL): DET_CFG src 3 -> 1 -> 3 while owned and idle is clean (`i2c_pl` follows only while the reader is not busy, the reader has no init state); writing ADF_PINS.ce with the driven value cannot glitch but flips CE when the pad differs from the driven level, so `run_on_core` now writes it only before the engine owns the pins. Side effects noted: SWEEP_COUNT advances by the test sweeps (nothing in sweepd compares it), the ramp stays in the counters / result memory until the next start, a done raises irq when `irq_en` = 1; the restore is in a `finally`.

