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
| Sweep | Run, Stop, Single; points; averages (per point, in sweepd); "Points = 2·span/RBW"; **Image reject (2 sweeps)** |
| Trace | Clear/Write, Max hold, Min hold, Average, View (freeze), Blank; Clear; Store B and Show B |
| Marker | M1, M2 with delta; Peak, Next (next lower peak), Pk ← / Pk →; M→Center, M→Ref; Track peak. Click the display to put M1, Shift+click for M2 |

A marker keeps its frequency when the span changes and disappears when it leaves the screen.

**Flagged points.** `sweepd` marks points it does not trust (see "Per-point handling" in `architecture.md`). Points read without PLL lock, and points at detector overload, get a red × on the trace. In Max hold, Min hold and Average a point stays marked if it was bad in any sweep since the trace was cleared. The marker readout names every flag of its point in brackets: `[unlocked]`, `[overload]`, `[at floor]` (only an upper bound) or `[outlier rejected]`. A `sweepd` that sends no flags (older version) simply shows none.

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

- **ADF4351:** send any 32-bit word in hex, one of R5..R0, or all six in order. The boxes check each word's address bits. `python tools/bringup.py pll --mhz <f>` prints the six words for a frequency; compare them with ADI's software before the first RF test. A word that enables an RF output is refused. To turn one on: send the registers, wait for LD = 1, tick the output, press Apply.
- **PE4302:** set a dB value or V1..V6 through the driver (make-before-break; the actual write order is shown), or tick **Raw, no ordering** to write V1 to V6 in order for a wiring test. In that mode the attenuation can dip during the change.
- **ADC:** ADS1115, the main ADC: convert a channel (code, volts, config and conversion registers), or read the registers without starting a conversion. AIN0: raw and volts at the pin and at the detector, as a cross-check.

**Patterns page:** walking one or zero, square wave on one pin, binary counter, PE4302 stage by stage (one out: never below 15.5 dB; one in: goes down to 0.5 dB), repeated ADF4351 frame.

- The preview updates as you change things and warns when the pattern takes the attenuator low. Keep RF off the input then.
- **Run** once or in a loop, **Stop** at any time. Afterwards the lines go back to safe.
- **Export CSV** writes the line levels after each edge, to compare with a DSLogic capture. It gives edge order, not timing.
- **Rates:** Python on sysfs GPIO manages roughly a few kHz at best, fewer steps/s when a step changes several lines. The figure in the preview is an estimate, not measured on a BBB. While running, the page shows the measured rate. Expect jitter: Linux is not real time here. A square wave's frequency is half the step rate. For the ADF4351 frame the step rate is the word rate, and the SPI clock itself is much faster.

**Tested only on the fake backend.** Unverified on a real BBB: the pin map, pin multiplexing and `config-pin` mode names, PE4302 weights and polarity, ADS1115 registers and bus number, SPI device number, and the rate estimates. See `bringup.md` stage 0.

## Synth tab

Sets the ADF4351 to a preset LO frequency or to your own, and shows what it was told. It uses bench mode (same switch as the Pins tab, so a running sweep is stopped after asking; leaving returns the board to the safe state). The buttons work only while bench mode is on. The frequency is the **LO** (the ADF4351 output), not the RF input: for the default 10.7 MHz IF with the LO above the signal, LO = RF + 10.7 MHz.

| Preset | LO | Why |
|---|---|---|
| 100 MHz CW (first light) | 100 MHz | the bring-up test frequency, integer-N (VCO 3.2 GHz / 32): the easiest lock to see |
| LO for a 100 MHz / 250 MHz signal | 110.7 / 260.7 MHz | where a sweep puts the LO for the two simulated tones; fractional-N, so it exercises FRAC / MOD |
| Sweep start / center / stop | 40.7 / 265.7 / 490.7 MHz | the LO over the full-span sweep (30 to 480 MHz RF), the stop is near the AD831's 500 MHz limit |
| Image check | 89.3 MHz | the LO on the other side of 100 MHz that image rejection uses |

The list follows what `sweepd` reports (RF range, IF, injection, PFD), so another IF in the config changes it; presets the ADF4351 or the mixer can not do are left out. Selecting one fills **Frequency** and **Output power** (-4, -1, +2, +5 dBm), which can be edited. The line below shows how the chip would make it (integer or fractional-N, INT, FRAC / MOD, VCO and divider) before anything is sent.

**Apply** does what the daemon's `bench_synth` does in one step: outputs off, write R5 to R0, wait up to 0.2 s for lock detect. The main output (RFOUTA) turns on only if **Turn the main output on after lock** is ticked (off by default) and the PLL locked; it asks for a confirm every time. An unlocked PLL leaves the output off and says so in the status bar and the device log. Above 500 MHz the output is refused, the PLL can still be programmed to look at it elsewhere. **RF off** always works. The first Apply per bench session also asks the usual SPI confirm.

**Readback.** The ADF4351 can not be read over SPI on this wiring (MUXOUT is not connected), so the readback is the words last written in this session, decoded the way the chip reads them (frequency = (INT + FRAC / MOD) x PFD / divider, prescaler, main and aux output and power), plus the live LD pin. It shows what the chip was told, not what it does: LD is the only measurement. Raw words from the Pins tab show up too. The same line is in the **status bar** on every tab, for example `LO 110.700000 MHz   LD 1   RF main -4 dBm`. Outside bench mode it asks `sweepd` for its status about every 1.5 s (5 s when it does not answer) and shows the LO of the last point tuned while sweeping: `LO 150.700 MHz (sweeping)   LD 1`. Nothing is shown when not connected, or `LO not programmed` right after entering bench mode (only the outputs-off R4 was written).

**Tested only on the fake backend**, like the Pins tab: the register words themselves are unverified against ADI's software (see `CLAUDE.md`, "Not done yet"). First light with this tab replaces sending the six words by hand: compare the words in the readback with ADI's software, then apply "100 MHz CW".

## Advanced tab

- **Connection**: host and the two ports. On connect the GUI reads sweepd's settings and limits and adopts them (so it shows what a remote BBB is doing). Commands that sweepd rejects show its error in the status bar.
- **Device log**: what `sweepd` reports, plus the GUI's own notes (connecting, connection problems, and every warning that the status bar showed). Records come live from the daemon, and on connect the GUI also fetches what the daemon kept before, so the box is complete after a reconnect or a late start. Lines are coloured by level (red error, amber warning, grey debug). Controls: **Show** is the lowest level listed (Error, Warning, Info, Debug; the default is Info; changing it re-lists everything kept, up to 2000 lines), **Pause** stops adding lines but keeps them (they appear when unticked), **Clear**, **Save…** (all lines with the date, to `captures/` by default). While you are on another tab, the Advanced tab title and the status bar count unread warnings and errors, for example `Advanced (1 error, 2 warnings)`; the status-bar count jumps to the tab when clicked, and an error also shows in the status bar. A daemon restart shows as a marker line. Per-point and per-SPI-word detail (trace) never reaches the GUI: start `sweepd` with `-vv` and read it over ssh with `journalctl -u sweepd -f`. A `sweepd` without a log (older version) shows a note after a few tries.
- **Simulated hardware**: starts `python -m sadiy.server.sweepd --sim` as a separate process on this PC, bound to 127.0.0.1 on the ports above. Parameters: sweep period, input noise floor, simulated RBW, up to four test tones (frequency, level, on/off). They are applied when the simulator starts; stop and start it to change them. "Connect after start" connects automatically. The process output shows in the log box.
- **Analyzer**: RBW used for the display and the points rule (follows the simulated RBW when the simulator starts), frequency limits, peak threshold above the median, number of sweeps in Average mode, GUI poll interval.
- **Data**: save the trace as CSV (`freq_hz,level_dbm`), save a screenshot as PNG. Both default to `captures/`, which is git-ignored.

## Files

| File | Role |
|---|---|
| `ui/sa_gui.py` | Qt window (PyQtGraph display, controls, tabs) |
| `ui/sa_core.py` | axis, settings clamping, trace modes, peak search, markers, CSV: no Qt, unit-tested |
| `ui/log_core.py` | the Device log's state: numbered, duplicate-free records, gap and restart detection, unread counters, levels: no Qt, unit-tested |
| `ui/bench_tab.py` | the Pins tab: board drawing and controls |
| `ui/synth_tab.py` | the Synth tab: presets, frequency and power, the readback (uses the Pins tab's bench session) |
| `ui/synth_core.py` | presets from sweepd's status, plan preview, readback texts: no Qt, unit-tested |
| `ui/bench_core.py` | bench session, confirm memory, input parsing, pattern preview, board layout and hit test: no Qt, unit-tested |
| `ui/sweep_client.py` | ZeroMQ SUB (newest frame only, all log records, flags of the last frame) and REQ with short timeouts, `fetch_log` |
| `ui/sim_runner.py` | starts / stops `sweepd --sim`, writes the temporary TOML override, keeps the log |
| `tests/test_sa_gui_smoke.py`, `tests/test_bench_gui_smoke.py`, `tests/test_synth_gui_smoke.py` | build the window offscreen, feed frames and flags, drive the Pins tab and the Device log, run the simulator end to end; skipped without PyQt5 / pyqtgraph |
| `tests/test_log_core.py`, `tests/test_sweep_client_log.py` | log buffer logic; the client against real ZeroMQ sockets on localhost |

## Known limits

- The RBW is fixed by the IF filter (in the simulator, `[sim] rbw_hz`). The RBW box is only for the display and the points rule, there is no RBW command.
- Reference level and dB/div do not change the attenuator: auto-ranging keeps the sweep peak at -15 dBm at the detector (`core/sweep.py`), same as before.
- A command with no answer blocks the window for up to 0.5 s (the REQ timeout). Sync after connecting uses 0.15 s tries.
- The low-IF image 21.4 MHz away shows up as a second copy of every signal (also in the simulator) unless **Image reject** is ticked: `sweepd` then sweeps twice with the LO above and below and keeps the lower reading, so a trace takes twice as long and the info line shows `IMG REJ`. Points below about 45 MHz can not be done that way and keep their image (flag `[image not suppressed]` at a marker; the daemon logs where suppression starts). Not verified on the real mixer.
- Peak search treats a rising plateau as a peak at its first point; harmless on real traces.
- The Device log keeps 2000 lines in the GUI and the daemon 500; older ones are gone. A fetch (on connect, after a gap) blocks the window for up to 0.15 s when the daemon is slow.
- Log lines of a simulator the GUI started also appear in the simulator's own process box under "Simulated hardware", because that box shows the child's stderr.
