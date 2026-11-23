# Parts still missing, in priority order

1. **IF stage, digital branch (EBAZ4205 PL engine)**. Decided 2026-11-23: no log detector and no ceramic filter. The IF goes through **two 30 MHz low-pass modules in series** (7th order Chebyshev, SMA; the only low-pass option on offer) into an **AD9226 module** (12 bit, 65 MS/s, ordered; sampled at 50 MS/s). The RBW is set digitally in the PL (CIC filter after the 10.7 MHz down-conversion), so no IF filter for it is needed. To buy or build: the two low-pass modules, an SMA-SMA adapter between them, and the **adapter v2** that wires the 14 DATA1 signals to the module (no HDMI, no LCD on those balls). Optional upgrade: a home-made 3 MHz bandpass at 10.7 MHz. An IF amp is only needed if the measured level asks for it (about 26 dB chain gain puts full scale at about -2 dBm at the RF input). The AD8310 is **not** bought. Record: [../zynq-ebaz/docs/adc-module.md](../zynq-ebaz/docs/adc-module.md).
   **BBB path (analog, unchanged plan):** 10.7 MHz ceramic filter (about 150 to 280 kHz), optional crystal filter, 15 to 20 dB IF gain, and a log detector. The AD8318 module that was built in is dead, a replacement is not bought; the BBB path has no detector until one is.
2. **Input low-pass filter, about 500 MHz**, between the PE4302 and the amp. The amp is wideband to 2 GHz and would otherwise compress on strong FM, DAB, GSM and LTE signals.
3. **LO low-pass filter + 3 to 6 dB pad** on the ADF4351 output. LO drive should be -10 dBm; the synthesizer minimum is -4 dBm and its harmonics are only 10 to 20 dB down.
4. **ADC handling**: done on the adapter board (RC + clamp to the ADS1115 A0, and a divider so the detector output cannot exceed 1.8 V at the optional BBB AIN0 cross-check). The ADS1115 module itself is the main ADC of the analog path; with the dead detector it has nothing to read until a detector exists. The AD9226 module is the digitizer of the digital IF branch (item 1).
5. **DC block + ESD protection or limiter** at the RF input.
6. **Power**: 12 V input, 5 V buck (also for the ADF4351 board's DC jack), 10 V rail for AD831 and amp, ferrites between rails. The PE4302 and ADS1115 take 3.3 V from the SBC pin.
7. **Shielded enclosure**, SMA cables, 50 ohm terminations.
8. Optional: 10 MHz TCXO as reference for the ADF4351 board.
9. Done on the adapter board: **2.2 kohm pull-ups to 3.3 V on the PE4302 inputs V1 to V6** (R27..R32). The module has 10 kohm pull-downs, so open inputs are 0 dB; the pull-ups make the boot-time default 31.5 dB.
10. Terminator (50 ohm) on the unused ADF4351 output, if not already fitted.
