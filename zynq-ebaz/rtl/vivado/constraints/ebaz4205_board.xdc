# Board-fixed pins: Ethernet PHY (MII) on EMIO. Hand-maintained, NOT generated.
# Copied 2026-11-14 from HW/Vivado/EBAZ_extender (working design); keep in sync with the PHY wiring, not with pins.toml.

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
set_input_delay -clock v_ETH_RX_clk -max 5.000 [get_ports {{ENET0_GMII_RX_EN_0[*]} {ENET0_GMII_RXD_P[*]}}]
set_input_delay -clock v_ETH_RX_clk -min -1.000 [get_ports {{ENET0_GMII_RX_EN_0[*]} {ENET0_GMII_RXD_P[*]}}]


set_property -dict {IOSTANDARD LVCMOS33 PACKAGE_PIN G17} [get_ports ENET0_GMII_RX_ER_0]
set_property PULLDOWN TRUE [get_ports ENET0_GMII_RX_ER_0]

# Disabled 2026-11-14: net enet0_mii_tx_clk_IBUF does not exist in the Phase 1 design (critical warning); impl passes without it.
#set_property CLOCK_DEDICATED_ROUTE FALSE [get_nets enet0_mii_tx_clk_IBUF]

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


