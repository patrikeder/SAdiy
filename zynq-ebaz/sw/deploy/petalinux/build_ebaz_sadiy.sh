#! /bin/bash
# Full build of the SAdiy Phase 1 image. XSA comes from zynq-ebaz/rtl/vivado/phase1.tcl.
XSA=${XSA:-/media/patrik/Workspaces/uC/SAdiy-linux/zynq-ebaz/build/phase1/ebaz4205_sadiy.xsa}
cd "$(dirname "$0")"
source ../petalinux_2502/settings.sh
petalinux-config --get-hw-description="$XSA" --silentconfig || exit 1
petalinux-build || exit 1
petalinux-package --boot --fsbl --fpga --u-boot --force
petalinux-package wic
