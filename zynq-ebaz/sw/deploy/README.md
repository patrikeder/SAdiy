# EBAZ4205 Phase 1: boot image with EMIO SPI / I2C / GPIO

Session L, written 2026-11-14. **Nothing here has been run on the board yet.**

## Paths

| What | Where |
|---|---|
| PetaLinux install (2025.2) | `/media/patrik/Workspaces/HW/ZYNQLinux/petalinux_2502/` (`source settings.sh`) |
| Base project (do not touch) | `/media/patrik/Workspaces/HW/ZYNQLinux/ebaz4205_CANI2C/` |
| **New project (session L only)** | `/media/patrik/Workspaces/HW/ZYNQLinux/ebaz4205_sadiy/` |
| Working XSA of the base design | `/media/patrik/Workspaces/HW/Vivado/EBAZ_extender/ebaz4205_wrapper.xsa` |
| Phase 1 XSA (output of `phase1.tcl`) | `zynq-ebaz/build/phase1/ebaz4205_sadiy.xsa` |

`ebaz4205_sadiy` is a copy of the base project without `build/`, `components/` and `images/`.
It reuses the base build's downloads and sstate-cache as local mirrors
(`CONFIG_PRE_MIRROR_URL`, `CONFIG_YOCTO_LOCAL_SSTATE_FEEDS_URL` in its `project-spec/configs/config`),
read-only, so the first build is mostly cache hits. Its hostname is `ebaz4205_sadiy`.
Never run two PetaLinux builds at once.

The PetaLinux project is not in git. The files that matter are mirrored here:

- `petalinux/system-user.dtsi`: copy of `project-spec/meta-user/recipes-bsp/device-tree/files/system-user.dtsi`.
  Edit it here, copy it to the project.

## Steps

1. Generate the Phase 1 XSA (needs Vivado 2025.2, same version as PetaLinux):
   ```
   cd zynq-ebaz
   python3 -I rtl/vivado/gen_xdc.py
   python3 -I rtl/vivado/extract_ps7.py        # only if ps7_base.tcl is missing or the base BD changed
   source <Vivado>/settings64.sh
   vivado -mode batch -source rtl/vivado/phase1.tcl
   ```
   Also check `build/phase1/timing.rpt` and the constraint warnings: the board XDC must apply
   cleanly (the Ethernet PHY is on EMIO and needs it).
2. Import into the new project and build:
   ```
   source /media/patrik/Workspaces/HW/ZYNQLinux/petalinux_2502/settings.sh
   cd /media/patrik/Workspaces/HW/ZYNQLinux/ebaz4205_sadiy
   petalinux-config --get-hw-description=/media/patrik/Workspaces/uC/SAdiy-linux/zynq-ebaz/build/phase1/ebaz4205_sadiy.xsa
   petalinux-build
   bootgen -arch zynq -image images/linux/bootgen.bif -w -o images/linux/BOOT.BIN
   petalinux-package --boot --fsbl --fpga --u-boot --force
   petalinux-package wic          # optional: full SD image
   ```
   The base project's `build_ebaz_CAN.sh` did the same steps (kept as `build_ebaz_sadiy.sh` /
   `rebuild_ebaz_sadiy.sh`; their XSA path still points at the base XSA, edit it first).
3. SD card. **The current card stays the known-good fallback.** Image-copy it first
   (`dd if=/dev/sdX of=backup.img bs=4M status=progress`, check the device name twice), then
   write the new `BOOT.BIN`, `image.ub` / `boot.scr` and rootfs only to a second card, or to the
   same card after the user confirms. No NAND is touched.
4. Check on the board: `sh -s < zynq-ebaz/sw/tools/ebaz_baseline.sh` lists `/dev/spidev*`,
   `/dev/i2c-*`, the gpiochip and the Python modules.

## What the image has to provide

Kernel 6.12.40 (PetaLinux 2025.2) already has spidev (built in), `I2C_CHARDEV`, `GPIO_CDEV`,
`GPIO_SYSFS`, `SPI_CADENCE`, `I2C_CADENCE`, `GPIO_ZYNQ`, UIO, FPGA manager, device-tree overlays
(checked in the base build's `.config`).

Needed by `sweepd` and **not in the rootfs yet** (rootfs packages, need the user's consent, see
`docs/STATUS-linux.md`): `python3-pyzmq`, `python3-numpy`, `python3-spidev`, `libgpiod` (+ tools).
Already in: `python3` (core, json), `i2c-tools`, `openssh-sshd`.

## Device names to expect (verify in S4)

- SPI: `/dev/spidev0.0` (bus 0 = PS SPI0, CS0 = LE).
- I2C: `/dev/i2c-0` (PS I2C0), ADS1115 at 0x48.
- EMIO GPIO: gpiochip of `zynq-gpio`, line = 54 + n, with n = 0..5 PE4302 V1..V6, 6 ADF4351 CE,
  7 ADF4351 LD. (Kernels 6.x also expose a sysfs base such as 512 + 54 + n; use libgpiod.)
- The PE4302 and CE pins are tri-stated until software sets the direction, so the adapter's pull-ups
  give 31.5 dB at boot. Set the value first, then switch the line to output, as `hal` already does
  for the BBB (check this when writing S5).

## Phase 2: load the engine bitstream (S8, runtime part)

The RTL lane builds `ebaz_sadiy.bit.bin` (`../SAdiy-rtl/zynq-ebaz/build/fpga/`, see `docs/handover-F2.md`).
Its PS7 settings equal Phase 1, so the Phase 1 boot image stays. Everything below is **untested on hardware**.

**Register access is `/dev/mem`, not UIO** (user decision 2026-11-14). The image already has `CONFIG_DEVMEM=y`
and `STRICT_DEVMEM` unset, so no kernel or device-tree change is needed. `sw/sadiy_ebaz/devmem.py`
(`DevMemRegs(base=0x43C00000).read/.write`) gives `RegOffload` its `reg_read` / `reg_write`; completion is polled,
there is no interrupt. Never touch `0x43C00000` before the bitstream is loaded: an AXI access to an unconfigured
PL range stalls the CPU.

```
sh zynq-ebaz/sw/deploy/make_engine_package.sh [path/to/ebaz_sadiy.bit.bin]   # -> zynq-ebaz/build/engine-pkg/
scp -r zynq-ebaz/build/engine-pkg root@<ebaz-ip>:/tmp/
ssh root@<ebaz-ip> /tmp/engine-pkg/sadiy_pl_load.sh
```
The script loads the bitstream through `/sys/class/fpga_manager/fpga0` (the rootfs may be read-only, so it points
`firmware_class.path` at the package directory instead of copying to `/lib/firmware`), restarts `eth0` (the PHY clock
and MII pass through the PL and are interrupted during reconfiguration) and prints ID / VERSION read via `/dev/mem`.

Fallback if the Ethernet link does not come back after the runtime load: bake the engine bitstream into a
second boot file (same FSBL and U-Boot) and boot with that; no runtime load is then needed. Already built:
`images/linux/BOOT_engine.BIN` in the PetaLinux project (bitstream of R's 2026-11-14 build). Copy it to the SD card's FAT
partition under the name `BOOT.BIN`, keeping the Phase 1 file as `BOOT_phase1.BIN`. Rebuild it when the bitstream changes.

## Python code is not in the image: deploy it

The rootfs has the interpreter and the modules (python3 3.12, tomllib, pyzmq, numpy, spidev, libgpiod) but none
of the SAdiy code. Init system is sysvinit, so the BBB `sweepd.service` does not apply (S5 writes an init script).

```
sh zynq-ebaz/sw/deploy/deploy_to_board.sh <ebaz-ip>        # tar over ssh into /opt/sadiy
ssh root@<ebaz-ip>
export PYTHONPATH=/opt/sadiy/src:/opt/sadiy/zynq-ebaz/sw
python3 -m sadiy.server.sweepd --sim                        # smoke test without hardware
```
`deploy_to_board.sh` leaves the Qt GUI out (it runs on the PC) and includes `sadiy_ebaz` and `regmap.toml` only when
they exist in the checkout (they come from the `rtl` branch after the merge). The kernel boots the rootfs with `ro`
on the command line; if `/opt` is not writable, run `mount -o remount,rw /` first (check with
`touch /opt/x`). A permanent `rw` would be an image change; say if you want it.
