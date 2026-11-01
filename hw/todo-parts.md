# Parts still missing, in priority order

1. **IF stage**: 10.7 MHz ceramic filter (about 150 to 280 kHz, first RBW), optional crystal filter for narrow RBW, and about 15 to 20 dB IF gain (ideally variable). Without it the detector sees the whole IF passband and there is no RBW.
2. **Input low-pass filter, about 500 MHz**, between the PE4302 and the amp. The amp is wideband to 2 GHz and would otherwise compress on strong FM, DAB, GSM and LTE signals.
3. **LO low-pass filter + 3 to 6 dB pad** on the ADF4351 output. LO drive should be -10 dBm; the synthesizer minimum is -4 dBm and its harmonics are only 10 to 20 dB down.
4. **ADC handling**: divider + RC + clamp so the detector output cannot exceed 1.8 V at the BBB ADC. An external ADC is required on the RPi (start with ADS1115).
5. **DC block + ESD protection or limiter** at the RF input.
6. **Power**: 12 V input, 5 V buck, 10 V rail for AD831 and amp, own 3.3 V LDO for the synthesizer, ferrites between rails.
7. **Shielded enclosure**, SMA cables, 50 ohm terminations.
8. Optional: 10 MHz TCXO as reference for the ADF4351 board.
9. Optional: **2.2 kohm pull-ups to 3.3 V on the PE4302 inputs V1 to V6**. The module has 10 kohm pull-downs, so open inputs are 0 dB; stronger pull-ups make the boot-time default 31.5 dB.
10. Terminator (50 ohm) on the unused ADF4351 output, if not already fitted.
