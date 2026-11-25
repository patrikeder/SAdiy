# Bring-up plan

Instruments on hand: several DMMs, Rigol MSO5354 (350 MHz), Rigol DS2072 (200 MHz), DSLogic logic analyzer.
Each stage lists the board test points it uses (see `hw/test-points.md`). Tick a stage only when its pass criteria are met.

## Stage 0: rails and control lines
- Measure each rail at its board before connecting the next board (`hw/test-points.md`).
- Pin check from the GUI: start `sweepd` on the BBB (`deploy/bbb-setup.md`, Run), then on the PC run `python -m sadiy.ui.sa_gui --host <bbb-ip> --connect`, then Pins tab, Enter bench mode. No RF connected yet. Keep the Advanced tab's Device log in view (or `journalctl -u sweepd -f` over ssh, with `-v` for debug): bench open warnings (SPI, I2C or the PCF8574 of the PE4302 not available), hardware errors and lease expiry are reported there with the reason.
  1. With no boards connected, first check the pin map itself: DMM or DSLogic on each pin in turn, Drive 0 / Drive 1 from the Pin page. This is the first test of the pin map and the pin mux on the real image, so correct `src/sadiy/pinmap.py` if a pin does not move.
  2. With boards connected, DSLogic on the module headers: Patterns page, walking one over ATT_V1..V6 (measured at the PE4302 header, behind the PCF8574), then over SYN_CLK, SYN_DATA and SYN_LE. Export the CSV and compare the edge order. A line that stays still or moves with another is an open or a short. Walking the SPI lines can latch junk into the ADF4351; the daemon sends an outputs-off R4 afterwards.
  3. I2C: `i2cdetect -y -r <bus>` must show the PCF8574 (0x27 by default; BBB bus 2, EBAZ4205 bus 0). Raw access page: set a few dB values; no read-back warning may appear. A warning names the V lines without a working 2.2 kohm pull-up.
- Identify V1 to V6: run `python tools/bringup.py pe4302-walk` on the SBC (as root, `sweepd` stopped; `--platform ebaz` before the command on the EBAZ4205). One stage is switched in at a time; check each line with a DMM at the PE4302 header, and the weight with a low-level tone through the attenuator on the scope (the log detector the tool's text assumes is dead). Write the weights and polarity into `config/default.toml` (on the BBB into `/etc/sadiy/local.toml`, which survives updates).
- DSLogic on V1 to V6: `python tools/bringup.py pe4302-pattern --db 16 --from-db 15.5` prints the write order; the capture must match and the lowest attenuation during the change must not drop below 15.5 dB. On the wire this is one I2C transaction of two bytes (the first adds the new stage, the second drops the old ones), 90 us apart at 100 kHz: capture SCL and SDA too and decode them. Do the same for the ADF4351 SPI lines with `adf4351-pattern --word 0x...`.
- PE4302 board: parallel control only, driven by a PCF8574 on I2C (wiring: `hw/boards/pe4302.md`). Measure the voltage on its supply pads (3.3 V needed), and supply the PCF8574 board from 3.3 V too. V1 to V6 default low through the module's 10 kohm pull-downs (= 0 dB). The 2.2 kohm pull-ups to 3.3 V (on the adapter board R27..R32) are required: the PCF8574 drives high only weakly. With them, V high is above 2.3 V and the attenuator powers up at 31.5 dB.
- ADF4351 board: 5 V on the DC jack (check polarity), `CE` and `PDR` high, `LD` to a GPIO.
- [ ] Pass: attenuation changes in 0.5 dB steps and matches the commanded value on a DMM-level check (stage 2 does the RF check).

## Stage 1: ADF4351 and the detector alone
- Lock detect gating needs the `SYN_LD` line read by the real engine (`build_hw_engine`): check in the Device log that sweeps report no unlocked points.
- Words from `python tools/bringup.py pll --mhz <f>` (`Adf4351.registers()` in `src/sadiy/drivers/adf4351.py`). Verify them against ADI's evaluation software for the same frequency first.
- ADF4351 -> fixed pad -> detector. MSO5354 on the pad output (50 ohm termination) for frequency and level; DMM on the detector output.
- Build the detector curve with the pad values known, with a DMM. On the BBB then read AIN0 (Raw access page) and compare, after confirming the divider output never exceeds 1.8 V at P9.39. (The detector is dead; on the EBAZ4205 the AD9226 takes this place.)
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
- ADC noise and settling at the rate used: AD9226 behind the PL's IF path on the EBAZ4205, AIN0 through IIO on the BBB. Measure the real time per point and its split (tune, settle, ADC, CPU idle) with `sweepd -vv` (see "Time per point and the PRUs" in `architecture.md`).
- Standard deviation of 100 detector reads at a fixed frequency: whether averaging several reads per point buys anything, and whether `outlier_db = 3` and the detector window (`floor_dbm`, `max_dbm`) fit the real detector.
