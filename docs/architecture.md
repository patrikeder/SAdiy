# Architecture

## Process model

```
 sweepd (one process, real-time priority)         clients (any number, any host)
 +--------------------------------------+         +-------------------------+
 | SweepEngine                          |  PUB    | sa_gui / cli_client     |
 |   synth.tune -> settle -> adc.read   | ------> | plot, markers, hold     |
 | PE4302 (GPIO) ADF4351 (SPI) ADC      |  REP    |                         |
 +--------------------------------------+ <------ | set / run / stop        |
```

- The GPIO / SPI control and the ADC reads run in `sweepd`, a separate process from any UI. This is the "secondary thread" requirement done with a process, because Python's GIL would otherwise couple plotting to SPI timing.
- On the BBB the viewer runs on another machine (`--host <bbb-ip>`). On the RPi it can run locally on the monitor. Same code both ways.
- Frames are two ZeroMQ parts: a JSON header and float32 dBm values (`server/protocol.py`).
- Commands (REQ/REP, JSON): `set` (start_hz, stop_hz, points, atten_db, auto_atten, averages), `run`, `stop`, `status`, and the `bench_*` commands (below; full list in `server/protocol.py`). `set` is rejected when the range lies outside `[rf] rf_min_hz .. rf_max_hz`, because the LO plan would fail below the ADF4351 minimum. `status` returns the settings, the running state and the `limits` (rf_min_hz, rf_max_hz, points_max), which the GUI adopts on connect.
- The GUI (`ui/sa_gui.py`, see `gui.md`) is one such client. It can also start `sweepd --sim` as a child process for development on a PC.

## Layering

`hal` (pins, buses) <- `drivers` (PE4302, ADF4351, ADS1115, on-chip ADC) <- `core` (sweep, cal, plan) <- `server` <- `ui`.
`pinmap.py` sits beside them: plain data with no dependencies, read by `server`, `ui` and `tools/gen_diagrams.py`.
Only `hal` touches the OS. Everything above runs against fakes and the simulator on a PC.
Inside `ui`, everything that is not drawing lives in `sa_core.py` (no Qt, unit-tested); `sa_gui.py` is the thin Qt layer, `sweep_client.py` the ZeroMQ side and `sim_runner.py` the simulator launcher.

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
- **Bus pins as GPIO:** SPI and I2C pins change function with `config-pin`, and go back when a bus command needs them or the mode closes. Clocking SPI lines by hand can latch junk into the ADF4351, so an outputs-off R4 is sent as soon as they are back on SPI.
- **Patterns** are built by `patterns.from_spec` from a JSON spec, by the GUI for the preview and CSV and by the daemon for the run, so the preview is what runs. The daemon sends steps in 10 ms slices between command polls, so stop always gets through. It does not catch up when it falls behind: it reports the measured rate. The rate limits in `hal/base.py` (about 3000 sysfs writes/s, 1000 SPI words/s) are estimates, not measured on a BBB.

## Frequency plan

- IF 10.7 MHz, high-side injection: LO = RF + 10.7 MHz. RF range about 25 to 489 MHz (ADF4351 minimum 34.375 MHz via /64, AD831 LO maximum 500 MHz).
- Low IF means an image 21.4 MHz above each RF (it shows 21.4 MHz lower on the sweep axis). The simulator reproduces this.
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
| PE4302 on 6 GPIO lines (parallel V1..V6), make-before-break write order, safe default | the module has no serial interface. Stages turning on are written first so no step is less attenuating than min(old, new); the module's own pull-downs default to 0 dB; optional 2.2 kohm pull-ups give maximum attenuation before the SBC drives the lines |
| GUI as a client with its own simulator launcher | the same GUI runs on a PC against the simulator, on the RPi locally and on a PC against the BBB; sim parameters go through a temporary TOML override (`[sim]` section), so `sweepd` has no GUI-specific code |
| ADS1115 as the main ADC on every platform | same code path and same calibration whichever SBC is used. 16 bits, but at most 860 SPS, so sweep speed is limited to about 1 ms per point. BBB AIN0 stays wired on the adapter (through a 0.751 divider) as a cross-check, read from the bench mode |
| Bench mode inside `sweepd` | one owner of the hardware; exclusivity with sweeping without any locking |
| One pin map module (`pinmap.py`) | netlist, diagrams, daemon rules and the clickable board can not disagree |
| Python first, native later | only if the measured per-point time says so (`native/`) |
| Simulator in the repo | whole stack testable without the hardware |
