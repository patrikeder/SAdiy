#! /bin/bash
# Full build of the SAdiy image. Hardware description: session R's engine XSA (PS7 with SPI0, SPI1, I2C0, 18 EMIO GPIO;
# engine and LCD pads in the bitstream), a snapshot in the project's xsa/ directory. XSA=<file> builds from another one,
# for example the Phase 1 XSA (zynq-ebaz/build/phase1/ebaz4205_sadiy.xsa, made by rtl/vivado/phase1.tcl; no LCD pads).
# Also installs system-user.dtsi and the kernel fragment from this directory into the project.
HERE=$(cd "$(dirname "$0")" && pwd)
cd "$HERE"
XSA=${XSA:-$HERE/xsa/ebaz_sadiy_20261114_1709.xsa}
DEPLOY=${DEPLOY:-/media/patrik/Workspaces/uC/SAdiy-linux/zynq-ebaz/sw/deploy/petalinux}
source ../petalinux_2502/settings.sh
if [ -d "$DEPLOY" ]; then
  cp "$DEPLOY/system-user.dtsi" project-spec/meta-user/recipes-bsp/device-tree/files/system-user.dtsi
  cp "$DEPLOY/kernel/user_lcd.cfg" project-spec/meta-user/recipes-kernel/linux/linux-xlnx/user_lcd.cfg
fi
petalinux-config --get-hw-description="$XSA" --silentconfig || exit 1
petalinux-build || exit 1
petalinux-package --boot --fsbl --fpga --u-boot --force
petalinux-package wic
