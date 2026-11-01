#!/usr/bin/env python3
"""Calibration run. Placeholder: needs the real hardware path (see docs/bringup.md, stage 4).

Procedure to implement:
1. Feed a known level into the analyzer input: the ADF4351 itself (or a signal generator)
   through a fixed, measured attenuator. Level at the input must be known to about 0.5 dB.
2. For each calibration frequency, read the detector with the attenuator at 0 dB and a few
   known input levels. Fit detector slope and intercept at that frequency.
3. Store net gain from input to detector (0 dB attenuation) per frequency with
   sadiy.core.cal.Cal.save() to cal/gain.json.
"""
raise SystemExit(__doc__)
