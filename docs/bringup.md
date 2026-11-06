# Bring-up plan

Instruments on hand: several DMMs, Rigol MSO5354 (350 MHz), Rigol DS2072 (200 MHz), DSLogic logic analyzer.
Each stage lists the board test points it uses (see `hw/test-points.md`). Tick a stage only when its pass criteria are met.

## Stage 0: rails and control lines
- Measure each rail at its board before connecting the next board (`hw/test-points.md`).
- Pin check from the GUI: start `sweepd` on the BBB (`deploy/bbb-setup.md`, Run), then on the PC run `python -m sadiy.ui.sa_gui --host <bbb-ip> --connect`, then Pins tab, Enter bench mode. No RF connected yet.
  1. With no boards connected, first check the pin map itself: DMM or DSLogic on each pin in turn, Drive 0 / Drive 1 from the Pin page. This is the first test of the pin map and the pin mux on the real image, so correct `src/sadiy/pinmap.py` if a pin does not move.
  2. With boards connected, DSLogic on the module headers: Patterns page, walking one over the PE4302 lines, then over SYN_CLK, SYN_DATA and SYN_LE. Export the CSV and compare the edge order. A line that stays still or moves with another is an open or a short. Walking the SPI lines can latch junk into the ADF4351; the daemon sends an outputs-off R4 afterwards.
  3. Raw access page: read the ADS1115 config register. The power-on value is 0x8583. If the read fails, check the bus number (`i2cdetect`, `bench.i2c_bus`).
- Identify V1 to V6: run `python tools/bringup.py pe4302-walk --gpio ...` on the SBC with a low-level tone through the attenuator into the detector and a DMM on the detector output. Each stage switched in should raise the output by weight x 24.5 mV. Write the weights and polarity into `config/default.toml`.
- DSLogic on V1 to V6: `python tools/bringup.py pe4302-pattern --db 16 --from-db 15.5` prints the write order; the capture must match and the lowest attenuation during the change must not drop below 15.5 dB. Do the same for the ADF4351 SPI lines with `adf4351-pattern --word 0x...`.
- PE4302 board: parallel control only. Measure the voltage on its supply pads (3.3 V needed) before connecting the SBC. V1 to V6 default low through the module's 10 kohm pull-downs (= 0 dB); optional 2.2 kohm pull-ups to 3.3 V make the default 31.5 dB.
- ADF4351 board: 5 V on the DC jack (check polarity), `CE` and `PDR` high, `LD` to a GPIO.
- [ ] Pass: attenuation changes in 0.5 dB steps and matches the commanded value on a DMM-level check (stage 2 does the RF check).

## Stage 1: ADF4351 and the detector alone
- Needs `Adf4351.registers()` first (see `src/sadiy/drivers/adf4351.py`). Verify the register words against ADI's evaluation software for the same frequency.
- ADF4351 -> fixed pad -> detector. MSO5354 on the pad output (50 ohm termination) for frequency and level; DMM on the detector output.
- Build the detector curve with the pad values known, then add the ADC path. The ADS1115 is the main ADC: read A0 from the Raw access page and compare with the DMM. Then read AIN0 as a cross-check, after confirming the divider output never exceeds 1.8 V at P9.39.
- [ ] Pass: detector voltage follows -24.5 mV/dB within the datasheet tolerance over at least 40 dB.

## Stage 2: attenuator and amp
- Source at about -30 dBm into the PE4302, amp on, MSO5354 on the amp output (50 ohm). Measure amp gain at 35, 100, 200 and 350 MHz. Above 350 MHz use the detector as a relative meter.
- Check attenuator accuracy across 0 to 31.5 dB and gain flatness. Step the input level up to find where the amp compresses.
- [ ] Pass: gain and P1dB measured and written into `config/default.toml` and the level plan.

## Stage 3: mixer, IF filter, IF amp
- Parts from `hw/todo-parts.md` must be fitted first (LPF, LO pad / LPF, IF filter, IF amp).
- Scope on the IF output at 10.7 MHz. First swept trace with one known tone.
- [ ] Pass: tone shows at the right frequency, its image 21.4 MHz away, and the level is within about 2 dB after the first calibration.

## Stage 4: calibration, auto-range, UI
- `tools/cal_run.py` procedure, per-frequency gain table in `cal/gain.json`.
- Check auto-ranging against the compression limits measured in stage 2.
- Remote viewing from the PC for the BBB: `python -m sadiy.ui.sa_gui --host <bbb-ip> --connect` (see `gui.md`). The status bar warns when the point count is too low for the RBW; use "Points = 2·span/RBW" and a narrower span for the first calibrated sweeps.
- [ ] Pass: a sweep over 30 to 480 MHz at a usable rate with calibrated levels.

## Open measurements to settle
- ADF4351 board: reference oscillator frequency, output level versus setting, harmonic content at the pad output.
- PLL lock time and detector settling, to replace `settle_s = 0.0005` with a measured value.
- ADS1115 noise and settling at the rate used. At most 860 SPS limits a sweep to about 1 ms per point.
