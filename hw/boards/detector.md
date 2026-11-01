# Log detector board (AD8318 class, 1 to 8000 MHz, 25 mV/dB)

| Item | Value |
|---|---|
| Part | AD8318 (confirm the marking on the board) |
| Range | 1 MHz to 8 GHz; +/-1 dB window about -58 to -1 dBm |
| Slope / intercept | about -24.5 mV/dB, about 20 dBm (varies with frequency; calibrate) |
| Output | about 0.73 V at -10 dBm, about 1.5 V at -40 dBm, about 1.9 V near -58 dBm (datasheet points at 0.9 to 2.2 GHz; verify at 10.7 MHz) |
| Supply | 5 V, about 68 mA (module listing) |
| Response | 10 ns pulse response; the CLPF capacitor sets the video filtering |

## Seen in the photo ([photos/detector-module.jpg](../photos/detector-module.jpg))
Silkscreen `P_Amp 1-8000mhz  Gain: -25mV/dB  V: 1.0`. SMA `RFin`, pads `VCC` and `GND` at the opposite end with grey leads, a 2-pin `OUT` header, a small LED, and a SOT-223 regulator next to the `VCC` pad, so the module probably accepts more than 5 V. Read the regulator marking before choosing the supply. Find which pin of the `OUT` header is the output and which is GND with a DMM.

Fill in from the PCB
- Supply connector: TODO
- Output connector / pad and what it is loaded with: TODO
- Is VOUT tied to VSET (measurement mode) and is the slope resistor network fitted: TODO
- RF input: SMA, AC coupling, 50 ohm termination present: TODO
- CLPF capacitor value: TODO
- ENBL pin strapping: TODO

ADC interface (not built yet): divider + RC + clamp so the BBB ADC pin never exceeds 1.8 V. The detector output can reach about 1.9 V near the bottom of its range, so a divider is needed. Put the real ratio in `config/default.toml` under `detector.divider_ratio`.
