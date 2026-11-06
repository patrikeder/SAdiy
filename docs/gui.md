# Spectrum analyzer GUI

```
pip install -e .[ui]                      # PyQtGraph + PyQt5 (pyzmq is a core dependency)
python -m sadiy.ui.sa_gui --sim           # start simulated hardware here and connect to it
python -m sadiy.ui.sa_gui --host <bbb-ip> --connect    # view a sweepd running on the BBB
sadiy-gui --sim                           # same, after `pip install -e .`
```

On aarch64 (Raspberry Pi) PyPI has no PyQt5 wheel and pip would try to build it from source. Install `python3-pyqt5` (or `python3-pyqt6`, the GUI runs on Qt5 and Qt6) plus `python3-pyqtgraph python3-zmq python3-numpy` with apt, create the venv with `--system-site-packages` and run `pip install -e . --no-deps` (see the README quick start).

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

## Pins tab

For wiring tests on the BBB. Everything goes through `sweepd`, so it works from a PC against a remote BBB. With `--sim` it drives a fake board; the top of the tab says SIMULATED.

```
cd /opt/sadiy && sudo PYTHONPATH=src python3 -m sadiy.server.sweepd --bench-only --config /etc/sadiy/local.toml   # on the BBB, or the service, see deploy/bbb-setup.md
python -m sadiy.ui.sa_gui --host <bbb-ip> --connect       # on the PC
```

**Enter bench mode** takes over the pins, after asking to stop a running sweep. All lines start safe: PE4302 at 31.5 dB, RF outputs off. **Leave bench mode** returns to the safe state, and so do disconnecting, closing the window, a hardware error, or 5 s without contact with the GUI. Press Run afterwards to sweep again; Run is refused while bench mode is on.

**The board** shows P8 and P9 as in `hw/diagrams/bbb-p*-pinout.svg` (pin 1 at the top, odd pins on the left), coloured by function, with lines to PE4302, ADF4351, ADS1115 and the optional AIN0 cross-check. Dots show live levels (yellow = 1, dark = 0, grey = not known, for example a pin on its SPI bus). Click a pin or a board row to select it.

**Pin page:** net, board pin, GPIO bank and bit, notes, and Drive 0 / Drive 1 / Input / Read / Back to bus.

| Pin | What you can do |
|---|---|
| Wired to a board input | drive, after a confirm the first time per pin |
| Lock detect, ADC inputs | read only |
| Free GPIO | locked until **Expert** is ticked |
| Power, ground, eMMC, HDMI | nothing, display only |

SPI and I2C pins can be driven as GPIO for a wiring check where the image has `config-pin`; otherwise they stay on their bus and the request is refused (check them with hardware SPI frames and an I2C read instead). This switches their mux with `config-pin`, and they return to the bus when a raw command needs them or with **Back to bus**.

**Raw access page:**

- **ADF4351:** send any 32-bit word in hex, one of R5..R0, or all six in order. The boxes check each word's address bits. The R0..R3 and R5 packing is not written yet, so the words come from ADI's software. A word that enables an RF output is refused. To turn one on: send the registers, wait for LD = 1, tick the output, press Apply.
- **PE4302:** set a dB value or V1..V6 through the driver (make-before-break; the actual write order is shown), or tick **Raw, no ordering** to write V1 to V6 in order for a wiring test. In that mode the attenuation can dip during the change.
- **ADC:** ADS1115, the main ADC: convert a channel (code, volts, config and conversion registers), or read the registers without starting a conversion. AIN0: raw and volts at the pin and at the detector, as a cross-check.

**Patterns page:** walking one or zero, square wave on one pin, binary counter, PE4302 stage by stage (one out: never below 15.5 dB; one in: goes down to 0.5 dB), repeated ADF4351 frame.

- The preview updates as you change things and warns when the pattern takes the attenuator low. Keep RF off the input then.
- **Run** once or in a loop, **Stop** at any time. Afterwards the lines go back to safe.
- **Export CSV** writes the line levels after each edge, to compare with a DSLogic capture. It gives edge order, not timing.
- **Rates:** Python on sysfs GPIO manages roughly a few kHz at best, fewer steps/s when a step changes several lines. The figure in the preview is an estimate, not measured on a BBB. While running, the page shows the measured rate. Expect jitter: Linux is not real time here. A square wave's frequency is half the step rate. For the ADF4351 frame the step rate is the word rate, and the SPI clock itself is much faster.

**Tested only on the fake backend.** Unverified on a real BBB: the pin map, pin multiplexing and `config-pin` mode names, PE4302 weights and polarity, ADS1115 registers and bus number, SPI device number, and the rate estimates. See `bringup.md` stage 0.

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
| `ui/bench_tab.py` | the Pins tab: board drawing and controls |
| `ui/bench_core.py` | bench session, confirm memory, input parsing, pattern preview, board layout and hit test: no Qt, unit-tested |
| `ui/sweep_client.py` | ZeroMQ SUB (newest frame only) and REQ with short timeouts |
| `ui/sim_runner.py` | starts / stops `sweepd --sim`, writes the temporary TOML override, keeps the log |
| `tests/test_sa_gui_smoke.py`, `tests/test_bench_gui_smoke.py` | build the window offscreen, feed frames, drive the Pins tab, run the simulator end to end; skipped without PyQt5 / pyqtgraph |

## Known limits

- The RBW is fixed by the IF filter (in the simulator, `[sim] rbw_hz`). The RBW box is only for the display and the points rule, there is no RBW command.
- Reference level and dB/div do not change the attenuator: auto-ranging keeps the sweep peak at -15 dBm at the detector (`core/sweep.py`), same as before.
- A command with no answer blocks the window for up to 0.5 s (the REQ timeout). Sync after connecting uses 0.15 s tries.
- The low-IF image 21.4 MHz away shows up as a second copy of every signal (also in the simulator).
- Peak search treats a rising plateau as a peak at its first point; harmless on real traces.
