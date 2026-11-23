# Wiring overview

- SBC pin maps and wiring order: [wiring-bbb.md](wiring-bbb.md), EBAZ4205: [../zynq-ebaz/docs/pinmap.md](../zynq-ebaz/docs/pinmap.md), [wiring-rpi.md](wiring-rpi.md) (no longer developed). Net list: [netlist.md](netlist.md).
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
| IF_1 | AD831 IF out | IF low-pass 30 MHz, first module (TODO) | digital IF branch; check what load the AD831 IF port wants |
| IF_2 | first low-pass | second low-pass (SMA-SMA adapter) | two modules in series: about 62 dB at the alias band at 50 MS/s |
| IF_3 | second low-pass | AD9226 module SMA in (TODO) | 50 ohm, 10 Vpp full scale (about +24 dBm); coupling AC or DC not known yet |
| ADC_BUS | AD9226 module header | adapter v2 (DATA1, 14 signals) | 12 data lines + OTR in, clock out; short cable, series resistors on the adapter (`../zynq-ebaz/docs/adc-module.md` section 4) |
| IF_A | AD831 IF out | 10.7 MHz IF filter, IF amp, detector RF in | **analog branch, optional**: the AD8318 module is dead and not replaced |
| DET | detector VOUT | RC + clamp (1k, 100 nF) on the adapter board | analog branch, only with a working detector; short and away from the LO and RF cables |
| ADC | RC + clamp | ADS1115 A0 (BBB: AIN0 too, through a divider, as a cross-check) | analog branch |

## Practical rules

- One ground star point near the SBC. RF coax shields also connect the boards, so avoid extra ground loops.
- Keep the LO and IF cables apart from the detector output wire.
- Fill in each board's connector and test points in `boards/*.md` as you inspect the PCBs.
