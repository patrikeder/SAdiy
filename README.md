# SAdiy: DIY swept spectrum analyzer

Swept low-IF receiver built from existing modules, controlled by a BeagleBone Black (preferred) or a Raspberry Pi 3/4/400.

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
python tools/bringup.py pe4302-pattern --db 16 --from-db 15.5   # V1..V6 write order for the logic analyzer
python tools/bringup.py pll --mhz 110.7
```

Run from a project checkout: the config is read from `config/default.toml` next to `src/`.

## Layout

| Path | What |
|---|---|
| `src/sadiy/hal/` | SPI / GPIO abstraction: Linux backends and recording fakes |
| `src/sadiy/drivers/` | PE4302, ADF4351, ADC drivers |
| `src/sadiy/core/` | frequency plan, detector model, calibration, sweep engine (no hardware access) |
| `src/sadiy/server/` | `sweepd` acquisition daemon, wire protocol |
| `src/sadiy/ui/` | clients (terminal, PyQtGraph); they never touch hardware |
| `src/sadiy/sim.py` | simulated RF chain for development |
| `src/sadiy/patterns.py` | pattern maker: attenuator line sequences and ADF4351 SPI frames, for logic analyzer comparison |
| `config/` | TOML configuration; values marked VERIFY need checking on the real boards |
| `hw/` | wiring (BBB and RPi), diagrams (SVG + PNG), board hierarchy, netlist, per-board notes, test points, missing parts |
| `docs/` | architecture and bring-up plan |
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
| Hardware wiring in `sweepd` (`build_hw_engine`) | **not written**: waits for the ADF4351 registers and the pin map |
| ADS1115 driver | stub |
| PyQtGraph client | untested skeleton |
| GPIO backend | sysfs; switch to libgpiod once the image is fixed |
