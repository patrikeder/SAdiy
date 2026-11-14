# Builds the bitstream of the existing project EBAZ_SAdiy: synth_1, impl_1 through write_bitstream
# (8 jobs), then reports, XSA, .bit.bin and summary.txt in the output directory.
#
# Usage (batch):  vivado -mode batch -source build.tcl      (normally via rtl/scripts/build_bit.sh)
# Environment:
#   SADIY_VIVADO_DIR  project directory (default /media/patrik/Workspaces/HW/Vivado/EBAZ_SAdiy)
#   SADIY_FPGA_OUT    output directory (default <zynq-ebaz>/build/fpga)
# Output: ebaz_sadiy.bit, ebaz_sadiy.xsa, ebaz_sadiy.bit.bin, utilization.rpt, timing_summary.rpt,
#         summary.txt.
# Exit code: 0 only if the run completed, WNS >= 0, WHS >= 0 and the bitstream exists
# (the .bit.bin is reported in summary.txt; a missing .bit.bin is not an error).

set_param general.maxThreads 8
set jobs 8

set here  [file dirname [file normalize [info script]]]
set ebaz  [file normalize $here/../..]
set repo  [file normalize $ebaz/..]
set pname EBAZ_SAdiy
if {[info exists ::env(SADIY_VIVADO_DIR)] && $::env(SADIY_VIVADO_DIR) ne ""} {
  set pdir $::env(SADIY_VIVADO_DIR)
} else {
  set pdir /media/patrik/Workspaces/HW/Vivado/EBAZ_SAdiy
}
if {[info exists ::env(SADIY_FPGA_OUT)] && $::env(SADIY_FPGA_OUT) ne ""} {
  set out $::env(SADIY_FPGA_OUT)
} else {
  set out $ebaz/build/fpga
}
file mkdir $out

proc fail {msg} {
  puts "BUILD FAILED: $msg"
  exit 1
}

if {![file exists $pdir/$pname.xpr]} { fail "project $pdir/$pname.xpr missing (run create_project first)" }
open_project $pdir/$pname.xpr

# ---- synthesis and implementation ----
reset_run synth_1
launch_runs synth_1 -jobs $jobs
wait_on_run synth_1
if {[get_property PROGRESS [get_runs synth_1]] ne "100%" || ![string match "*Complete*" [get_property STATUS [get_runs synth_1]]]} {
  fail "synthesis failed, see $pdir/$pname.runs/synth_1/runme.log"
}
reset_run impl_1
launch_runs impl_1 -to_step write_bitstream -jobs $jobs
wait_on_run impl_1
if {[get_property PROGRESS [get_runs impl_1]] ne "100%" || ![string match "*Complete*" [get_property STATUS [get_runs impl_1]]]} {
  fail "implementation failed ([get_property STATUS [get_runs impl_1]]), see $pdir/$pname.runs/impl_1/runme.log"
}

# ---- artifacts ----
open_run impl_1
set bit_src [lindex [glob -nocomplain $pdir/$pname.runs/impl_1/*.bit] 0]
set have_bit [expr {$bit_src ne "" && [file exists $bit_src]}]
if {$have_bit} {
  file copy -force $bit_src $out/ebaz_sadiy.bit
}
report_utilization    -file $out/utilization.rpt
report_timing_summary -file $out/timing_summary.rpt -delay_type min_max -max_paths 10
set xsa_ok 1
if {[catch {write_hw_platform -fixed -include_bit -force $out/ebaz_sadiy.xsa} err]} {
  puts "XSA export failed: $err"
  set xsa_ok 0
}

# .bit.bin for the Linux fpga_manager
set binfile $out/ebaz_sadiy.bit.bin
file delete -force $binfile
set bin_msg "not produced"
if {$have_bit} {
  set bif [open $out/ebaz_sadiy.bif w]
  puts $bif "all:\n\{\n  $out/ebaz_sadiy.bit\n\}"
  close $bif
  set bootgen [file join [file dirname [file normalize [info nameofexecutable]]] bootgen]
  if {![file executable $bootgen]} { set bootgen bootgen }
  if {[catch {exec $bootgen -image $out/ebaz_sadiy.bif -arch zynq -process_bitstream bin -w on 2>@1} bgout]} {
    set bin_msg "bootgen FAILED: [string map {"\n" " "} $bgout]"
  } elseif {[file exists $binfile]} {
    set bin_msg "ok ([file size $binfile] bytes)"
  } else {
    set cand [glob -nocomplain $out/*.bin]
    set bin_msg "bootgen ran but $binfile not found (found: $cand): [string map {"\n" " "} $bgout]"
  }
}

# ---- numbers for summary.txt ----
proc stat {name} { return [get_property STATS.$name [get_runs impl_1]] }
set wns [stat WNS]; set tns [stat TNS]; set whs [stat WHS]; set ths [stat THS]
proc util_line {rpt key} {
  # "| Slice LUTs* | 1234 | 0 | 0 | 17600 | 7.01 |" -> "1234 / 17600 (7.01 %)"
  foreach l [split $rpt "\n"] {
    if {[regexp "^\\|\\s*[string map {* \\*} $key]\\s*\\|\\s*(\\S+)\\s*\\|\\s*\\S+\\s*\\|\\s*\\S+\\s*\\|\\s*(\\S+)\\s*\\|\\s*(\\S+)\\s*\\|" $l -> used avail pct]} {
      return "$used / $avail ($pct %)"
    }
  }
  return "n/a"
}
set fh [open $out/utilization.rpt r]; set urpt [read $fh]; close $fh
set ncw 0
foreach lg [glob -nocomplain $pdir/$pname.runs/*/runme.log] {
  set fh [open $lg r]; set txt [read $fh]; close $fh
  set n [llength [regexp -all -inline -line {^CRITICAL WARNING:} $txt]]
  puts "critical warnings in [file tail [file dirname $lg]]: $n"
  incr ncw $n
}
set commit "unknown"
catch {
  set commit [string trim [exec git -C $repo rev-parse --short HEAD]]
  if {[string trim [exec git -C $repo status --porcelain -- $ebaz/rtl]] ne ""} { append commit " (rtl/ has uncommitted changes)" }
}
set sf [open $out/summary.txt w]
puts $sf "EBAZ_SAdiy build summary"
puts $sf "date:      [clock format [clock seconds] -format {%Y-%m-%d %H:%M:%S}]"
puts $sf "git:       $commit (worktree $repo)"
puts $sf "project:   $pdir/$pname.xpr"
puts $sf "WNS:       $wns ns   TNS: $tns ns"
puts $sf "WHS:       $whs ns   THS: $ths ns"
puts $sf "LUT:       [util_line $urpt {Slice LUTs}]"
puts $sf "FF:        [util_line $urpt {Slice Registers}]"
puts $sf "BRAM tile: [util_line $urpt {Block RAM Tile}]"
puts $sf "DSP:       [util_line $urpt {DSPs}]"
puts $sf "critical warnings (all runs, runme.log): $ncw"
puts $sf "bitstream: [expr {$have_bit ? "$out/ebaz_sadiy.bit" : "MISSING"}]"
puts $sf "xsa:       [expr {$xsa_ok ? "$out/ebaz_sadiy.xsa" : "FAILED"}]"
puts $sf "bit.bin:   $bin_msg"
close $sf

# ---- verdict ----
set bad {}
if {!$have_bit} { lappend bad "bitstream missing" }
if {$wns eq "" || $wns < 0} { lappend bad "WNS $wns < 0" }
if {$whs eq "" || $whs < 0} { lappend bad "WHS $whs < 0" }
if {!$xsa_ok} { lappend bad "XSA export failed" }
close_project
if {[llength $bad] > 0} { fail [join $bad "; "] }
puts "BUILD OK: $out"
exit 0
