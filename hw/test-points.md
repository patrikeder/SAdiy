# Test points and expected values

"Verify" means the value comes from a datasheet or a seller listing and has not been measured on these boards yet. Add the real pad / header name from each PCB in the first column.

| ID (fill in from PCB) | Node | Instrument | Expected | Source |
|---|---|---|---|---|
| TP_5V | 5 V rail | DMM | 4.75 to 5.5 V at the detector | detector datasheet |
| TP_10V | AD831 / amp rail | DMM | 9 to 11 V at the AD831 module | AD831 module listing |
| TP_5V_SYN / TP_3V3_SYN | ADF4351 board DC jack / `3V3` header pin | DMM | 5 V at the jack; 3.0 to 3.6 V at the pin (AMS1117-3.3 output) | photo, ADF4351 datasheet |
| TP_3V3_ATT | PE4302 VDD pad | DMM | 3.3 V (module has no regulator); chip allows 2.7 to 5.5 V | module description |
| TP_PE_V1 ... V6 | PE4302 control inputs | DSLogic, DMM | static levels per `pe4302-pattern`; one stage at a time with `pe4302-walk`; high when the SBC does not drive them (pull-ups) | module, verify |
| TP_SYN_SPI | ADF4351 CLK / DATA / LE | DSLogic | 32-bit words, MSB first, LE rises after the last bit | ADF4351 datasheet |
| TP_SYN_LD | lock detect | DSLogic / scope | high when locked | verify |
| TP_LO_OUT | ADF4351 output after pad | MSO5354, 50 ohm | about -4 dBm minus pad loss (-4 dBm is 0.40 Vpp into 50 ohm, before the pad) | ADF4351 datasheet |
| TP_AMP_OUT | amp output | MSO5354, 50 ohm | gain 31 dB at 500 MHz, P1dB about +10 dBm | seller claim, verify |
| TP_IF | AD831 IF output | MSO5354 | 10.7 MHz when LO = RF + 10.7 MHz | design |
| TP_DET_IN | detector RF input | MSO5354 or DMM on Vout | -58 to -1 dBm useful window | AD8318 datasheet |
| TP_DET_OUT | detector Vout | DMM | about 0.73 V at -10 dBm; slope about -24.5 mV/dB; verify at 10.7 MHz | AD8318 datasheet (900 MHz) |
| TP_ADC_IN | SBC ADC pin | DMM | **never above 1.8 V on the BBB** | BBB |

Notes
- The scopes only reach 350 MHz (MSO5354) and 200 MHz (DS2072), so for 350 to 500 MHz use the detector as a relative meter.
- If the scope input is 1 Mohm, use a 50 ohm feed-through termination for level checks.
- Mark each test point on the PCB with a label that matches the first column.
