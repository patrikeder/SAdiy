# 30 dB amplifier board

Generic "0.1 to 2000 MHz RF wideband amplifier, 30 dB LNA" module. Transistor marking "NO2" did not match any datasheet part, so all numbers below are seller claims and must be measured.

| Item | Claim |
|---|---|
| Gain | 32 dB @ 0.1 MHz, 31 @ 500 MHz, 29 @ 1 GHz, 25 @ 1.5 GHz, 20 @ 2 GHz |
| Output P1dB | about +10 dBm (some listings +13 dBm) |
| Noise figure | 1.9 dB |
| Supply | 6 to 12 V (some listings 9 to 12 V); maximum gain at 12 V |
| Impedance | 50 ohm, SMA |

A flat 31 dB from a single transistor would be unusual: look for a second device on the board.

Fill in from the PCB
- Supply connector and polarity marking: TODO
- Supply current at 10 V (measure): TODO
- Number of gain devices and their markings: TODO
- Measured gain at 35 / 100 / 200 / 350 MHz: TODO
- Measured P1dB at 100 MHz: TODO
- Supply decoupling present; stability with a 50 ohm load and with the PE4302 / LPF in front: TODO

It is wideband, so the 500 MHz LPF must sit in front of it (`../todo-parts.md`).
