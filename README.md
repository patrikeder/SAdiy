# SAdiy: DIY swept spectrum analyzer

Swept low-IF receiver built from existing modules, controlled by a BeagleBone Black (preferred) or a Raspberry Pi 3/4/400. The detector is read by an ADS1115 on I2C on both.

```
RF in -> DC block/ESD -> PE4302 -> 500 MHz LPF -> 30 dB amp -> AD831 mixer -> 10.7 MHz IF filter -> IF amp -> log detector -> ADC -> SBC
                                                                  ^
ADF4351 (LO = RF + 10.7 MHz) -> LPF + pad -----------------------+
```

Stages that are not built yet are listed in `hw/todo-parts.md`. Range with these parts is about 25 to 489 MHz (AD831 limit). The full design review is in the Claude project "DIY Spectrum analyzer".

## Quick start (PC, no hardware)

```
cd SAdiy
python3 -m venv .venv && . .venv/bin/activate
pip install -e .[dev]
pytest
python -m sadiy.server.sweepd --sim &        # simulated RF chain, publishes on tcp 5556 / 5557
python -m sadiy.ui.cli_client --count 5      # prints the peak of each sweep
pip install -e .[ui]                         # PyQtGraph + PyQt5, only for the GUI
python -m sadiy.ui.sa_gui --sim              # spectrum analyzer GUI, starts its own simulated hardware; the Pins tab drives a fake board
python tools/bringup.py pe4302-pattern --db 16 --from-db 15.5   # V1..V6 write order for the logic analyzer
python tools/bringup.py pll --mhz 110.7
```

Run from a project checkout: the config is read from `config/default.toml` next to `src/`.

## Layout

| Path | What |
|---|---|
| `src/sadiy/pinmap.py` | the BBB pin map: nets, kernel GPIO numbers, what each pin may do. Read by the netlist and diagram generator, the daemon and the GUI |
| `src/sadiy/hal/` | SPI / GPIO / I2C / ADC abstraction: Linux backends and recording fakes |
| `src/sadiy/drivers/` | PE4302, ADF4351, ADS1115 and on-chip ADC drivers |
| `src/sadiy/core/` | frequency plan, detector model, calibration, sweep engine (no hardware access) |
| `src/sadiy/server/` | `sweepd` acquisition daemon, wire protocol, bench mode (`bench.py`) |
| `src/sadiy/ui/` | clients (terminal, spectrum analyzer GUI `sa_gui.py`, old PyQtGraph skeleton `qt_client.py`); they never touch hardware. `sa_core.py` holds the GUI logic without Qt (tested). `bench_tab.py` and `bench_core.py` are the Pins tab |
| `src/sadiy/sim.py` | simulated RF chain for development |
| `src/sadiy/patterns.py` | pattern maker: attenuator line sequences and ADF4351 SPI frames, for logic analyzer comparison |
| `config/` | TOML configuration; values marked VERIFY need checking on the real boards |
| `hw/` | wiring (BBB and RPi), diagrams (SVG + PNG), board hierarchy, netlist, per-board notes, test points, missing parts |
| `docs/` | architecture, bring-up plan, GUI manual (`gui.md`) |
| `deploy/` | BBB setup notes, systemd unit |
| `native/` | placeholder for C++ / Rust, only if profiling demands it |
| `tools/` | bring-up and calibration helpers; `gen_diagrams.py` regenerates `hw/diagrams/` and `hw/netlist.md` |
| `tests/` | pytest suite (runs on a PC) |

## Status

| Part | State |
|---|---|
| PE4302 driver (parallel V1..V6, glitch-safe write order, safe default) | done, tested with recording fakes; weights and polarity of V1..V6 still to be verified on the module (`pe4302-walk`) |
| Pattern maker (`patterns.py`): attenuator write sequences, ADF4351 SPI frames | done, tested |
| PLL math (divider, INT, FRAC, MOD) | done, tested |
| Detector model, calibration table, auto-ranging | done, tested |
| Sweep engine, `sweepd`, protocol, terminal client | done, tested against the simulator |
| Simulator | done (tone, image, RBW filter, detector, noise) |
| ADF4351 register packing | **not written**: needs the datasheet register maps (see `drivers/adf4351.py`) |
| Hardware wiring in `sweepd` (`build_hw_engine`) | **not written**: waits for the ADF4351 registers and the pin map. `sweepd --bench-only` runs the bench mode without it |
| ADS1115 driver, the main ADC on every platform | done, tested against a register model only; not yet on a real ADS1115. Not yet used by sweeps (needs `build_hw_engine`) |
| Bench mode: Pins tab, raw board access, check patterns (`docs/gui.md`) | done, **tested on the fake backend only**. The Linux backend has never run on a BBB. Pin map, pin multiplexing, PE4302 weights and polarity and the I2C / SPI device numbers are all unverified |
| Spectrum analyzer GUI (`sa_gui.py`, see `docs/gui.md`) | done: classic display, markers, trace modes, Pins tab, Advanced tab with simulated hardware; smoke-tested offscreen against the simulator, not yet used with real hardware or on a real display |
| `qt_client.py` | old untested skeleton, superseded by `sa_gui.py` |
| GPIO backend | sysfs; switch to libgpiod once the image is fixed |
