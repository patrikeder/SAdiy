# Block design `ebaz_sadiy_bd` for the SAdiy PL sweep engine on the EBAZ4205.
#
# Contents: PS7 (settings of ps7_config.tcl = the working board design + Phase 1 overrides),
# proc_sys_reset, one AXI3 -> AXI4-Lite protocol converter, and external ports. Nothing from the
# EBAZ_extender design beyond the PS7 settings and the Ethernet wiring is used.
#
# Sourced by create_project.tcl inside an open project (needs: a project with part set).
# Port names for DDR / FIXED_IO / Ethernet / emio / SPI0 / I2C0 are those of session L's phase1.tcl,
# so their pin constraints apply unchanged.
#
# Address map: m_axil = 0x43C0_0000 .. 0x43C0_FFFF (64 KiB; the engine decodes the low 12 bits).

set here [file dirname [file normalize [info script]]]
set bdname ebaz_sadiy_bd

create_bd_design $bdname

# ---- PS7: board settings copied from EBAZ_extender, then the SAdiy overrides ----
set ps [create_bd_cell -type ip -vlnv xilinx.com:ip:processing_system7:5.5 processing_system7_0]
source $here/ps7_config.tcl
set_property -dict $ps7_base $ps
set_property -dict $ps7_overrides $ps

# ---- DDR, fixed IO, EMIO GPIO and MDIO interfaces ----
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
proc const_cell {name val w} {
  set c [create_bd_cell -type ip -vlnv xilinx.com:ip:xlconstant:1.1 $name]
  set_property -dict [list CONFIG.CONST_VAL $val CONFIG.CONST_WIDTH $w] $c
  return $c
}

# ---- SPI0 (ADF4351): SCLK, MOSI, SS0 out. MISO tied low, SS_I tied high (master) ----
ext_out processing_system7_0/SPI0_SCLK_O spi_sclk_o
ext_out processing_system7_0/SPI0_MOSI_O spi_mosi_o
ext_out processing_system7_0/SPI0_SS_O   spi_ss_o
const_cell const0 0 1
const_cell const1 1 1
connect_bd_net [get_bd_pins const0/dout] [get_bd_pins $ps/SPI0_MISO_I]
connect_bd_net [get_bd_pins const1/dout] [get_bd_pins $ps/SPI0_SS_I]

# ---- I2C0 (ADS1115): split open-drain signals, IOBUFs are in the board top ----
ext_in  processing_system7_0/I2C0_SCL_I i2c0_scl_i
ext_out processing_system7_0/I2C0_SCL_O i2c0_scl_o
ext_out processing_system7_0/I2C0_SCL_T i2c0_scl_t
ext_in  processing_system7_0/I2C0_SDA_I i2c0_sda_i
ext_out processing_system7_0/I2C0_SDA_O i2c0_sda_o
ext_out processing_system7_0/I2C0_SDA_T i2c0_sda_t

# ---- ENET0 MII on EMIO, as in the working design: RXD[3:0] zero-extended to 8 bit,
# TXD[3:0] sliced from 8 bit, FCLK1 (25 MHz) is the PHY clock ----
ext_in  processing_system7_0/ENET0_GMII_RX_CLK ENET0_GMII_RX_CLK_0
ext_in  processing_system7_0/ENET0_GMII_RX_DV  ENET0_GMII_RX_DV_0
ext_in  processing_system7_0/ENET0_GMII_RX_ER  ENET0_GMII_RX_ER_0
ext_in  processing_system7_0/ENET0_GMII_TX_CLK ENET0_GMII_TX_CLK_0
ext_out processing_system7_0/ENET0_GMII_TX_EN  ENET0_GMII_TX_EN_0
set rxd [create_bd_port -dir I -from 3 -to 0 ENET0_GMII_RXD_P]
set cc [create_bd_cell -type ip -vlnv xilinx.com:ip:xlconcat:2.1 rxd_concat]
set_property -dict [list CONFIG.NUM_PORTS {2} CONFIG.IN0_WIDTH {4} CONFIG.IN1_WIDTH {4}] $cc
const_cell zero4 0 4
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

# ---- fabric clock (FCLK0, 100 MHz), reset, AXI path to the engine ----
set rst [create_bd_cell -type ip -vlnv xilinx.com:ip:proc_sys_reset:5.0 proc_sys_reset_0]
set conv [create_bd_cell -type ip -vlnv xilinx.com:ip:axi_protocol_converter:2.1 axi_pc_0]
# Smallest option: AXI3 -> AXI4-Lite converter, no interconnect. PS7 GP0 and the converter
# negotiate AXI3 / AXI4LITE protocols by themselves.

set fclk [create_bd_port -dir O -type clk fclk0]
set_property CONFIG.FREQ_HZ 100000000 $fclk
connect_bd_net [get_bd_pins $ps/FCLK_CLK0] $fclk
connect_bd_net [get_bd_pins $ps/FCLK_CLK0] [get_bd_pins $ps/M_AXI_GP0_ACLK]
connect_bd_net [get_bd_pins $ps/FCLK_CLK0] [get_bd_pins proc_sys_reset_0/slowest_sync_clk]
connect_bd_net [get_bd_pins $ps/FCLK_CLK0] [get_bd_pins axi_pc_0/aclk]
connect_bd_net [get_bd_pins $ps/FCLK_RESET0_N] [get_bd_pins proc_sys_reset_0/ext_reset_in]
connect_bd_net [get_bd_pins proc_sys_reset_0/peripheral_aresetn] [get_bd_pins axi_pc_0/aresetn]
set arst [create_bd_port -dir O -type rst aresetn]
connect_bd_net [get_bd_pins proc_sys_reset_0/peripheral_aresetn] $arst

connect_bd_intf_net [get_bd_intf_pins $ps/M_AXI_GP0] [get_bd_intf_pins axi_pc_0/S_AXI]
make_bd_intf_pins_external [get_bd_intf_pins axi_pc_0/M_AXI]
set_property name m_axil [get_bd_intf_ports M_AXI_0]
set_property CONFIG.FREQ_HZ 100000000 [get_bd_intf_ports m_axil]
# the exported interface belongs to the fclk0 / aresetn ports
set_property CONFIG.ASSOCIATED_BUSIF m_axil [get_bd_ports fclk0]
set_property CONFIG.ASSOCIATED_RESET aresetn [get_bd_ports fclk0]

# ---- interrupt from the engine to IRQ_F2P[0] ----
ext_in processing_system7_0/IRQ_F2P irq_f2p

# ---- address segment: 64 KiB at 0x43C0_0000 ----
assign_bd_address -offset 0x43C00000 -range 64K \
  -target_address_space [get_bd_addr_spaces $ps/Data] [get_bd_addr_segs m_axil/Reg] -force

validate_bd_design
save_bd_design
