# Spectrum analyzer GUI

Steps to start the server and the GUI: [how-to-start.md](how-to-start.md).

```
pip install -e .[ui]                      # PyQtGraph + PyQt5 (pyzmq is a core dependency)
python -m sadiy.ui.sa_gui --sim           # start simulated hardware here and connect to it
python -m sadiy.ui.sa_gui --host <bbb-ip> --connect    # view a sweepd running on the BBB
sadiy-gui --sim                           # same, after `pip install -e .`
python -m sadiy.ui.sa_gui --platform ebaz --host <ebaz-ip> --connect   # fix the board: only the EBAZ4205 is shown
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

**Small screens.** Every tab fits a window of about 600 px height; the Advanced tab, the longest, scrolls when the window is lower than its content (on a 1080 px display the window used to be forced to 1194 px).

**Saved settings (Settings menu).** The GUI remembers what you set. The settings are the frequencies, points, averages, attenuation (and Auto), image reject, reference level, dB/div and the trace mode; as `default.json` in the settings folder the GUI also keeps the host and ports of the connection. The folder is `$SADIY_CONFIG_DIR`, else `$XDG_CONFIG_HOME/sadiy`, else `~/.config/sadiy` (the menu item *Show settings folder* names it). It is per PC and not in the repository.
- **At the start** the GUI loads `default.json` (the first time there is none: the settings as delivered). A host or port given on the command line wins over the saved connection. When you connect the first time, the saved settings are sent to `sweepd` (it was told what it measures); a later reconnect adopts what `sweepd` has, as before. On a first start nothing is sent.
- **At exit** `default.json` is written. *Save as default* does it at once. While the GUI is connected to the simulator it started, the saved host stays.
- **Save as...** stores the setup under a name (letters, digits, space and `_ . - + ( )`) in `settings/<name>.json` of the folder; **Load** lists the saved names and applies one to the controls and, when connected, to `sweepd`; **Delete** removes one after asking. Named settings hold the measurement setup only, so loading one never changes the host.
- **Restore settings as delivered** takes the values of `config/default.json` of the repository (never written by the program; the built-in values are the fallback), applies them and makes them the next start's `default.json`. Named settings stay.
- Values that are not usable (a frequency outside the range, 5000 points, an unknown trace mode) are clamped or replaced and named in the status bar; a damaged `default.json` is reported in the device log and the as-delivered values are used. Files are JSON, written whole or not at all (`ui/settings_core.py` has the layout).

**Flagged points.** `sweepd` marks points it does not trust (see "Per-point handling" in `architecture.md`). Points read without PLL lock, and points at detector overload, get a red × on the trace. In Max hold, Min hold and Average a point stays marked if it was bad in any sweep since the trace was cleared. The marker readout names every flag of its point in brackets: `[unlocked]`, `[overload]`, `[at floor]` (only an upper bound) or `[outlier rejected]`. A `sweepd` that sends no flags (older version) simply shows none.

The status bar warns when the step is larger than RBW/2 (narrow signals read low, see "Points versus RBW" in `architecture.md`). With the default 401 points over 30 to 480 MHz it shows up at once. Use "Points = 2·span/RBW" or a narrower span.

## Pins tab

**Platform.** The tab draws the board `sweepd` runs on: the BeagleBone Black (headers P8 and P9) or the EBAZ4205 (connectors DATA2, DATA1, DATA3; pin ids like `DATA2.14`). Two ways to choose:

- Without `--platform` the tab has a **Platform** selector. It follows `sweepd` as soon as the GUI connects (`status` and `bench_open` name the platform, `sweepd --platform bbb|ebaz` or `[platform] name` in its config) and can be changed by hand while bench mode is off. A simulator started from the Advanced tab runs the platform that is shown.
- With `--platform bbb` or `--platform ebaz` the selector is hidden and the other board does not appear anywhere (drawing, pin list, text). If that `sweepd` runs on the other platform, bench mode is refused with a message that says so.

For wiring tests on the BBB or the EBAZ4205. Everything goes through `sweepd`, so it works from a PC against a remote board. With `--sim` it drives a fake board; the top of the tab says SIMULATED. The tab behaves the same on both boards; what differs is below.

### Using it on the BeagleBone Black

```
cd /opt/sadiy && sudo PYTHONPATH=src python3 -m sadiy.server.sweepd --bench-only --config /etc/sadiy/local.toml   # on the BBB, or the service, see deploy/bbb-setup.md
python -m sadiy.ui.sa_gui --platform bbb --host <bbb-ip> --connect       # on the PC (--platform optional)
```

The board drawing shows P8 and P9 as in `hw/diagrams/bbb-p*-pinout.svg` (pin 1 at the top, odd pins on the left), with lines to the PCF8574 (which drives the PE4302 attenuator), the ADF4351 and AIN0. SPI and I2C pins can be driven as GPIO where the image has `config-pin` (this image has none, so they stay on their bus). Free GPIO (P8.7 to P8.19, P8.26 on a stock image) are locked until **Expert** is ticked. P8.7 to P8.12 were the PE4302 lines: the adapter board still routes them to its PE4302 header, so leave them alone while the PCF8574 is wired there.

### Using it on the EBAZ4205

Status: **the Pins tab works on the real EBAZ4205 only with `sweepd --platform ebaz --bench-only`** (Linux owns the pins: PS GPIO, `/dev/spidev0.0`, `/dev/i2c-0`; run on the board 2026-11-16 with the old attenuator wiring: ADF4351 frequency setting, PE4302 attenuation and ADC readings worked; the PCF8574 has not run on the board). While `sweepd --platform ebaz` sweeps through the PL engine there is no bench mode, because the engine owns the pins: wiring tests and sweeping are two separate runs of `sweepd`. On the board (as root, `. ~/sadiy/env.sh` first):

```
sudo env PYTHONPATH=$PYTHONPATH python3 -m sadiy.server.sweepd --platform ebaz --bench-only      # on the board
python -m sadiy.ui.sa_gui --platform ebaz --host <ebaz-ip> --connect                                # on the PC
```

Without the board:

```
python -m sadiy.ui.sa_gui --platform ebaz --sim                  # the EBAZ board drawing against a simulated sweepd (try the whole tab)
python -m sadiy.server.sweepd --sim --platform ebaz &            # the same without a GUI, then
python -m sadiy.ui.sa_gui --platform ebaz --host 127.0.0.1 --connect
python tools/bringup.py --platform ebaz gpio-map                 # DATA2 pin, EMIO number and Linux GPIO number of every net
```

Other scripts that run on the board: `zynq-ebaz/sw/tools/ebaz_s4_readonly.sh` and `ebaz_s4_readback.sh` (EMIO and pad levels), `ebaz_lcd_test.py` (LCD, LEDs, keys) and the checklist in `zynq-ebaz/docs/ebaz-bringup.md`. Deployment to the board: `zynq-ebaz/sw/deploy/README.md`. The EBAZ's address is the one on its Ethernet port.

Differences from the BBB, all visible in the tab:

- A **View** selector (EBAZ4205 only) switches the left part between the **Adapter board** (default: the picture `zynq-ebaz/docs/pinmap-adapter.svg` made by `rtl/scripts/gen_pinmap.py`: UART header, USB-C, HDMI, LEDs, buzzer, LCD, keys and the right connector with its signals, FPGA ball and bank for each; re-read from the file at each start of the GUI; drawn on the window's own colours, not on a white page: the file's white background is left out and its plain text takes the window's text colour; pins are clickable here too: a click on a circle, key, LED or label selects the pin, as in the connectors view, the selected one gets a red frame, and the regions are read from the picture itself, so a regenerated picture keeps working) and the **Connectors** drawing described next, where pins are clicked. Power and ground pins and NC have no region there; choose those in the connectors view. Without the file (a GUI started away from the checkout) the connectors drawing is shown and the selector is hidden. Qt's SVG module is not needed: without it (a PyQt6 on Raspberry Pi OS has none unless `python3-pyqt6.qtsvg` is installed) the same picture is painted by hand from the shapes in the file (`bench_core.adapter_shapes`), looking almost the same. The BeagleBone has no such picture.
- The drawing shows DATA2 (the adapter's signals), DATA1 and DATA3 (display, keys and LEDs: shown only, they can not be driven here) with lines to the PCF8574 and the ADF4351. There is no AIN0 and no on-chip ADC, so the Raw access page has no ADC box.
- No pin mux: SPI (DATA2.5, .7, .8) and I2C (DATA2.20, .11) are wired to the PS in the bitstream, so they can not be driven as GPIO and **Back to bus** is not needed. SYN_CE (DATA2.13) and lock detect (DATA2.9, read only) are EMIO GPIO and work as on the BBB. The former PE4302 pins DATA2.14 to .19 are spare EMIO GPIO.
- Pin ids are `DATA<n>.<pin>`; the pin page shows the FPGA ball in the name, `GPIO: EMIO n (Linux line 54 + n)` and the adapter pin it goes to.
- **Expert** unlocks only the six spare EMIO pins DATA2.14 to .19 (do not drive them while old attenuator wires are still connected). Every other connector pin without a net is display-only.

**Enter bench mode** takes over the pins, after asking to stop a running sweep. All lines start safe: PE4302 at 31.5 dB, RF outputs off. **Leave bench mode** returns to the safe state, and so do disconnecting, closing the window, a hardware error, or 5 s without contact with the GUI. Press Run afterwards to sweep again; Run is refused while bench mode is on.

**The board** is coloured by function. Dots show live levels (yellow = 1, dark = 0, grey = not known, for example a pin on its SPI bus). Click a pin or a board row to select it.

**Pin page:** net, board pin, GPIO (bank and bit on the BBB, EMIO number on the EBAZ), notes, and Drive 0 / Drive 1 / Input / Read / Back to bus.

| Pin | What you can do |
|---|---|
| Wired to a board input | drive, after a confirm the first time per pin |
| Lock detect, ADC inputs | read only |
| Free GPIO (EBAZ: the spare EMIO pins DATA2.14 to .19) | locked until **Expert** is ticked |
| Power, ground, eMMC, HDMI (BBB); display, keys, LEDs, power, ground (EBAZ) | nothing, display only |

On the BBB, SPI and I2C pins can be driven as GPIO for a wiring check where the image has `config-pin`; otherwise (and always on the EBAZ4205) they stay on their bus and the request is refused (check them with hardware SPI frames and an I2C read instead). This switches their mux with `config-pin`, and they return to the bus when a raw command needs them or with **Back to bus**.

**Raw access page:**

- **ADF4351:** send any 32-bit word in hex, one of R5..R0, or all six in order. The boxes check each word's address bits. `python tools/bringup.py pll --mhz <f>` prints the six words for a frequency; compare them with ADI's software before the first RF test. A word that enables an RF output is refused. To turn one on: send the registers, wait for LD = 1, tick the output, press Apply.
- **PE4302 (through the PCF8574):** set a dB value or V1..V6. The driver writes the port in one I2C transaction (two bytes where stages switch both in and out: new stages in first) and the page shows the bytes and the lines that changed. **Raw: one byte (wiring test)** writes exactly the ticked levels in one byte; the attenuation can dip during the change. The port is read back after each write: if a pin does not follow, a warning names the lines (each V line needs a 2.2 kohm pull-up to 3.3 V). The attenuator is not available while an I2C pin is driven as GPIO.
- **ADC** (BeagleBone only): the on-chip AIN0, raw and volts at the pin and at the detector. The EBAZ4205 has no ADC in bench mode.

**Patterns page:** walking one or zero, square wave on one pin, binary counter, PE4302 stage by stage (one out: never below 15.5 dB; one in: goes down to 0.5 dB), repeated ADF4351 frame. The signals ATT_V1..V6 in the pin list are the PCF8574's outputs: each step that changes them is one I2C write, and they cannot be mixed with I2C pins driven as GPIO. A logic analyzer sees them on the PCF8574's pins or the PE4302 header.

- The preview updates as you change things and warns when the pattern takes the attenuator low. Keep RF off the input then.
- **Run** once or in a loop, **Stop** at any time. Afterwards the lines go back to safe.
- **Export CSV** writes the line levels after each edge, to compare with a DSLogic capture. It gives edge order, not timing.
- **Rates:** Python on sysfs GPIO (BBB; the EBAZ numbers will differ and are not measured) manages roughly a few kHz at best, fewer steps/s when a step changes several lines. The figure in the preview is an estimate, not measured on a BBB. While running, the page shows the measured rate. Expect jitter: Linux is not real time here. A square wave's frequency is half the step rate. For the ADF4351 frame the step rate is the word rate, and the SPI clock itself is much faster.

**Tested only on the fake backend.** Unverified on a real BBB or EBAZ4205 (the EBAZ pin locations and EMIO numbers are still to be probed at the bench): the pin map, pin multiplexing and `config-pin` mode names, PE4302 weights and polarity, the PCF8574 (address, bus number, pull-ups, never run with a real one), SPI device number, and the rate estimates. See `bringup.md` stage 0.

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

**Readback.** The ADF4351 can not be read back on this wiring: the adapter leaves the MUX header pin unwired and R2 sets MUXOUT to three-state, so there is nothing to read it with (and the datasheet's MUXOUT options, which are not checked here, are for signals such as the R and N divider outputs, not for reading registers). So the readback is the words last written in this session, decoded the way the chip reads them (frequency = (INT + FRAC / MOD) x PFD / divider, prescaler, main and aux output and power), plus the live LD pin. It shows what the chip was told, not what it does: LD is the only measurement. Raw words from the Pins tab show up too. The same line is in the **status bar** on every tab, for example `LO 110.700000 MHz   LD 1   RF main -4 dBm`. Outside bench mode it asks `sweepd` for its status about every 1.5 s (5 s when it does not answer) and shows the LO of the last point tuned while sweeping: `LO 150.700 MHz (sweeping)   LD 1`. Nothing is shown when not connected, or `LO not programmed` right after entering bench mode (only the outputs-off R4 was written).

**Tested only on the fake backend**, like the Pins tab: the register words themselves are unverified against ADI's software (see `CLAUDE.md`, "Not done yet"). First light with this tab replaces sending the six words by hand: compare the words in the readback with ADI's software, then apply "100 MHz CW".

## Advanced tab

- **Connection**: host and the two ports. On connect the GUI reads sweepd's settings and limits and adopts them (so it shows what a remote BBB is doing). Commands that sweepd rejects show its error in the status bar.
- **Ramp self-test** (EBAZ4205 PL engine only): the button asks `sweepd` to run the engine's own test ramp and check the results against known values (no RF, no ADC, no synthesiser writes; criteria in `zynq-ebaz/docs/selftest.md`). `sweepd` answers commands between two sweeps, so the test starts when the sweep in progress ends (up to a few seconds), sweeping pauses for about a second and then goes on by itself; the engine keeps its pins and the sweep table is sent again. The line next to the button shows **PASS** (green) or **FAIL** (red) with the number of checks, and the box below lists every failed check (first wrong index, likely cause) or one line per sweep. Options: **Sweeps** (1 to 20 checked sweeps, each with another test base; a poison sweep comes first), **Wrap run** (a second run with N_AVG 1, base 0xFFF0), **Full memory** (4096 points). The button stays off, with the reason next to it, when `sweepd` has no such engine (`--sim`, `--bench-only`, BeagleBone); the GUI waits for the answer without freezing and a disconnect cancels it. `sweepd` also writes the verdict into the Device log (`self-test PASS` / `self-test FAIL`). The command is `selftest` (see `server/protocol.py`, `status.selftest_available`); the same test runs without the GUI as `~/sadiy/selftest.sh` (sweepd stopped).
- **Virtual spectrum** (EBAZ4205 PL engine, needs the module `sadiy_ebaz/virtual_spectrum.py` of the RTL lane): the button replaces the real sweep by one made inside the PL: its sample generator plays three tones, the IF path (NCO, mixer, CIC, power) steps over the points, and the normal chain shows the result as a spectrum with peaks at 100, 200 and 300 MHz of the displayed axis (-30, -45 and -60 dBm) on a noise floor of about -90 dBm, drifting slowly back and forth with new noise every sweep (sweeps are kept at least 0.1 s apart, so the drift takes a few seconds). It checks the whole chain from the table to the GUI without any RF around it; the label shows `VIRTUAL SPECTRUM, not RF` with the sweep number and the drift, and the status bar says so. While it runs every frame carries the expected trace (noise-free, before detector clipping, so it stays at the floor level where the measured trace shows the floor flag) and the display draws it as a dashed grey line under trace A: measured and expected must agree on the peaks. The button also waits for the sweep in progress and does not freeze the GUI. It is off while the self-test runs and refused in bench mode; a failed sweep or stopping `sweepd` switches it off and the real sweep (table uploaded again) takes over. `sweepd --platform ebaz --test-spectrum` starts in this mode. The command is `virtual` (`server/protocol.py`).
- **Device log**: what `sweepd` reports, plus the GUI's own notes (connecting, connection problems, and every warning that the status bar showed). Records come live from the daemon, and on connect the GUI also fetches what the daemon kept before, so the box is complete after a reconnect or a late start. Lines are coloured by level (red error, amber warning, grey debug). Controls: **Show** is the lowest level listed (Error, Warning, Info, Debug; the default is Info; changing it re-lists everything kept, up to 2000 lines), **Pause** stops adding lines but keeps them (they appear when unticked), **Clear**, **Save…** (all lines with the date, to `captures/` by default). While you are on another tab, the Advanced tab title and the status bar count unread warnings and errors, for example `Advanced (1 error, 2 warnings)`; the status-bar count jumps to the tab when clicked, and an error also shows in the status bar. A daemon restart shows as a marker line. Per-point and per-SPI-word detail (trace) never reaches the GUI: start `sweepd` with `-vv` and read it over ssh with `journalctl -u sweepd -f`. A `sweepd` without a log (older version) shows a note after a few tries.
- **Simulated hardware**: starts `python -m sadiy.server.sweepd --sim` as a separate process on this PC, bound to 127.0.0.1 on the ports above. Parameters: sweep period, input noise floor, simulated RBW, up to four test tones (frequency, level, on/off). They are applied when the simulator starts; stop and start it to change them. "Connect after start" connects automatically. The process output shows in the log box.
- **Analyzer**: RBW used for the display and the points rule (follows the simulated RBW when the simulator starts), frequency limits, peak threshold above the median, number of sweeps in Average mode, GUI poll interval.
- **Data**: save the trace as CSV (`freq_hz,level_dbm`), save a screenshot as PNG. Both default to `captures/`, which is git-ignored.

## Files

| File | Role |
|---|---|
| `ui/sa_gui.py` | Qt window (PyQtGraph display, controls, tabs) |
| `ui/sa_core.py` | axis, settings clamping, trace modes, peak search, markers, CSV: no Qt, unit-tested |
| `ui/settings_core.py` | saved settings: layout of the JSON, checking and clamping, the settings folder, named settings, the as-delivered file `config/default.json`: no Qt, unit-tested |
| `ui/log_core.py` | the Device log's state: numbered, duplicate-free records, gap and restart detection, unread counters, levels: no Qt, unit-tested |
| `ui/bench_tab.py` | the Pins tab: board drawing and controls, platform selector |
| `ui/synth_tab.py` | the Synth tab: presets, frequency and power, the readback (uses the Pins tab's bench session) |
| `ui/synth_core.py` | presets from sweepd's status, plan preview, readback texts: no Qt, unit-tested |
| `ui/bench_core.py` | bench session, the shapes of the adapter picture, confirm memory, input parsing, pattern preview, board layout and hit test (all take a `pinmap.PinMap`, default BBB): no Qt, unit-tested |
| `pinmap.py`, `pinmap_ebaz.py`, `platforms.py` | the pin maps (`pinmap.BBB`, `pinmap_ebaz.EBAZ`) and `platforms.get(name)`; the layout of the drawn board is part of the map |
| `ui/sweep_client.py` | ZeroMQ SUB (newest frame only, all log records, flags of the last frame) and REQ with short timeouts, `fetch_log` |
| `ui/sim_runner.py` | starts / stops `sweepd --sim`, writes the temporary TOML override, keeps the log |
| `tests/test_sa_gui_smoke.py`, `tests/test_bench_gui_smoke.py`, `tests/test_synth_gui_smoke.py`, `tests/test_platform_gui_smoke.py` | build the window offscreen, feed frames and flags, drive the Pins tab and the Device log, run the simulator end to end; skipped without PyQt5 / pyqtgraph |
| `tests/test_settings_core.py`, `tests/test_settings_gui.py` | the settings files and the Settings menu (offscreen, with a temporary folder) |
| `tests/test_log_core.py`, `tests/test_sweep_client_log.py` | log buffer logic; the client against real ZeroMQ sockets on localhost |

## Known limits

- The RBW is fixed by the IF filter (in the simulator, `[sim] rbw_hz`). The RBW box is only for the display and the points rule, there is no RBW command.
- With the detector module dead (2026-11-23) a sweep has no real signal source yet: the Virtual spectrum and the ramp self-test are the sources on the EBAZ4205 until the AD9226 is wired (`zynq-ebaz/docs/adc-module.md`).
- Reference level and dB/div do not change the attenuator: auto-ranging keeps the sweep peak at -15 dBm at the detector (`core/sweep.py`), same as before.
- A command with no answer blocks the window for up to 0.5 s (the REQ timeout). Sync after connecting uses 0.15 s tries.
- The low-IF image 21.4 MHz away shows up as a second copy of every signal (also in the simulator) unless **Image reject** is ticked: `sweepd` then sweeps twice with the LO above and below and keeps the lower reading, so a trace takes twice as long and the info line shows `IMG REJ`. Points below about 45 MHz can not be done that way and keep their image (flag `[image not suppressed]` at a marker; the daemon logs where suppression starts). Not verified on the real mixer.
- Peak search treats a rising plateau as a peak at its first point; harmless on real traces.
- The Device log keeps 2000 lines in the GUI and the daemon 500; older ones are gone. A fetch (on connect, after a gap) blocks the window for up to 0.15 s when the daemon is slow.
- Log lines of a simulator the GUI started also appear in the simulator's own process box under "Simulated hardware", because that box shows the child's stderr.
