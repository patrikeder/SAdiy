# SNA bring-up plan and timeline
Written 2026-11-01. Delivery dates are Amazon.de estimates from that day and may slip.

## 1. Signal path and levels
ADF4351 -> 6 dB pad -> PE4302 -> [DUT] -> detector -> ADC
- 6 dB pad: the ADF4351 minimum output is -4 dBm, so about -10 dBm after the pad.
- PE4302 on the source side sets the stimulus level in 0.5 dB steps (check its max RF input power in the datasheet, verify).
- Detector window about -58 to -1 dBm (57 dB). Realistic dynamic range about 50 dB.
- ADF4351 harmonics (2nd about -19 dBc, 3rd about -13 dBc) limit stopband measurements of filters. Use a low-pass or accept the limit.

## 2. Calibration
1. Thru: DUT replaced by a short SMA adaptor. Sweep and store P_thru(f).
2. Detector curve: known pads (6/10/20 dB) in the thru path, fit slope and intercept per frequency band.
3. S21(f) = P_dut(f) - P_thru(f) in dB, plus detector curve correction.

## 3. Software tasks
- [ ] ADF4351 register packing (`../src/sadiy/drivers/adf4351.py`), golden tests against ADI's eval software.
- [ ] SNA mode in `freqplan`: LO = RF directly, no f_if, 35 to 4400 MHz, RF divider handled by the packing code.
- [ ] ADS1115 driver (I2C, +/-2.048 V range, 860 SPS) and BBB on-chip ADC path with divider.
- [ ] `build_hw_engine` in `sweepd`: real SPI/GPIO, switch GPIO from sysfs to libgpiod.
- [ ] Thru normalisation and S21 trace in `cal.py`, saved as JSON/NPZ.
- [ ] Client: S21 trace in dB, markers, thru-store button. Terminal first; later an SNA mode in `ui/sa_gui.py` (markers, trace B, CSV export and the Advanced tab carry over; the level axis becomes dB relative to the thru).
- [ ] Measure per-point time (PLL lock plus ADC) before deciding on C++/Rust.

## 4. Timeline (evenings, adjust freely)
| When | What |
|---|---|
| Sun 1 Nov to Mon 2 Nov | ADF4351 register packing plus golden tests. SNA mode in `freqplan`, test on the simulator. |
| Tue 3 Nov | Verify the pin map on the BBB/RPi image. Wire ADF4351 and PE4302, clean 3.3 V rail. DSLogic on SPI/GPIO. ADF4351 at 100 MHz on the MSO5354 (frequency and level). |
| Wed 4 Nov | ADS1115 and 10 dB pad arrive. Detector curve with a DMM against the pad. |
| Thu 5 Nov | 6 dB pad and DC blocks arrive. ADC driver, first live sweep of the thru. |
| Fri 6 Nov | 20 dB pad arrives. Detector calibration with 6/10/20 dB pads. |
| Sat 7 Nov to Sun 8 Nov | First S21 sweeps: thru, 10 dB and 20 dB pad (check they read flat), then the 30 dB amp as DUT with at least 30 dB of pads in front (amp P1dB about +10 dBm at about 31 dB gain, seller claims). Measure the gain roll-off to 2 GHz. |
| Following week | Client with markers, save calibration, measure time per point. Then decide: mixer/IF stage for the spectrum analyzer, or C++/Rust for the sweep loop. |

## 5. Done criteria
- Thru sweep flat within about +/-1 dB over 35 MHz to 2 GHz.
- 10 dB and 20 dB pads read within about +/-1 dB of nominal (specified +/-0.5 to 0.8 dB).
- Amp gain curve reproducible between two sweeps.

## 6. Open points
- Which ADC path first: ADS1115 on the RPi, or BBB on-chip ADC (0 to 1.8 V, needs divider)?
- Answered 2026-11-01: the PE4302 module has parallel control only (V1..V6), no serial mode. Still open: is its RF input DC-blocked (series capacitors seen on the photos, verify)?
