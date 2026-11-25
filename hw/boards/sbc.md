# SBC: BeagleBone Black, or EBAZ4205 (the port)

| Item | BBB | EBAZ4205 (Zynq-7010) |
|---|---|---|
| Role | the validation vehicle, runs `sweepd` today (bench mode only) | the port: Linux on the PS, optional sweep engine in the PL |
| Supply | 5 V / 2 A | 5 V (board), the adapter takes its 3.3 V from the board |
| GPIO / SPI level | 3.3 V | 3.3 V (PL bank, LVCMOS33) |
| Analog input | 8 channels, 12-bit, **0 to 1.8 V max**; AIN0 is the detector input (the ADS1115 was removed) | none in the PS; the AD9226 module feeds the PL |
| Control pins | P9 (SPI0, I2C2, LD, CE), pin mux per pin | DATA2 (SPI0, I2C0, LD, CE), fixed in the bitstream, no pin mux. The PE4302 is behind a PCF8574 on I2C on both |
| Display | remote viewer over network | remote viewer; the adapter's ST7789 LCD, 3 LEDs and 5 keys are Linux devices |
| Image / OS | Debian Trixie, kernel 6.18, Python 3.13 (read from the board, 2026-11-07) | PetaLinux 2025.2, kernel 6.12.40, sysvinit, Python 3.12 (baseline 2026-11-14) |
| Pin map | `src/sadiy/pinmap.py`, `wiring-bbb.md` | `src/sadiy/pinmap_ebaz.py`, `../zynq-ebaz/docs/pinmap.md` |

Both maps are in the generated `netlist.md`. The Raspberry Pi is no longer supported (its connector was removed from the adapter board; the old notes are still in `wiring-rpi.md`).

Fill in
- Header or breakout used to reach the boards: the adapter board (`boards/sbc-adapter/README.md`)
- Ground star point location: TODO

Setup notes: `../../deploy/bbb-setup.md` (BBB), `../../zynq-ebaz/sw/deploy/README.md` (EBAZ4205).
