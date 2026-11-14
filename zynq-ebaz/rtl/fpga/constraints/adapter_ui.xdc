# HelloFPGA adapter board for the EBAZ4205 (silk "EBAZ4205_ZJB05"): display, keys and LEDs, all owned by Linux (PS).
# Hand-maintained. Source: photo zynq-ebaz docs/20261114_134742.heic (user, 2026-11-14); the balls of keys,
# LEDs and display clock / data / select are the same as in the old EBAZ_extender project.
#
#   LCD_PIN (silk)   CS T20   DC R18   SCL R19   SDA P20   RES N17      -> lcd_cs lcd_dc lcd_scl lcd_sda lcd_res
#                    ST7789 panel, driven by Linux: PS SPI1 on EMIO (scl, sda, cs) + EMIO GPIO 8 (dc) / 9 (res)
#   KEY1..KEY5       T19, P19, U20, U19, V20                              -> keys[0..4]
#   LED1..LED3       H18, K17, E19                                        -> led[0..2]
#
# Notes
#  - Keys: pull-up enabled (the extender project did the same), a pressed key is read as 0 (Linux: GPIO_ACTIVE_LOW).
#  - Keys and LEDs are EMIO GPIO 13..17 / 10..12 for Linux (see ebaz_sadiy_top.sv); no PL logic.
#  - LED polarity is not known from the photo: led = 1 is "on" only if the LEDs are driven active high. Check once.
#  - All of these are slow, quasi-static or <= 12.5 MHz signals that leave the fabric as data (no generated
#    clock), so they are false paths like the other pads in timing.xdc.
#  - Not constrained although on the adapter: HDMI (D19, C20, B19, F19 + D18 buzzer), the UART header on H16 / H17.
#  - CONFLICT with the planned AD9226 on DATA1: H18, K17, E19 (LEDs), H16 / H17 (UART header), D19, C20, B19, F19
#    (HDMI) are also adc_* pins in pins.toml. Do not constrain both.

# CS and RES have a pull-up so the panel is deselected and not in reset while the PS pins are still inputs;
# SCL idles low (SPI mode 0).
set_property -dict {PACKAGE_PIN T20 IOSTANDARD LVCMOS33 PULLTYPE PULLUP} [get_ports lcd_cs]
set_property -dict {PACKAGE_PIN R18 IOSTANDARD LVCMOS33} [get_ports lcd_dc]
set_property -dict {PACKAGE_PIN R19 IOSTANDARD LVCMOS33 PULLTYPE PULLDOWN} [get_ports lcd_scl]
set_property -dict {PACKAGE_PIN P20 IOSTANDARD LVCMOS33} [get_ports lcd_sda]
set_property -dict {PACKAGE_PIN N17 IOSTANDARD LVCMOS33 PULLTYPE PULLUP} [get_ports lcd_res]

set_property -dict {PACKAGE_PIN T19 IOSTANDARD LVCMOS33 PULLTYPE PULLUP} [get_ports {keys[0]}]
set_property -dict {PACKAGE_PIN P19 IOSTANDARD LVCMOS33 PULLTYPE PULLUP} [get_ports {keys[1]}]
set_property -dict {PACKAGE_PIN U20 IOSTANDARD LVCMOS33 PULLTYPE PULLUP} [get_ports {keys[2]}]
set_property -dict {PACKAGE_PIN U19 IOSTANDARD LVCMOS33 PULLTYPE PULLUP} [get_ports {keys[3]}]
set_property -dict {PACKAGE_PIN V20 IOSTANDARD LVCMOS33 PULLTYPE PULLUP} [get_ports {keys[4]}]

set_property -dict {PACKAGE_PIN H18 IOSTANDARD LVCMOS33} [get_ports {led[0]}]
set_property -dict {PACKAGE_PIN K17 IOSTANDARD LVCMOS33} [get_ports {led[1]}]
set_property -dict {PACKAGE_PIN E19 IOSTANDARD LVCMOS33} [get_ports {led[2]}]

set_false_path -from [get_ports {keys[*]}]
set_false_path -to   [get_ports {led[*] lcd_cs lcd_dc lcd_scl lcd_sda lcd_res}]
set_false_path -from [get_ports {lcd_dc lcd_res}]
