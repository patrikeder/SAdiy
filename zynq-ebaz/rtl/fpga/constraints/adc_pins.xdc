# AD9226 module pads: adc_clk (output), adc_d[11:0] and adc_otr (inputs). NOT part of the normal build.
# Added by create_project.tcl only with SADIY_ADC_PADS=1 (which also defines ADC_PADS in the top, so the ports exist).
#
# Status 2026-11-23: PREPARED, NOT VERIFIED. The balls are the DATA1 assignment of rtl/vivado/pins.toml
# (session L's master). On the first adapter these balls are shared with LED1..3 (H18, K17, E19), the UART header
# (H16, H17), the buzzer (D18) and the HDMI port (B19, C20, D19, F19), which adapter_ui.xdc constrains: a build with
# ADC_PADS=1 is only valid with the adapter v2 that has none of those on DATA1 (and with the LED / buzzer / UART /
# HDMI lines removed from adapter_ui.xdc and pins.toml). The order of adc_d[] on the module's header is also not
# known yet (docs/adc-module.md): the adapter wires DATA1 balls to the module header, so changing this mapping later
# means changing only this file and pins.toml. Until then the front end runs on its tie-off / traffic generator
# sources (FE_CFG.src 0 / 1), which need no pads.
set_property -dict {PACKAGE_PIN A20 IOSTANDARD LVCMOS33} [get_ports {adc_d[0]}]    ; # DATA1-5
set_property -dict {PACKAGE_PIN B19 IOSTANDARD LVCMOS33} [get_ports {adc_d[1]}]    ; # DATA1-7
set_property -dict {PACKAGE_PIN B20 IOSTANDARD LVCMOS33} [get_ports {adc_d[2]}]    ; # DATA1-8
set_property -dict {PACKAGE_PIN C20 IOSTANDARD LVCMOS33} [get_ports {adc_d[3]}]    ; # DATA1-9
set_property -dict {PACKAGE_PIN D20 IOSTANDARD LVCMOS33} [get_ports {adc_d[4]}]    ; # DATA1-13
set_property -dict {PACKAGE_PIN D18 IOSTANDARD LVCMOS33} [get_ports {adc_d[5]}]    ; # DATA1-14
set_property -dict {PACKAGE_PIN D19 IOSTANDARD LVCMOS33} [get_ports {adc_d[6]}]    ; # DATA1-16
set_property -dict {PACKAGE_PIN F20 IOSTANDARD LVCMOS33} [get_ports {adc_d[7]}]    ; # DATA1-17
set_property -dict {PACKAGE_PIN E19 IOSTANDARD LVCMOS33} [get_ports {adc_d[8]}]    ; # DATA1-18 (adapter v1: LED3)
set_property -dict {PACKAGE_PIN F19 IOSTANDARD LVCMOS33} [get_ports {adc_d[9]}]    ; # DATA1-19
set_property -dict {PACKAGE_PIN H18 IOSTANDARD LVCMOS33} [get_ports {adc_d[10]}]   ; # DATA1-15 (adapter v1: LED1)
set_property -dict {PACKAGE_PIN H17 IOSTANDARD LVCMOS33} [get_ports {adc_d[11]}]   ; # DATA1-11
set_property -dict {PACKAGE_PIN H16 IOSTANDARD LVCMOS33} [get_ports adc_otr]       ; # DATA1-6
set_property -dict {PACKAGE_PIN K17 IOSTANDARD LVCMOS33 DRIVE 8 SLEW FAST} [get_ports adc_clk]   ; # DATA1-20 (adapter v1: LED2)

# Timing: adc_clk is made in fabric as data (a register of the 100 MHz clock divided by FE_CFG.div) and the data
# lines are taken with a software-chosen phase (FE_CFG.phase), so there is no fixed clock relation for STA to check.
# False paths are the honest constraint (the same reasoning as in timing.xdc for the SPI clock); the capture
# phase is verified on the bench with the traffic generator and the module (docs/adc-module.md).
set_false_path -to   [get_ports adc_clk]
set_false_path -from [get_ports {adc_d[*] adc_otr}]
# First capture register of the data pins into the I/O cells (less pad-to-register delay and a fixed one):
set_property IOB TRUE [get_cells -quiet -hierarchical -filter {NAME =~ *u_fe/u_adc/p1_reg[*]}]
