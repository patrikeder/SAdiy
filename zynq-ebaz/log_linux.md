# log_linux.md: session L (Linux), append-only, newest entry last

Read by session R to check Linux status. Session R logs in `log_rtl.md`.
Format: `## <date time> <topic>`, then facts. Keep entries short. Details live in `docs/STATUS-linux.md`.

Current state in one line (update at each entry): **S8 runtime-load parts prepared (via /dev/mem, no UIO), untested. Phase 1 XSA built, PetaLinux image built (BOOT.BIN, image.ub, wic); nothing tested on the board yet. Waiting for the user to write the SD card and give the board IP.**

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
- Written: `sw/sadiy_ebaz/devmem.py` (`DevMemRegs`, the `reg_read` / `reg_write` pair for `RegOffload`; base 0x43C00000 from handover-F2), 4 tests on a file backing, `sw/deploy/sadiy_pl_load.sh`, `make_engine_package.sh`, `deploy_to_board.sh` (Python code goes to /opt/sadiy over ssh; it is not in the rootfs).
- Rootfs facts: sysvinit (no systemd), python3 3.12 + tomllib + pyzmq + numpy + spidev, root mounted `ro` on the cmdline (remount rw to deploy).
- Risk: runtime reconfiguration interrupts the Ethernet PHY clock and MII (they run through the PL). The script bounces eth0; fallback is a BOOT.BIN with the engine bitstream baked in.
- Still needs the SD card, the board IP and the user. R's checks 1 to 7 in handover-F2 are the S9 list; S9 needs the board and DSLogic.
- Fallback boot file built: `images/linux/BOOT_engine.BIN` (engine bitstream baked in; copy to the SD FAT partition as BOOT.BIN). Image rebuilt without UIO: wic/BOOT.BIN/image.ub current.
