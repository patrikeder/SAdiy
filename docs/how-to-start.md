# How to start

Only the steps. Two programs: the server `sweepd` runs on the target (EBAZ4205 or BBB) and the GUI runs on the PC. Details: [gui.md](gui.md), [architecture.md](architecture.md). Bench mode on the EBAZ4205 has worked on the board (2026-11-16, user report: setting ADF4351 frequencies, setting the attenuation, reading ADC values; that was with the old attenuator wiring, and the PCF8574 that drives the PE4302 now has not run on a board). Sweeping has started on the board but nothing has been checked against real RF yet; where a step is untested on a board it says so.

## 0. Once on the PC

```bash
cd SAdiy
python3 -m venv .venv && . .venv/bin/activate      # installs software: ask first, see CLAUDE.md
pip install -e .[dev,ui]
```

## A. Try it with no hardware (PC only)

```bash
. .venv/bin/activate
python -m sadiy.ui.sa_gui --sim                    # starts a simulated server and connects to it
```

## B. EBAZ4205: server on the board, GUI on the PC

**1. Put the code and the bitstream on the board** (PC, from the checkout; user `petalinux`):

```bash
sh zynq-ebaz/sw/deploy/deploy_to_board.sh <ebaz-ip>          # BITSTREAM=<ebaz_sadiy.bit.bin> to choose the bitstream
```

It prints which bitstream it found (default: `zynq-ebaz/build/fpga/` of this checkout, else the RTL worktree next to it) and puts the day-to-day scripts into `~/sadiy`.

**The short way (on the board, from `~/sadiy`):**

```bash
./status.sh      # software build, PL state and map version, device nodes, running sweepd, network. Read-only
./fpga.sh        # load the bitstream if the PL has none or the wrong one (--force: load again)
./bench.sh       # bench mode: checks the PL, then sweepd --bench-only (Pins and Synth tabs; no sweeping)
./sweep.sh       # sweeping with the PL engine (map 1.1 or newer; no bench mode in this run)
./selftest.sh    # pass/fail test of the PL sweep path with the engine's test ramp (no RF; ./sweep.sh --test-ramp shows it in the GUI)
./sim.sh         # simulated chain, no hardware, no root
./stop.sh        # stop a running sweepd (lines go back to safe)
```
and on the PC `sh zynq-ebaz/sw/pc/gui.sh <ebaz-ip>` (or `--sim`). `bench.sh` and `sweep.sh` run `fpga.sh` first and stop with a message when the PL is not ready; `fpga.sh` restarts the network interface for a few seconds when it loads (an ssh session may stall). The steps below are what the scripts do. `~/sadiy/README.txt` on the board says what is where. Typing `python3 -m sadiy.server.sweepd` by hand needs `. ~/sadiy/env.sh` first: without PYTHONPATH, from `~` the folder `~/sadiy` is found as an empty package and the error is `No module named 'sadiy.server'`. `./status.sh` lists every copy of the software under `~` with its build (old bring-up packages carry their own, not updated by the deploy).

**2. Start the server** (on the board, over ssh):

```bash
ssh petalinux@<ebaz-ip>
. ~/sadiy/env.sh                                   # sets PYTHONPATH; without it: ModuleNotFoundError: No module named 'sadiy'
sudo env PYTHONPATH=$PYTHONPATH python3 -m sadiy.server.sweepd --platform ebaz      # the PL sweep engine, needs root for /dev/mem
```

- Wiring tests (Pins tab, raw ADF4351 / PE4302 access, patterns; no sweeping): `--platform ebaz --bench-only` instead; Linux owns the pins then and hands them back from the PL engine if a killed server left them. Sweeping and bench mode are separate runs.
- Without the adapter and detector: `--sim --platform ebaz` instead (simulated chain, no root needed).
- Stop with Ctrl-C. Messages: `-v` for more, `-q` for less.
- Which build runs: `sweepd` logs `build: sadiy 0.1.0, commit 9b446a2 (linux, ...)` right after its start line, `status` carries it, the GUI writes it into the Device log when it connects (and warns when GUI and server are different commits), and `bringup.py`, `pl_bringup.py` and `cli_client` print it when they start. `deploy_to_board.sh`, `make_bbb_package.py` and `make_bringup_pkg.sh` record it in a `BUILD_INFO` file next to the copy; "build unknown" means a copy without it. A bring-up package made earlier (`~/sadiy/bringup-pkg`) is its own copy of the code and is not updated by `deploy_to_board.sh`: compare its line with the checkout's (`python -m sadiy.buildinfo`).
- Bench mode (Pins tab) is not available while the server sweeps ("this sweepd has no bench backend"): the PL engine owns the pins. Restart with `--bench-only` for wiring tests; checklist for the attenuator and lock: `zynq-ebaz/docs/bench-test-adc-att-lock.md`.
- The server listens on tcp 5556 (sweeps) and 5557 (commands).
- Bitstream: the `BOOT.BIN` rebuilt on 2026-11-15 14:53 holds the engine of 2026-11-15 00:03 = **register map 1.2** (sweep path, the ADC reader of that time, CE and I2C pin mux, IF path). An SD card written before that has map 1.0 (engine of 2026-11-14 17:09): `--bench-only` and detector `ps` / `test` still work with it, the default PL detector stops with "needs map >= 1.1". Update the card: copy `BOOT.BIN` and `image.ub` (see `zynq-ebaz/sw/deploy/README.md`), or load the newer bitstream for one run with `sadiy_pl_load.sh` from session R's bring-up package. `--bench-only` worked on the board (2026-11-16); the sweep path has started and swept (3.47 s per sweep, 401 points, 4 averages) but its results are not checked yet. **The software now needs register map 2.x** (PE4302 through the PCF8574, 2026-11-25): update the card or load the new bitstream; an older one is refused.

**3. Start the GUI** (PC):

```bash
. .venv/bin/activate
python -m sadiy.ui.sa_gui --platform ebaz --host <ebaz-ip> --connect      # or: sh zynq-ebaz/sw/pc/gui.sh <ebaz-ip>
```

Press **Run** on the Spectrum tab (sweeping server), or open the **Pins** tab and **Enter bench mode** (`--bench-only` server). Without a GUI: `python -m sadiy.ui.cli_client --host <ebaz-ip> --count 5`.

## C. BeagleBone Black: server on the board, GUI on the PC

Sweeping on the BBB is not written yet, so the server runs in bench mode (Pins tab) only.

**1. Server** (on the BBB; installed per [../deploy/bbb-setup.md](../deploy/bbb-setup.md)):

```bash
cd /opt/sadiy && sudo PYTHONPATH=src python3 -m sadiy.server.sweepd --bench-only --config /etc/sadiy/local.toml
```

Or as a service: `sudo systemctl start sweepd` (log: `journalctl -u sweepd -f`).

**2. GUI** (PC):

```bash
. .venv/bin/activate
python -m sadiy.ui.sa_gui --platform bbb --host <bbb-ip> --connect
```

Then the **Pins** tab, **Enter bench mode**.

## If it does not connect

- GUI window: Advanced tab, Connection: host and ports (5556, 5557) must match the server's.
- `ModuleNotFoundError: No module named 'sadiy'` on a board: run `. ~/sadiy/env.sh` first, or use `python3 tools/bringup.py ...` from `~/sadiy` (it finds `src` itself).
- Server and GUI must agree on the board: `--platform ebaz` on both, or leave the GUI's selector on automatic (omit `--platform`).
- Port already in use: another `sweepd` is running (`pgrep -af sweepd`).
