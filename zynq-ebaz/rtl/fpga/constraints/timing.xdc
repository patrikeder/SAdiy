# Extra timing constraints for ebaz_sadiy_top. The Ethernet clocks / delays are in eth.xdc.
#
# The pads below carry slow, quasi-static signals to and from the adapter board and have no
# source-synchronous relation to a fabric clock that STA could check:
#   adf4351_clk/dat/le : the engine's SPI clock is generated in fabric AS DATA (a register output,
#                        at most 25 MHz, from the 100 MHz FCLK0); the ADF4351 samples it on its own
#                        edge, with a setup / hold of a few ns against 20+ ns bit periods. No
#                        generated clock is defined for it on purpose.
#   adf4351_ce/ld, pe4302_v : static levels (attenuator weights, chip enable, lock detect) read
#                        by software or the sequencer, which waits many clocks for them.
#   i2c_scl/sda        : open-drain I2C0 of the PS (EMIO), at most 400 kHz, bit-banged by the PS.
#   enet0_mdio_*       : MDIO / MDC of the PS, 2.5 MHz at most.
# A set_false_path is therefore the honest constraint: an invented output delay would be a number
# nobody can verify. It also keeps these ports out of the "unconstrained ports" report.
set_false_path -to   [get_ports {adf4351_clk adf4351_dat adf4351_le adf4351_ce pe4302_v[*]}]
set_false_path -from [get_ports {adf4351_ld adf4351_ce pe4302_v[*]}]
set_false_path -to   [get_ports {i2c_scl i2c_sda}]
set_false_path -from [get_ports {i2c_scl i2c_sda}]
set_false_path -to   [get_ports {enet0_mdio_mdc enet0_mdio_mdio_io}]
set_false_path -from [get_ports {enet0_mdio_mdio_io}]
# ENET0_GMII_RX_ER_0 and the PHY clock output enet0_phy_clk (FCLK1, 25 MHz, a clock output with
# no data relation to the fabric) have no clock relation either.
set_false_path -from [get_ports ENET0_GMII_RX_ER_0]
set_false_path -to   [get_ports enet0_phy_clk]
