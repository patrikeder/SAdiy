# Out-of-context build of one standalone DSP module: synthesis, place, route, reports.
#   vivado -mode batch -source synth_ooc.tcl -tclargs <top> <out_dir>
# Clock 10 ns (100 MHz) on `clk`. Inputs and outputs are not constrained (the module is meant to sit between
# registers of the engine), so the timing is the register-to-register timing inside the module.
set top [lindex $argv 0]
set out [lindex $argv 1]
set here [file dirname [file normalize [info script]]]
file mkdir $out
set_param general.maxThreads 8
read_verilog -sv [glob $here/*.sv]
synth_design -top $top -part xc7z010clg400-1 -mode out_of_context
create_clock -name clk -period 10.000 [get_ports clk]
opt_design
place_design
route_design
report_utilization -file $out/${top}_utilization.rpt
report_timing_summary -file $out/${top}_timing.rpt
set wns [get_property SLACK [get_timing_paths -max_paths 1 -setup]]
set whs [get_property SLACK [get_timing_paths -max_paths 1 -hold]]
proc used {pat} { set c [get_cells -hier -filter $pat]; return [llength $c] }
set lut  [llength [get_cells -hier -filter {PRIMITIVE_GROUP == LUT || REF_NAME =~ RAM*D* || REF_NAME =~ SRL*}]]
set ff   [llength [get_cells -hier -filter {PRIMITIVE_GROUP == FLOP_LATCH || PRIMITIVE_GROUP == REGISTER}]]
set b36  [llength [get_cells -hier -filter {REF_NAME =~ RAMB36*}]]
set b18  [llength [get_cells -hier -filter {REF_NAME =~ RAMB18*}]]
set dsp  [llength [get_cells -hier -filter {REF_NAME =~ DSP48*}]]
set fh [open $out/${top}_summary.txt w]
puts $fh "$top WNS $wns WHS $whs LUT $lut FF $ff RAMB36 $b36 RAMB18 $b18 DSP $dsp"
close $fh
puts "OOC_DONE $top WNS $wns WHS $whs LUT $lut FF $ff RAMB36 $b36 RAMB18 $b18 DSP $dsp"
