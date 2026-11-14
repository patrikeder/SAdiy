# Creates the Vivado project EBAZ_SAdiy (project mode, GUI-openable) for the SAdiy engine.
#
# Usage (batch):  vivado -mode batch -source create_project.tcl [-tclargs force]
#   normally via rtl/scripts/create_project.sh [--force]
# Environment:
#   SADIY_VIVADO_DIR   project directory (default /media/patrik/Workspaces/HW/Vivado/EBAZ_SAdiy)
#   SADIY_RTL_SRC_DIR  directory with the engine RTL (default <worktree>/zynq-ebaz/rtl/src); also
#                      accepted as a second tclarg after `force`/`noforce`, e.g. for a stub test
# Refuses to touch an existing project unless the tclarg `force` is given.
# RTL sources and ebaz_sadiy_top.sv are added BY REFERENCE: the repo stays the source of truth.

set_param general.maxThreads 8

set here   [file dirname [file normalize [info script]]]          ;# .../zynq-ebaz/rtl/fpga
set rtl    [file normalize $here/..]
set ebaz   [file normalize $here/../..]
set part   xc7z010clg400-1
set pname  EBAZ_SAdiy

set force 0
if {[llength $argv] > 0 && [lindex $argv 0] eq "force"} { set force 1 }
if {[info exists ::env(SADIY_VIVADO_DIR)] && $::env(SADIY_VIVADO_DIR) ne ""} {
  set pdir $::env(SADIY_VIVADO_DIR)
} else {
  set pdir /media/patrik/Workspaces/HW/Vivado/EBAZ_SAdiy
}
set srcdir $rtl/src
if {[info exists ::env(SADIY_RTL_SRC_DIR)] && $::env(SADIY_RTL_SRC_DIR) ne ""} {
  set srcdir $::env(SADIY_RTL_SRC_DIR)
}
if {[llength $argv] > 1 && [lindex $argv 1] ne ""} { set srcdir [lindex $argv 1] }
set srcdir [file normalize $srcdir]

if {[file exists $pdir/$pname.xpr] && !$force} {
  puts "ERROR: project $pdir/$pname.xpr exists. Use -tclargs force (create_project.sh --force) to recreate it."
  exit 1
}

# ---- constraints: master pin XDC of session L when present, else the snapshot ----
set master $ebaz/rtl/vivado/constraints/ebaz4205.xdc
if {[file exists $master]} {
  set pins $master
  puts "CREATE_PROJECT: pin constraints from the master file $master"
} else {
  set pins $here/constraints/data2_pins.xdc
  puts "CREATE_PROJECT: master $master not found, using the snapshot $pins"
}

# ---- RTL sources ----
set rtl_files [lsort [concat [glob -nocomplain -directory $srcdir *.sv] [glob -nocomplain -directory $srcdir *.v]]]
if {[llength $rtl_files] == 0} { puts "ERROR: no RTL sources in $srcdir"; exit 1 }
if {[file exists $rtl/regmap/axil_regs.sv]} {
  lappend rtl_files $rtl/regmap/axil_regs.sv
} else {
  puts "CREATE_PROJECT: WARNING $rtl/regmap/axil_regs.sv not found (generated file); sadiy_top may not elaborate"
}
puts "CREATE_PROJECT: RTL from $srcdir ([llength $rtl_files] files)"

create_project -force $pname $pdir -part $part

# Block design: PS7 + AXI4-Lite converter + external ports
source $here/bd_ebaz_sadiy.tcl
set bdfile [get_files ebaz_sadiy_bd.bd]
generate_target all $bdfile
# The board top instantiates the BD module directly (no wrapper), as session L's phase1_top does.

# By reference (no -copy_to): files stay in the repo.
add_files -norecurse -fileset sources_1 $rtl_files
add_files -norecurse -fileset sources_1 $here/ebaz_sadiy_top.sv
set_property include_dirs [list $srcdir] [get_filesets sources_1]

add_files -fileset constrs_1 -norecurse $here/constraints/eth.xdc $pins $here/constraints/timing.xdc
set_property top ebaz_sadiy_top [current_fileset]
update_compile_order -fileset sources_1

set_property target_language Verilog [current_project]
close_project
puts "CREATE_PROJECT: done: $pdir/$pname.xpr"
