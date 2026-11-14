# Ethernet PHY constraints (MII on EMIO). HAND-MAINTAINED, not generated.
# Source: HW/Vivado/EBAZ_extender/EBAZ_extender.srcs/constrs_1/imports/ebaz4205/ebaz4205.xdc
# (lines up to the DATA1 block; CAN, display, keys, LEDs, GPIO and the debug hub lines are not carried over).
# Port names are those of ebaz_sadiy_top.sv / the block design (same as session L's phase1_top.v).
#
# Changes against the source (2026-11-14):
#  - set_input_delay on ENET0_GMII_RX_EN_0[*]: that port does not exist (the design has ENET0_GMII_RX_DV_0
#    and ENET0_GMII_RX_ER_0). Replaced by RX_DV, which is what the line meant.
#  - set_output_delay on ENET0_GMII_TX_EN_0[*]: exists, kept.
#  - set_property CLOCK_DEDICATED_ROUTE FALSE [get_nets enet0_mii_tx_clk_IBUF]: net does not exist
#    (critical warning), commented out as in session L's board constraints.

# ENET0 MII via EMIO
set_property PACKAGE_PIN U18 [get_ports enet0_phy_clk]
set_property IOSTANDARD LVCMOS33 [get_ports enet0_phy_clk]

set_property IOSTANDARD LVCMOS33 [get_ports enet0_mdio_mdc]
set_property IOSTANDARD LVCMOS33 [get_ports enet0_mdio_mdio_io]

set_property IOSTANDARD LVCMOS33 [get_ports ENET0_GMII_RX_CLK_0]
set_property IOSTANDARD LVCMOS33 [get_ports ENET0_GMII_RX_DV_0]
set_property IOSTANDARD LVCMOS33 [get_ports {ENET0_GMII_RXD_P[3]}]
set_property IOSTANDARD LVCMOS33 [get_ports {ENET0_GMII_RXD_P[2]}]
set_property IOSTANDARD LVCMOS33 [get_ports {ENET0_GMII_RXD_P[1]}]
set_property IOSTANDARD LVCMOS33 [get_ports {ENET0_GMII_RXD_P[0]}]

set_property IOSTANDARD LVCMOS33 [get_ports ENET0_GMII_TX_CLK_0]
set_property IOSTANDARD LVCMOS33 [get_ports {ENET0_GMII_TX_EN_0[0]}]
set_property IOSTANDARD LVCMOS33 [get_ports {ENET0_GMII_TXD_P[3]}]
set_property IOSTANDARD LVCMOS33 [get_ports {ENET0_GMII_TXD_P[2]}]
set_property IOSTANDARD LVCMOS33 [get_ports {ENET0_GMII_TXD_P[1]}]
set_property IOSTANDARD LVCMOS33 [get_ports {ENET0_GMII_TXD_P[0]}]

set_property PACKAGE_PIN W15 [get_ports enet0_mdio_mdc]
set_property PACKAGE_PIN Y14 [get_ports enet0_mdio_mdio_io]
set_property PACKAGE_PIN U14 [get_ports ENET0_GMII_RX_CLK_0]
set_property PACKAGE_PIN W16 [get_ports ENET0_GMII_RX_DV_0]
set_property PACKAGE_PIN Y17 [get_ports {ENET0_GMII_RXD_P[3]}]
set_property PACKAGE_PIN V17 [get_ports {ENET0_GMII_RXD_P[2]}]
set_property PACKAGE_PIN V16 [get_ports {ENET0_GMII_RXD_P[1]}]
set_property PACKAGE_PIN Y16 [get_ports {ENET0_GMII_RXD_P[0]}]

## Timing Constraints (Assumes a 25MHz MII Clock, adjust period if different)
create_clock -period 40.000 -name v_ETH_RX_clk [get_ports ENET0_GMII_RX_CLK_0]

## Setup/Hold constraints to match data lines to the clock edge (Source-Synchronous Out)
set_input_delay -clock v_ETH_RX_clk -max 5.000 [get_ports {ENET0_GMII_RX_DV_0 {ENET0_GMII_RXD_P[*]}}]
set_input_delay -clock v_ETH_RX_clk -min -1.000 [get_ports {ENET0_GMII_RX_DV_0 {ENET0_GMII_RXD_P[*]}}]


set_property -dict {IOSTANDARD LVCMOS33 PACKAGE_PIN G17} [get_ports ENET0_GMII_RX_ER_0]
set_property PULLDOWN TRUE [get_ports ENET0_GMII_RX_ER_0]

#set_property CLOCK_DEDICATED_ROUTE FALSE [get_nets enet0_mii_tx_clk_IBUF]  ; # dead: net does not exist

set_property PACKAGE_PIN U15 [get_ports ENET0_GMII_TX_CLK_0]
set_property PACKAGE_PIN W19 [get_ports {ENET0_GMII_TX_EN_0[0]}]
set_property PACKAGE_PIN Y19 [get_ports {ENET0_GMII_TXD_P[3]}]
set_property PACKAGE_PIN V18 [get_ports {ENET0_GMII_TXD_P[2]}]
set_property PACKAGE_PIN Y18 [get_ports {ENET0_GMII_TXD_P[1]}]
set_property PACKAGE_PIN W18 [get_ports {ENET0_GMII_TXD_P[0]}]

## Timing Constraints (Assumes a 25MHz MII Clock, adjust period if different)
create_clock -period 40.000 -name v_ETH_TX_clk [get_ports ENET0_GMII_TX_CLK_0]

## Setup/Hold constraints to match data lines to the clock edge (Source-Synchronous Out)
set_output_delay -clock v_ETH_TX_clk -max 5.000 [get_ports {{ENET0_GMII_TX_EN_0[*]} {ENET0_GMII_TXD_P[*]}}]
set_output_delay -clock v_ETH_TX_clk -min -1.000 [get_ports {{ENET0_GMII_TX_EN_0[*]} {ENET0_GMII_TXD_P[*]}}]

set_property DRIVE 8 [get_ports enet0_mdio_mdc]
set_property DRIVE 8 [get_ports enet0_mdio_mdio_io]

set_property DRIVE 8 [get_ports {ENET0_GMII_TX_EN_0[0]}]
set_property DRIVE 8 [get_ports {ENET0_GMII_TXD_P[3]}]
set_property DRIVE 8 [get_ports {ENET0_GMII_TXD_P[2]}]
set_property DRIVE 8 [get_ports {ENET0_GMII_TXD_P[1]}]
set_property DRIVE 8 [get_ports {ENET0_GMII_TXD_P[0]}]
