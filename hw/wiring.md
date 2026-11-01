# Wiring overview

- SBC pin maps and wiring order: [wiring-bbb.md](wiring-bbb.md), [wiring-rpi.md](wiring-rpi.md). Net list: [netlist.md](netlist.md).
- Diagrams and board hierarchy: [hierarchy.md](hierarchy.md).
- This page: RF cabling between the boards.

## RF cabling

Keep every RF link a short coax (SMA), 50 ohm. Mark each cable with its name.

| Cable | From | To | Notes |
|---|---|---|---|
| RF_IN | RF input connector | DC block + ESD (TODO) | PE4302 ports must see 0 V DC or a DC block |
| RF_1 | DC block + ESD | PE4302 RF1 | |
| RF_2 | PE4302 RF2 | 500 MHz LPF (TODO) | |
| RF_3 | 500 MHz LPF | 30 dB amp in | amp is wideband to 2 GHz: filter first |
| RF_4 | 30 dB amp out | AD831 RF in | |
| LO_1 | ADF4351 RFOUT | LO LPF + pad (TODO) | unused output terminated in 50 ohm |
| LO_2 | LO LPF + pad | AD831 LO in | about -10 dBm |
| IF_1 | AD831 IF out | 10.7 MHz IF filter (TODO) | |
| IF_2 | IF filter | IF amp (TODO) | |
| IF_3 | IF amp | detector RF in | check the detector input coupling and 50 ohm termination |
| DET | detector VOUT | divider + RC + clamp (TODO) | analog, short and away from the LO and RF cables |
| ADC | divider block | SBC ADC input | BBB AIN0, or the ADS1115 A0 on the RPi |

## Practical rules

- One ground star point near the SBC. RF coax shields also connect the boards, so avoid extra ground loops.
- Keep the LO and IF cables apart from the detector output wire.
- Fill in each board's connector and test points in `boards/*.md` as you inspect the PCBs.
