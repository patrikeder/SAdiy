# SAdiy: DIY swept spectrum analyzer

A swept low-IF spectrum analyzer built from ready-made RF modules and controlled by a BeagleBone Black (BBB). The software runs on a PC today against a simulated RF chain. It has not run on the real hardware yet: see [Status](#status).

The code is Python. C++ or Rust comes in only if a measured time per point demands it (`native/`).

## Signal chain

Planned:

```
RF in -> DC block/ESD -> PE4302 -> 500 MHz LPF -> 30 dB amp -> AD831 mixer -> 10.7 MHz IF filter -> IF amp -> log detector -> ADS1115 -> BBB
                                                                  ^
ADF4351 (LO = RF + 10.7 MHz) -> LPF + pad -----------------------+
```

Built so far: PE4302, amp, AD831, detector and ADF4351. The missing stages are listed in priority order in [hw/todo-parts.md](hw/todo-parts.md).

- **Range:** 30 to 480 MHz by default (`config/default.toml`). The AD831 LO limit puts the ceiling at about 489 MHz.
- **Image:** the low IF puts an image 21.4 MHz above each RF, so every signal also shows a copy 21.4 MHz lower on the sweep axis.
- **ADC:** an ADS1115 on I2C reads the detector. The BBB on-chip AIN0 stays wired as an optional cross-check.

## Quick start (PC, no hardware)

```bash
python3 -m venv .venv && . .venv/bin/activate
pip install -e .[dev,ui]      # ui adds PyQtGraph and PyQt5, only needed for the GUI
pytest
```

Run the spectrum analyzer GUI. It starts its own simulated hardware, and its Pins tab drives a fake board:

```bash
python -m sadiy.ui.sa_gui --sim
```

Or run the daemon and a terminal client separately:

```bash
python -m sadiy.server.sweepd --sim &      # publishes on tcp 5556, takes commands on tcp 5557
python -m sadiy.ui.cli_client --count 5    # prints the peak of each sweep
```

Bring-up helpers that need no hardware:

```bash
python tools/bringup.py pe4302-pattern --db 16 --from-db 15.5   # V1..V6 write order, for a logic analyzer
python tools/bringup.py pll --mhz 110.7                         # divider, INT, FRAC, MOD
```

Run from a project checkout: the config is read from `config/default.toml` next to `src/`.

## On the BBB

Setup is in [deploy/bbb-setup.md](deploy/bbb-setup.md). Sweeping on real hardware is not written yet, so for now the daemon runs in bench mode only:

```bash
cd /opt/sadiy && sudo PYTHONPATH=src python3 -m sadiy.server.sweepd --bench-only --config /etc/sadiy/local.toml   # on the BBB
python -m sadiy.ui.sa_gui --host <bbb-ip> --connect   # on the PC
```

The GUI's **Pins** tab then gives wiring tests over the network:

- a clickable drawing of P8 and P9 with the boards, and live pin levels
- raw access to the ADF4351, PE4302 and both ADCs
- check patterns with a preview and CSV export, to compare with a logic analyzer capture

The daemon enforces the safety rules: the attenuator starts at 31.5 dB, RF outputs stay off until the PLL is locked, and all lines return to a safe state if the client disappears. See [docs/gui.md](docs/gui.md).

## How it fits together

```
 sweepd (one process, on the BBB)              clients (any number, any host)
 +----------------------------------+          +------------------------+
 | sweep engine or bench mode       |   PUB    | sa_gui / cli_client    |
 | PE4302 (GPIO) ADF4351 (SPI)      | -------> | plot, markers, Pins    |
 | ADS1115 (I2C) AIN0 (IIO)         |   REP    |                        |
 +----------------------------------+ <------- | commands (JSON)        |
```

`sweepd` is the only process that touches the hardware. Clients talk to it over ZeroMQ: frames on port 5556, JSON commands on port 5557. Code layers as `hal` -> `drivers` -> `core` -> `server` -> `ui`, and only `hal` touches the OS, so everything above it runs on a PC against fakes and the simulator. Details and the design decisions are in [docs/architecture.md](docs/architecture.md).

## Repository layout

| Path | What |
|---|---|
| `src/sadiy/pinmap.py` | the BBB pin map: nets, kernel GPIO numbers, what each pin may do. Read by the diagram generator, the daemon and the GUI |
| `src/sadiy/hal/` | SPI, GPIO, I2C and ADC abstraction: Linux backends and recording fakes |
| `src/sadiy/drivers/` | PE4302, ADF4351, ADS1115 and on-chip ADC drivers |
| `src/sadiy/core/` | frequency plan, detector model, calibration, sweep engine (no hardware access) |
| `src/sadiy/server/` | `sweepd` daemon, wire protocol, bench mode |
| `src/sadiy/ui/` | terminal client and GUI (`sa_gui.py`, `bench_tab.py`); logic without Qt is in `sa_core.py` and `bench_core.py`. `qt_client.py` is an old skeleton |
| `src/sadiy/sim.py` | simulated RF chain |
| `src/sadiy/patterns.py` | pin patterns and SPI frames, for logic analyzer comparison |
| `config/` | TOML configuration; values marked VERIFY need checking on the real boards |
| `hw/` | wiring, diagrams, netlist, per-board notes, test points, missing parts, adapter board (KiCad) |
| `docs/` | architecture, bring-up plan, GUI manual |
| `deploy/` | BBB setup notes, systemd units, pin mode script, example local config |
| `sna/` | second project: a scalar network analyzer reusing the same chain |
| `tools/` | bring-up and calibration helpers, `gen_diagrams.py` |
| `tests/` | pytest suite, runs on a PC; GUI tests run offscreen and are skipped without the GUI packages |
| `native/` | placeholder for C++ or Rust |

`hw/netlist.md` and `hw/diagrams/` are generated. To change them, edit `src/sadiy/pinmap.py` or `tools/gen_diagrams.py` and run `python tools/gen_diagrams.py`.

## Hardware documentation

| Document | What |
|---|---|
| [hw/wiring-bbb.md](hw/wiring-bbb.md) | BBB wiring, wiring order, power-on checks |
| [hw/netlist.md](hw/netlist.md) | every signal, strap and supply pin |
| [hw/boards/sbc-adapter/README.md](hw/boards/sbc-adapter/README.md) | adapter board that carries the modules on the BBB |
| [hw/as-built.md](hw/as-built.md) | what is really on the bench |
| [docs/bringup.md](docs/bringup.md) | staged bring-up plan with pass criteria |

The adapter board is BBB only: its Raspberry Pi connector was removed. The Raspberry Pi wiring notes and software paths are still in the repo but are no longer developed.

## Status

| Part | State |
|---|---|
| Frequency plan and PLL math, detector model, calibration, auto-ranging | done, tested |
| Sweep engine, `sweepd`, protocol, terminal client, simulator | done, tested against the simulator |
| Spectrum analyzer GUI | done, smoke-tested offscreen against the simulator; not yet used with real hardware or on a real display |
| PE4302 driver | done, tested with fakes; weights and polarity not yet confirmed on the module (`pe4302-walk`) |
| ADS1115 driver | done, tested against a register model only; sweeps do not use it yet |
| Bench mode (Pins tab) | done, **tested on the fake backend only**; the Linux backend has never run on a BBB |
| ADF4351 register packing | R4 done but unchecked against the datasheet; **R0..R3 and R5 not written** |
| Sweeping on real hardware (`build_hw_engine`) | **not written**: waits for the ADF4351 registers |
| GPIO backend | sysfs; moves to libgpiod once the image is fixed |

Unverified on a real BBB: the pin map, pin multiplexing and `config-pin` modes, and the SPI and I2C device numbers.
