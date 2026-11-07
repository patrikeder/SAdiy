# Architecture

## Process model

```
 sweepd (one process, real-time priority)          clients (any number, any host)
 +----------------------------------------+        +----------------------------+
 | SweepEngine, per point:                |  PUB   | sa_gui / cli_client        |
 |   tune -> settle -> lock detect ->     | -----> |  "sweep": dBm + flags      |
 |   n ADC reads -> median -> cal -> flags|        |  "log": errors, warnings   |
 | PE4302 (GPIO) ADF4351 (SPI) ADC (I2C)  |  REP   | plot, markers, hold,       |
 | log ring (last 500 records)            | <----- | Device log (Advanced tab)  |
 +----------------------------------------+        | set / run / stop / log     |
        |                                           +----------------------------+
        +--> stderr / journald: -v, -vv (trace) for ssh
```

- The GPIO / SPI control and the ADC reads run in `sweepd`, a separate process from any UI. This is the "secondary thread" requirement done with a process, because Python's GIL would otherwise couple plotting to SPI timing.
- On the BBB the viewer runs on another machine (`--host <bbb-ip>`). On the RPi it can run locally on the monitor. Same code both ways.
- Frames are ZeroMQ parts on topic `sweep`: a JSON header, float32 dBm values and one flag byte per point (`server/protocol.py`). The flag part is optional and additive, so older readers ignore it and `VERSION` stays 1.
- Log records go out on the same PUB socket under topic `log`, one JSON part each (see Logging below).
- Commands (REQ/REP, JSON): `set` (start_hz, stop_hz, points, atten_db, auto_atten, averages), `run`, `stop`, `status`, `log` (the records sweepd kept, after a given number), and the `bench_*` commands (below; full list in `server/protocol.py`). `set` is rejected when the range lies outside `[rf] rf_min_hz .. rf_max_hz`, because the LO plan would fail below the ADF4351 minimum. `status` returns the settings, the running state, the `limits` (rf_min_hz, rf_max_hz, points_max), which the GUI adopts on connect, `last_error`, `log_seq` and `last_sweep` (the counts of the last sweep: unlocked, overload, at floor, outlier points).
- The GUI (`ui/sa_gui.py`, see `gui.md`) is one such client. It can also start `sweepd --sim` as a child process for development on a PC.

## Layering

`hal` (pins, buses) <- `drivers` (PE4302, ADF4351, ADS1115, on-chip ADC) <- `core` (sweep, cal, plan) <- `server` <- `ui`.
`pinmap.py` sits beside them: plain data with no dependencies, read by `server`, `ui` and `tools/gen_diagrams.py`. So does `logs.py` (levels, ring buffer, standard library only), used by `server` and `ui`.
Only `hal` touches the OS. Everything above runs against fakes and the simulator on a PC.
Inside `ui`, everything that is not drawing lives in `sa_core.py` and `log_core.py` (no Qt, unit-tested); `sa_gui.py` is the thin Qt layer, `sweep_client.py` the ZeroMQ side and `sim_runner.py` the simulator launcher.

## Per-point handling (`core/sweep.py`)

What only the BBB side can do, and what the GUI therefore never has to guess. Per point, after `tune` and the settle time:

1. **Lock detect.** `SYN_LD` is read (a short wait, then one more tune, then give up). A point that never locks gets the flag *unlocked* and stays out of auto-ranging. Without a lock source the sweep is not gated, and `sweepd` says so once.
2. **Robust read.** The ADC drivers give the n samples (`read_samples`), and the point is their **median** (`[sweep] combine`: median, trimmed or mean; with fewer than 3 samples all are the mean). One I2C glitch or noisy conversion no longer moves the point. A sample more than `outlier_db` from the result flags the point *outlier rejected*.
3. **Rails.** A point at or above `[detector] max_dbm` is flagged *overload* (not trusted), at or below `floor_dbm` *at floor* (only an upper bound).

4. **Image rejection (optional, `image_reject`).** The low IF puts an image 21.4 MHz (2 IF) below every signal. With the option on, `run_rejecting()` sweeps twice, with the LO above and below the signal, and keeps the lower reading per point. A tone appears at the same place in both sweeps, its image moves from 2 IF below (high-side LO) to 2 IF above (low-side LO), so the image drops out; two tones exactly 2 IF apart are kept too. It takes twice as long. Points whose opposite LO is out of range (low-side LO below the ADF4351 minimum of 34.375 MHz, so RF below about 45.1 MHz; high-side LO above the AD831 limit of 500 MHz) keep their image and get the flag *image not suppressed*. If one side was unlocked, the other side's reading is used and flagged the same way. The simulator models both sides, so it shows the effect; the real mixer's behaviour with a low-side LO is **not verified**.

`SweepEngine.run()` returns the dBm values; `last_flags` and `last_stats` hold the flags and counts of that sweep. `sweepd` sends the flags with the frame, reports a lasting fault once and then at most every 10 s with the number of sweeps in between (and again when it is gone), and puts the counts in `status`. If a sweep raises (SPI, I2C or GPIO error), `sweepd` logs it, puts the attenuator to maximum and the RF outputs off, stops sweeping and stays up, so the GUI can read why and bench mode still works.

What stays in the GUI: trace modes, markers, peak search, smoothing, dB/div. They are stateful and reversible, and the GUI always gets the cleanest calibrated single sweep. The GUI marks the flagged points on the trace and names the flags at a marker. Software cannot replace the missing IF filter: with an analog detector after the mixer there is no digital IF, so the RBW can not be narrowed afterwards. Only post-detection work (this section, calibration, averaging sweeps) is possible.

## Logging

- **Levels:** error, warning, info, debug, trace. Trace (every point, every SPI word) is for ssh only and never enters the ring or the network.
- **On the BBB:** `python -m sadiy.server.sweepd -v` (debug), `-vv` (trace), `-q` (warning), or `--log-level`, or `[log] level` in the config; the default is info. It goes to stderr, which systemd sends to the journal: `journalctl -u sweepd -f` over ssh is the low-level channel.
- **Ring:** the last `[log] ring_lines` records (500), numbered, kept in the daemon; routine lines are dropped before warnings and errors. Identical records within `dedup_s` fold into one followed by "repeated N more times".
- **To clients:** every record from debug up is published live on topic `log`. The `log` command returns what the daemon kept after a sequence number, so a client fills in what it missed (on connect, or after a gap in the numbers). `boot` identifies one run of the daemon: after a restart the numbers start again and the GUI shows a marker line.
- **What gets logged:** start-up and mode, settings changes, run and stop, refused commands, sweep summaries and faults (see above), a failed sweep with its error, bench open and close, lease expiry, RF output changes, pattern runs, and every hardware error with its traceback (on stderr; the ring has the one-line form). Nothing is logged per point above trace, so logging cannot slow the sweep.
- **GUI:** the Device log in the Advanced tab (`gui.md`), with its own level box, and a count of unread warnings and errors on the tab and in the status bar. Terminal clients: `python -m sadiy.ui.cli_client --log-level warning`.

## Bench mode

Direct pin control for wiring tests on the BBB (`server/bench.py`, GUI side in `gui.md`).

- **Where it runs:** inside `sweepd`, not in a separate daemon. `sweepd` must stay the only process that touches the hardware, and one process makes exclusivity with sweeping a plain check instead of a lock between daemons. `bench_*` commands are refused while a sweep runs and `run` is refused while bench mode is open. `sweepd --bench-only` runs it on the BBB before `build_hw_engine` exists; `--sim` gives it the fake backend.
- **Rules live in the daemon, not the GUI**, so every client gets them. What a pin may do comes from `pinmap.py`:

| Pins | Access |
|---|---|
| Wired to a board input: ATT_V1..V6, SYN_CLK / DATA / LE, SYN_CE, I2C_SCL / SDA | drive after `confirm: true`; without it the reply has `needs_confirm` |
| SYN_LD, AIN0..6 | input-only |
| Other free GPIO | needs `expert: true` |
| Power, ground, eMMC, HDMI, reset, GNDA_ADC, VDD_ADC | display-only |

- **RF outputs:** a raw R4 that enables an output is refused. Outputs turn on only through `bench_rf`, after an R0 was sent in the session and LD reads high. While an output is on, raw SPI words other than an R4 that turns it off are refused, and so is using the SPI pins as GPIO.
- **Safe state:** PE4302 at maximum attenuation, outputs off, every other line an input or back on its bus. It is restored on `bench_close`, on any hardware error, on daemon exit and when the client's lease runs out (no bench command for `bench.lease_s`, 5 s by default), which covers a crashed GUI or a lost network. A pattern also returns its lines to safe when it ends.
- **Bus pins as GPIO:** where the image has `config-pin` (the Trixie image does not; the request is then refused), SPI and I2C pins change function with it, and go back when a bus command needs them or the mode closes. Clocking SPI lines by hand can latch junk into the ADF4351, so an outputs-off R4 is sent as soon as they are back on SPI.
- **Patterns** are built by `patterns.from_spec` from a JSON spec, by the GUI for the preview and CSV and by the daemon for the run, so the preview is what runs. The daemon sends steps in 10 ms slices between command polls, so stop always gets through. It does not catch up when it falls behind: it reports the measured rate. The rate limits in `hal/base.py` (about 3000 sysfs writes/s, 1000 SPI words/s) are estimates, not measured on a BBB.

## Frequency plan

- IF 10.7 MHz, high-side injection: LO = RF + 10.7 MHz. RF range about 25 to 489 MHz (ADF4351 minimum 34.375 MHz via /64, AD831 LO maximum 500 MHz).
- Low IF means an image 21.4 MHz above each RF (it shows 21.4 MHz lower on the sweep axis). The simulator reproduces this. The optional image rejection (two sweeps, see "Per-point handling") removes it above about 45 MHz.
- The ADF4351 divider is always the lowest that keeps the VCO at or above 2200 MHz, so the VCO stays in 2200 to 4400 MHz. FRAC / MOD come from the best rational approximation with MOD <= 4095.

## Points versus RBW

The sweep samples the response of the IF filter, so the step must be no larger than about RBW / 2 or narrow signals read low. Example seen in the simulator: 401 points over 30 to 480 MHz (1.1 MHz step) with a 230 kHz RBW read a -30 dBm tone at -41.5 dBm. Rule: points >= 2 * span / RBW. A full 450 MHz span at 230 kHz RBW needs about 3900 points, which is the practical limit of `sweepd` (4001). Narrower spans are cheap.

## Level plan (amp numbers are seller claims, measure them)

- Net gain input to detector at 0 dB attenuation about 22 dB (amp 31, PE4302 1.5, IF filter 6, LPF about 1.5). Detector window -58 to -1 dBm maps to about -80 to -23 dBm at the input.
- The amp compresses at about -19.5 dBm at the input with 0 dB attenuation. Auto-ranging aims the sweep peak at -15 dBm at the detector (`core/sweep.py: next_atten_db`). Check that this keeps the amp and the AD831 below compression, and lower the target if not.
- Thermal floor in a 230 kHz RBW is about -117 dBm with the claimed amp noise figure. The detector floor (about -80 dBm) limits sensitivity until the IF gain stage is added.

## Decisions

| Decision | Why |
|---|---|
| Process, not thread, for acquisition | GIL; also gives remote viewing on the BBB for free |
| ZeroMQ PUB/SUB + REQ/REP | simple, multi-client, works across hosts |
| Precompute all sweep points and PLL words | keeps the inner loop to tune, settle, read |
| Median of the reads, lock gating and per-point flags on the BBB | only the BBB sees lock detect and the raw samples; the GUI keeps the reversible, stateful processing |
| Image rejection as two sweeps, lower reading kept, off by default | the ghost can not be told from a signal in one sweep; the cost is twice the sweep time and it needs a low-side LO, so it is a switch |
| Flags as an optional fourth frame part, not a new protocol version | older GUIs and the terminal client keep working |
| Log as a second PUB topic plus a `log` command, with a numbered ring | live and cheap, and a late or lossy client can still fill in what it missed |
| Per-sweep and per-fault log lines throttled, per-point lines only at trace | a fault that recurs on every point must not flood the ring, the network or the sweep time |
| No PRU for now | see "Time per point and the PRUs" below |
| PE4302 on 6 GPIO lines (parallel V1..V6), make-before-break write order, safe default | the module has no serial interface. Stages turning on are written first so no step is less attenuating than min(old, new); the module's own pull-downs default to 0 dB; optional 2.2 kohm pull-ups give maximum attenuation before the SBC drives the lines |
| GUI as a client with its own simulator launcher | the same GUI runs on a PC against the simulator, on the RPi locally and on a PC against the BBB; sim parameters go through a temporary TOML override (`[sim]` section), so `sweepd` has no GUI-specific code |
| ADS1115 as the main ADC on every platform | same code path and same calibration whichever SBC is used. 16 bits, but at most 860 SPS (1.2 ms per conversion, plus the I2C transfers, see below). BBB AIN0 stays wired on the adapter (through a 0.751 divider) as a cross-check, read from the bench mode |
| Bench mode inside `sweepd` | one owner of the hardware; exclusivity with sweeping without any locking |
| One pin map module (`pinmap.py`) | netlist, diagrams, daemon rules and the clickable board can not disagree |
| Python first, native later | only if the measured per-point time says so (`native/`) |
| Simulator in the repo | whole stack testable without the hardware |

## Time per point and the PRUs

Estimates from the code and `config/default.toml`, **not measured on a BBB**; measure them once `build_hw_engine` runs (the per-point split: tune, settle, ADC, CPU idle).

- The ADC path dominates. An ADS1115 read is the conversion (1.2 ms at 860 SPS, 7.8 ms at the default 128 SPS) plus about five I2C transfers, roughly 1.4 ms at 100 kHz (the bus clock of I2C2 is unverified). With the defaults (128 SPS, 4 averages) that is about 40 ms per point, 17 s for 401 points. At 860 SPS and one read it is about 3 ms per point.
- One ADS1115 LSB is about 0.005 dB at 24.5 mV/dB, so averaging several reads per point probably buys little. Check with the standard deviation of 100 reads at a fixed frequency; repeated sweeps (the GUI's Average mode) are cheaper than reads per point.
- The floor under any ADC is PLL lock plus the detector's RC (1 kohm, 100 nF: about 0.1 ms, so about 0.6 ms to settle to 0.1 dB after a 40 dB step), so about 1 ms per point.
- The CPU is idle most of the time in this loop and the numpy work per sweep is below a millisecond, so neither the filtering above nor the frame size (16 kB for 4001 points) loads the BBB.
- **PRUs.** They would remove syscall overhead and jitter (about 0.3 to 0.5 ms per point), only worth it once the ADC is fast. They have no SPI, I2C or ADC peripheral, no FPU and 8 kB of program memory. The ADF4351 SPI (P9.17, 18, 22) and the ADS1115 I2C (P9.19, 20) are not PRU pins, and the adapter board is made, so a PRU could only bit-bang them as GPIO. The ADS1115 has no ready line wired. So: no PRU. The order of measures is a faster ADS1115 setting (860 SPS, fewer reads), then the on-chip ADC through the IIO buffer (a change to the cross-platform decision above), then the `native/` extension, and a PRU sweep sequencer only after a board respin with SPI on PRU pins and a fast ADC. Zero-span (time-domain) mode would be the other use; the IIO buffer covers it without a PRU. The PRU pin names for P9 are from memory: verify before a respin.
