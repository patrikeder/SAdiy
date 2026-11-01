# Spectrum analyzer GUI

```
pip install -e .[ui]                      # PyQtGraph + PyQt5 (pyzmq is a core dependency)
python -m sadiy.ui.sa_gui --sim           # start simulated hardware here and connect to it
python -m sadiy.ui.sa_gui --host <bbb-ip> --connect    # view a sweepd running on the BBB
sadiy-gui --sim                           # same, after `pip install -e .`
```

The GUI is a client of `sweepd` (ZeroMQ, see `architecture.md`). It never touches SPI / GPIO. Closing it also stops a simulator it started.

## Spectrum tab

Black display, 10 x 10 graticule, yellow trace A, blue stored trace B, red markers. Info line above the display (reference level, attenuation, RBW, scale, points, sweep time), start / center-span / stop under it, marker readout at the bottom. Controls on the right:

| Group | What |
|---|---|
| Frequency | center, span, start, stop in MHz; Full span, Span ÷2, Span ×2. Entries are clamped to the limits sweepd reports (30 to 480 MHz by default); center is clamped given the span, as on a bench analyzer |
| Amplitude | reference level and dB/div (display only), attenuator Auto or manual in 0.5 dB steps (sent to sweepd), Auto scale fits level and scale to the trace |
| Sweep | Run, Stop, Single; points; averages (per point, in sweepd); "Points = 2·span/RBW" |
| Trace | Clear/Write, Max hold, Min hold, Average, View (freeze), Blank; Clear; Store B and Show B |
| Marker | M1, M2 with delta; Peak, Next (next lower peak), Pk ← / Pk →; M→Center, M→Ref; Track peak. Click the display to put M1, Shift+click for M2 |

A marker keeps its frequency when the span changes and disappears when it leaves the screen.

The status bar warns when the step is larger than RBW/2 (narrow signals read low, see "Points versus RBW" in `architecture.md`). With the default 401 points over 30 to 480 MHz it shows up at once. Use "Points = 2·span/RBW" or a narrower span.

## Advanced tab

- **Connection**: host and the two ports. On connect the GUI reads sweepd's settings and limits and adopts them (so it shows what a remote BBB is doing). Commands that sweepd rejects show its error in the status bar.
- **Simulated hardware**: starts `python -m sadiy.server.sweepd --sim` as a separate process on this PC, bound to 127.0.0.1 on the ports above. Parameters: sweep period, input noise floor, simulated RBW, up to four test tones (frequency, level, on/off). They are applied when the simulator starts; stop and start it to change them. "Connect after start" connects automatically. The process output shows in the log box.
- **Analyzer**: RBW used for the display and the points rule (follows the simulated RBW when the simulator starts), frequency limits, peak threshold above the median, number of sweeps in Average mode, GUI poll interval.
- **Data**: save the trace as CSV (`freq_hz,level_dbm`), save a screenshot as PNG. Both default to `captures/`, which is git-ignored.

## Files

| File | Role |
|---|---|
| `ui/sa_gui.py` | Qt window (PyQtGraph display, controls, tabs) |
| `ui/sa_core.py` | axis, settings clamping, trace modes, peak search, markers, CSV: no Qt, unit-tested |
| `ui/sweep_client.py` | ZeroMQ SUB (newest frame only) and REQ with short timeouts |
| `ui/sim_runner.py` | starts / stops `sweepd --sim`, writes the temporary TOML override, keeps the log |
| `tests/test_sa_gui_smoke.py` | builds the window offscreen, feeds frames, runs the simulator end to end; skipped without PyQt5 / pyqtgraph |

## Known limits

- The RBW is fixed by the IF filter (in the simulator, `[sim] rbw_hz`). The RBW box is only for the display and the points rule, there is no RBW command.
- Reference level and dB/div do not change the attenuator: auto-ranging keeps the sweep peak at -15 dBm at the detector (`core/sweep.py`), same as before.
- A command with no answer blocks the window for up to 0.5 s (the REQ timeout). Sync after connecting uses 0.15 s tries.
- The low-IF image 21.4 MHz away shows up as a second copy of every signal (also in the simulator).
- Peak search treats a rising plateau as a peak at its first point; harmless on real traces.
