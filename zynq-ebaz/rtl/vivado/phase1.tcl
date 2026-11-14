# Phase 1 build: PS7 (settings of the working EBAZ4205 design) with EMIO SPI0,
# I2C0 and GPIO, FCLK0 = 100 MHz, M_AXI_GP0 and IRQ_F2P enabled for Phase 2.
# No custom RTL except the pin wiring in phase1_top.v.
#
# STATUS: written 2026-11-14 on a machine without Vivado. NOT RUN YET. Expect to
# fix small things (BD pin names) on the first run; see docs/STATUS-linux.md.
#
# Usage (from zynq-ebaz/):
#   source <Vivado install>/settings64.sh
#   vivado -mode batch -source rtl/vivado/phase1.tcl -tclargs [build_dir]
# Output: <build_dir>/ebaz4205_sadiy.xsa (default build_dir = zynq-ebaz/build/phase1)
#
# Prerequisites: python3 -I rtl/vivado/gen_xdc.py && python3 -I rtl/vivado/extract_ps7.py

set here [file dirname [file normalize [info script]]]
set build [expr {$argc > 0 ? [lindex $argv 0] : [file normalize "$here/../../build/phase1"]}]
set part  xc7z010clg400-1
set bdname ebaz4205
set_param general.maxThreads 8

file mkdir $build
create_project -force phase1 $build/prj -part $part
create_bd_design $bdname

# ---- PS7: base settings, then Phase 1 overrides ----
set ps [create_bd_cell -type ip -vlnv xilinx.com:ip:processing_system7:5.5 processing_system7_0]
source $here/ps7_base.tcl
set_property -dict $ps7_base $ps

set_property -dict [list \
  CONFIG.PCW_FPGA0_PERIPHERAL_FREQMHZ {100} \
  CONFIG.PCW_GPIO_EMIO_GPIO_WIDTH {16} \
  CONFIG.PCW_GPIO_EMIO_GPIO_IO {16} \
  CONFIG.PCW_CAN0_PERIPHERAL_ENABLE {0} \
  CONFIG.PCW_CAN1_PERIPHERAL_ENABLE {0} \
  CONFIG.PCW_UART0_PERIPHERAL_ENABLE {0} \
] $ps
# Kept from the base: SD0 on MIO (boot), UART1 on MIO 24..25 (console), ENET0 MII on
# EMIO with FCLK1 = 25 MHz as PHY clock, SPI0 / I2C0 / GPIO on EMIO, M_AXI_GP0, IRQ_F2P.

# ---- external ports ----
make_bd_intf_pins_external [get_bd_intf_pins $ps/DDR]
make_bd_intf_pins_external [get_bd_intf_pins $ps/FIXED_IO]
set_property name DDR [get_bd_intf_ports DDR_0]
set_property name FIXED_IO [get_bd_intf_ports FIXED_IO_0]

make_bd_intf_pins_external [get_bd_intf_pins $ps/GPIO_0]
set_property name emio [get_bd_intf_ports GPIO_0_0]
make_bd_intf_pins_external [get_bd_intf_pins $ps/MDIO_ETHERNET_0]
set_property name enet0_mdio [get_bd_intf_ports MDIO_ETHERNET_0_0]

proc ext_out {pin port {w 1}} {
  set p [create_bd_port -dir O -from [expr {$w-1}] -to 0 $port]
  connect_bd_net [get_bd_pins $pin] $p
}
proc ext_in {pin port {w 1}} {
  set p [create_bd_port -dir I -from [expr {$w-1}] -to 0 $port]
  connect_bd_net [get_bd_pins $pin] $p
}

# SPI0 (ADF4351): MOSI, SCLK, SS0 out. MISO tied low, SS_I tied high (master).
ext_out processing_system7_0/SPI0_SCLK_O spi_sclk_o
ext_out processing_system7_0/SPI0_MOSI_O spi_mosi_o
ext_out processing_system7_0/SPI0_SS_O   spi_ss_o
set c0 [create_bd_cell -type ip -vlnv xilinx.com:ip:xlconstant:1.1 const0]
set_property -dict [list CONFIG.CONST_VAL {0} CONFIG.CONST_WIDTH {1}] $c0
set c1 [create_bd_cell -type ip -vlnv xilinx.com:ip:xlconstant:1.1 const1]
set_property -dict [list CONFIG.CONST_VAL {1} CONFIG.CONST_WIDTH {1}] $c1
connect_bd_net [get_bd_pins const0/dout] [get_bd_pins $ps/SPI0_MISO_I]
connect_bd_net [get_bd_pins const1/dout] [get_bd_pins $ps/SPI0_SS_I]

# I2C0 (ADS1115): split open-drain signals, IOBUFs are in phase1_top.v
ext_in  processing_system7_0/I2C0_SCL_I i2c0_scl_i
ext_out processing_system7_0/I2C0_SCL_O i2c0_scl_o
ext_out processing_system7_0/I2C0_SCL_T i2c0_scl_t
ext_in  processing_system7_0/I2C0_SDA_I i2c0_sda_i
ext_out processing_system7_0/I2C0_SDA_O i2c0_sda_o
ext_out processing_system7_0/I2C0_SDA_T i2c0_sda_t

# ENET0 MII on EMIO, same wiring as the working design: RXD[3:0] zero-extended to 8 bit,
# TXD[3:0] sliced from 8 bit, FCLK1 (25 MHz) is the PHY clock.
ext_in  processing_system7_0/ENET0_GMII_RX_CLK ENET0_GMII_RX_CLK_0
ext_in  processing_system7_0/ENET0_GMII_RX_DV  ENET0_GMII_RX_DV_0
ext_in  processing_system7_0/ENET0_GMII_RX_ER  ENET0_GMII_RX_ER_0
ext_in  processing_system7_0/ENET0_GMII_TX_CLK ENET0_GMII_TX_CLK_0
ext_out processing_system7_0/ENET0_GMII_TX_EN  ENET0_GMII_TX_EN_0
set rxd [create_bd_port -dir I -from 3 -to 0 ENET0_GMII_RXD_P]
set cc [create_bd_cell -type ip -vlnv xilinx.com:ip:xlconcat:2.1 rxd_concat]
set_property -dict [list CONFIG.NUM_PORTS {2} CONFIG.IN0_WIDTH {4} CONFIG.IN1_WIDTH {4}] $cc
set z4 [create_bd_cell -type ip -vlnv xilinx.com:ip:xlconstant:1.1 zero4]
set_property -dict [list CONFIG.CONST_VAL {0} CONFIG.CONST_WIDTH {4}] $z4
connect_bd_net $rxd [get_bd_pins rxd_concat/In0]
connect_bd_net [get_bd_pins zero4/dout] [get_bd_pins rxd_concat/In1]
connect_bd_net [get_bd_pins rxd_concat/dout] [get_bd_pins $ps/ENET0_GMII_RXD]
set txd [create_bd_port -dir O -from 3 -to 0 ENET0_GMII_TXD_P]
set sl [create_bd_cell -type ip -vlnv xilinx.com:ip:xlslice:1.0 txd_slice]
set_property -dict [list CONFIG.DIN_WIDTH {8} CONFIG.DIN_FROM {3} CONFIG.DIN_TO {0} CONFIG.DOUT_WIDTH {4}] $sl
connect_bd_net [get_bd_pins $ps/ENET0_GMII_TXD] [get_bd_pins txd_slice/Din]
connect_bd_net [get_bd_pins txd_slice/Dout] $txd
set phy [create_bd_port -dir O -type clk enet0_phy_clk]
set_property CONFIG.FREQ_HZ 25000000 $phy
connect_bd_net [get_bd_pins $ps/FCLK_CLK1] $phy

# ---- fabric clock, AXI GP0 (unused until Phase 2) and IRQ_F2P ----
connect_bd_net [get_bd_pins $ps/FCLK_CLK0] [get_bd_pins $ps/M_AXI_GP0_ACLK]
set irq0 [create_bd_cell -type ip -vlnv xilinx.com:ip:xlconstant:1.1 irq_zero]
set_property -dict [list CONFIG.CONST_VAL {0} CONFIG.CONST_WIDTH {1}] $irq0
connect_bd_net [get_bd_pins irq_zero/dout] [get_bd_pins $ps/IRQ_F2P]

validate_bd_design
save_bd_design

# ---- sources, constraints, implementation ----
set bdfile [get_files $bdname.bd]
generate_target all $bdfile
add_files -norecurse $here/phase1_top.v
add_files -fileset constrs_1 -norecurse \
  $here/constraints/ebaz4205.xdc $here/constraints/ebaz4205_board.xdc
set_property top phase1_top [current_fileset]
update_compile_order -fileset sources_1

launch_runs impl_1 -to_step write_bitstream -jobs 8
wait_on_run impl_1
if {[get_property PROGRESS [get_runs impl_1]] ne "100%"} {
  error "implementation failed, see $build/prj/phase1.runs/impl_1"
}
open_run impl_1
report_utilization -file $build/utilization.rpt
report_timing_summary -file $build/timing.rpt
write_hw_platform -fixed -include_bit -force $build/ebaz4205_sadiy.xsa
puts "XSA: $build/ebaz4205_sadiy.xsa"
