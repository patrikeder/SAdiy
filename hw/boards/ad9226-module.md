# AD9226 module and IF low-pass modules (digital IF branch, EBAZ4205 only)

Facts from the seller's listing ("AD9226_01"); nothing is measured yet. **check** marks what the bench has to settle. The full record (level plan, anti-alias analysis, adapter v2 requirements, what is built in the PL) is [../../zynq-ebaz/docs/adc-module.md](../../zynq-ebaz/docs/adc-module.md); pictures are in `../../zynq-ebaz/docs/adc-module/`.

## AD9226 module

| Item | Value |
|---|---|
| ADC | AD9226, 12 bit, 65 MSPS maximum, parallel: D0..D11 + OTR (over-range) |
| Input | 1 channel, SMA (and an XH2.54 socket), 50 ohm, 10 Vpp full scale (about +24 dBm); real input attenuation **check** |
| Bandwidth | -3 dB at 320 MHz |
| Reference | internal 2 V |
| Supply | 5 V (4.75 to 5.25 V); 3.3 V logic made on the module (3V3 net **check** with a DMM); current not given |
| Clock | none on the module: the FPGA supplies it on the header's CLK pin |
| Header | 2.54 mm: GND, +5 V, data, CLK; the labels are not legible on the photo. **Need the pin table** |
| Coupling | not stated (AC or DC) **check** |
| Size | 54 x 37 x 23 mm, 16 g |

## Connection to the EBAZ4205

14 signals on DATA1 (`adc_d[0..11]`, `adc_otr`, `adc_clk`; balls in `zynq-ebaz/rtl/vivado/pins.toml`), through the **adapter v2** (adapter v1 uses three of those balls for LEDs and other parts). The default bitstream has no ADC pins: the data lines are tied off inside the engine and a traffic generator tests the whole path; a build with `SADIY_ADC_PADS=1` adds the pins. The module is not on the BBB's pin map and is not in `netlist.md` yet.

## IF low-pass modules

Two modules in series, 30 MHz cutoff (the only option on offer): 7th order Chebyshev type I, 1 dB ripple, SMA, 50 ohm, insertion loss 1 to 2 dB typical (3 dB maximum), stopband up to 70 dB, 30 x 9 mm without connector, maximum input about 23 dBm. At 50 MS/s the alias band (fs - 10.7 MHz +- 1.5 MHz, 37.8 to 40.8 MHz) is attenuated by about 31 to 38 dB with one module and about 62 dB with two. Lower sample rates do not work with this filter.

## Test points and checks

- 5 V and 3V3 on the module with a DMM before the clock is connected.
- Input: DC level at the SMA (coupling), mixer IF level with the scope, then the PL checks `./run.sh fe` (no module needed) and later with `FE_CFG.src = 2`.
- Capture phase against the module: `FE_CFG.phase` is found on the bench.
