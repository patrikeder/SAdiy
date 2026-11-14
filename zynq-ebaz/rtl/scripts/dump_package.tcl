# Dump the package pin table of the target part to CSV: ball, bank, pin function, site (blank for PS / power pins).
# Usage: vivado -mode batch -source dump_package.tcl -tclargs <out.csv>
# Result is committed as rtl/fpga/clg400_pins.csv; gen_pinmap.py reads it (no Vivado needed to regenerate docs).
set out [lindex $argv 0]
link_design -part xc7z010clg400-1 -name pkg
set f [open $out w]
puts $f "ball,bank,function,site"
foreach p [lsort [get_package_pins]] {
  set s [get_sites -of_objects $p -quiet]
  set sn ""
  if {[llength $s]} { set sn [get_property NAME $s] }
  puts $f "[get_property NAME $p],[get_property BANK $p],[get_property PIN_FUNC $p],$sn"
}
close $f
