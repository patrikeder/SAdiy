# AD9226 module and the IF filter in front of it

State 2026-11-23 (front end built, see section 6). User decision: the IF digitizer is the AD9226 module below; the log detector (AD8310 / AD8318) is not
bought. The facts come from the seller's listing (images in `adc-module/`, the listing text could not be fetched
automatically); nothing here is measured yet. Items marked **check** need the module on the bench.

## 1. The module (listing, "AD9226_01")

| Item | Listing says | Note |
|---|---|---|
| ADC | AD9226, 12 bit, 65 MSPS maximum | 13 parallel data lines: D0..D11 and over-range (OTR) |
| Input | 1 channel, SMA (and an XH2.54 socket), 50 ohm, range 10 Vpp (+-5 V) | 10 Vpp into 50 ohm is about +24 dBm full scale. The plan's "about 8.4 dB attenuation" came from another project; 10 Vpp against the ADC's 2 V range would be about 14 dB. **check** |
| Analog bandwidth | -3 dB at 320 MHz | the ADC sees (and aliases) everything the mixer delivers up to that, so a filter in front is needed |
| Reference | internal 2 V | |
| Supply | 5 V DC, 4.75 to 5.25 V (screw terminal or header) | an on-board regulator (photo: 3V3 pads, U5) makes 3.3 V |
| Logic level | 3.3 V | answers user task U2 (DRVDD = 3.3 V) as far as the listing goes. **check** with a DMM on the module's 3V3 net |
| Clock | none mentioned, no oscillator visible on the photo | the FPGA supplies it (CLK pin of the header); the example is Verilog for a Cyclone board |
| Header | 2.54 mm, GND, +5 V, data, CLK | the pin labels are not legible on the photo. **Need:** a close-up or the seller's pin table before the adapter v2 is drawn |
| Coupling | not stated | **check** (AC or DC coupled; decides whether a bias path is needed after a bandpass; a low-pass passes DC) |
| Size, weight | 54 x 37 x 23 mm, 16 g | |

Files: `adc-module/ad9226-module-photo.png` (board), `adc-module/ad9226-listing-parameters.png` (listing table; the
user's original `docs/ADC_param.png` is an AVIF file with a .png name and does not open in every viewer).

## 2. Level plan (estimates)

- Full scale about +24 dBm at the module input (listing). With the chain gain of about 26 dB (amp 31, PE4302 1.5,
  LPF 1.5, mixer about 0, IF filter 1.5 instead of the 6 of the ceramic filter) full scale is about -2 dBm at the RF
  input at 0 dB attenuation, which matches the old detector window. No IF amp is needed to start.
- Quantization noise (70 dB SNR over fs/2 = 25 MHz at 50 MS/s) is about -90 dBm in 1 kHz at the module input, so
  about -115 dBm at the RF input; the chain's noise figure (about -104 dBm with 10 dB NF) will dominate. Measure it.
- Over-range: OTR goes into the result word (bit 30) as for the existing IF path.

## 3. Sample rate and the anti-alias filter

The IF is 10.7 MHz. Anything at fs - 10.7 MHz (and fs + 10.7, ...) folds onto it; the DDC window is about +-1.5 MHz.
The only low-pass module on offer (listing: 7th order Chebyshev type I, 1 dB ripple, SMA, 50 ohm, up to 70 dB
stopband, insertion loss 1 to 2 dB typical, 3 dB maximum) has a 30 MHz cutoff. Ideal attenuation of such a filter
(real ones are limited to about 70 dB by parasitics) over the fold band fs - 10.7 +- 1.5 MHz:

| fs | fold band | one module | two modules in series | note |
|---|---|---|---|---|
| 25 MS/s | 11.8 to 14.8 MHz | 0 dB | 0 dB | useless: the low-pass does nothing below 30 MHz |
| 40 MS/s | 27.8 to 30.8 MHz | 1 to 4 dB | 2 dB | useless |
| 50 MS/s | 37.8 to 40.8 MHz | 31 to 38 dB | about 62 dB | divide-by-2 of the 100 MHz fabric clock |
| 65 MS/s | 52.8 to 55.8 MHz | 59 to 63 dB | far more | needs its own clock (MMCM, e.g. 100/2 x 13 / 10) and a clock-domain crossing into the engine |

Consequences:
- **50 MS/s is the minimum** with this filter. One module alone leaves ghost responses at about -31 to -38 dBc for
  a strong signal 28.6 MHz away from the tuned frequency (RF = LO - 10.7 -+ 28.6 MHz).
- **Decision for the first build:** 50 MS/s, two 30 MHz modules in series (SMA-SMA adapter), about 62 dB ideal.
  Passband ripple of up to 2 dB at 10.7 MHz is fixed and is removed by calibration (flatness over the window). A
  home-made 5th-order bandpass at 10.7 MHz, about 3 MHz wide (T37-6 or T50-6 toroids, C0G capacitors), would
  also limit the total power reaching the ADC and is the upgrade if the low-pass proves too weak or overloads.
- The same idea as the image rejection can remove what is left: sweep once more at a different sample rate (alias
  responses move, wanted ones do not) and take the minimum. Costs a second sweep; not planned.
- The IF path at 50 MS/s is simulated since the front end exists (`tb_if`: tone through the front end at `div` 2,
  bit-exact tie-off). The CIC ratio doubles for the same RBW (R = 64 at 50 MS/s about R = 32 at 25 MS/s).

## 4. Adapter v2 requirements (from this module)

- The 14 DATA1 signals as in `rtl/vivado/pins.toml` (`adc_d[0..11]`, `adc_otr`, `adc_clk`: A20 B19 B20 C20 D20
  D18 D19 F20 E19 F19 H18 H17, H16, K17) go straight to the module header; no LEDs, buzzer, UART header or HDMI on
  those balls. This makes the HDMI-port proposal of `pinmap.md` unnecessary.
- 5 V and GND to the module (wide enough for a few hundred mA), module supply filtered; the 3.3 V logic comes from
  the module itself.
- Series resistors on the data lines near the FPGA of 33 to 100 ohm, 33 to 47 ohm on `adc_clk` at the FPGA. The
  220 ohm of the control lines is too much at 50 MHz (RC with the input capacitance).
- Keep the cable between adapter and module short; sample delay is adjustable in the `adc_ad9226` module
  (constant latency of 7 clock periods is not corrected).

## 5. Open points

1. Pin table of the module's header (photo is not legible). **User**
2. Coupling, real input attenuation, 3V3 net with a DMM, mixer IF output level with the scope. **User at the bench**
3. What load the AD831 IF port wants (datasheet or module photo). **Open**
4. ~~Register map 1.3~~ done 2026-11-23 (section 6). Left: the pins (ADC_PADS build) after the adapter v2, the
   capture phase against the module on the bench, the real-ADC bring-up stage (`fe` with src 2).
5. `ebaz4205-zynq-plan.md` appendix E still says "the module attenuates its input by about 8.4 dB" and
   "DRVDD = 3.3 V to check"; this file has the newer facts.

## 6. What is built (register map 1.3, 2026-11-23)

The engine has an ADC front end (`rtl/src/adc_fe.sv`, `rtl-spec.md` section 8d, registers `FE_CFG`, `FE_TIE`,
`FE_TG_INC`, `FE_STAT`; `VERSION` >= 0x00010003 tells software it exists). It runs without the module and without
pins, so the whole path can be tested before the adapter v2 exists:

| `FE_CFG.src` | Data lines | Use |
|---|---|---|
| 0 | tie-off (`FE_TIE`) | constant stream: bit-exact IF path result, OTR path |
| 1 | traffic generator: ramp / walking one / tone / constant | clock, capture, conversion, data-line order (walking one), IF path at 50 MS/s |
| 2 | pins (`adc_d`, `adc_otr`) | the module; needs a build with `SADIY_ADC_PADS=1` and the adapter v2 |

Pins in the default build: none for the ADC (data lines tied to 0x800, no `adc_clk` pad). `adc_pins.xdc` has the
14 DATA1 balls of pins.toml ready; it is not used until the adapter v2 and the module's header order are known.

Use on the board (after loading the 1.3 bitstream): `./run.sh fe` runs the checks above automatically (no module
needed). To look at the generator in the GUI: the virtual spectrum of session L still uses the sample generator;
the front end is read through `FE_STAT` and the IF path (`FE_CFG.src = 1, tg_mode = 2`, `DET_CFG.mode = 1`,
`DET_CFG.src = 2`, `IF_NCO` = `FE_TG_INC`).
