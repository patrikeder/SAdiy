# Bench test: PE4302 via PCF8574, ADF4351 lock (EBAZ4205, Linux owns the pins)

Goal: check the attenuator and whether the LO locks at the frequencies set in the GUI. (The file name still says "adc": the ADS1115 and its test step were removed on 2026-11-25.) Nothing here has run on the board with the PCF8574 yet; every "expect" below is from the datasheets and the code, not a measurement. Mode: `./bench.sh` (= `sweepd --platform ebaz --bench-only`) (PS path: `/dev/spidev0.0`, `/dev/i2c-0`, EMIO GPIO; the sweep engine is not used). The software needs a bitstream of register map 2.x.

## Safety

- ADF4351 board: 5 V from its DC jack only, never the `3V3` header pin. `CE` and `PDR` high. Terminate the unused output (AOUT-) with 50 ohm.
- All lines start safe: PE4302 at 31.5 dB, ADF4351 RF outputs off. The main output turns on only after lock and a confirm.
- RF into the PE4302 input: at most -20 dBm (start at -40 dBm). The LO output is at most about 5 dBm: do not connect it to the RF input.
- Input power is never raised while the attenuator is below 31.5 dB until the weights are confirmed (step 2).

## 0. Before

On the PC, from the main checkout (must show a clean `git status`):

```
sh zynq-ebaz/sw/deploy/deploy_to_board.sh <ebaz-ip>
```

On the board (`ssh petalinux@<ebaz-ip>`, then `cd ~/sadiy`):

```
./status.sh          # PL state operating, register map equals the software's, pins owned by Linux; /dev/spidev0.0 and /dev/i2c-0 ok
./fpga.sh            # if the PL has no bitstream or the wrong one: loads fpga/ebaz_sadiy.bit.bin
. ~/sadiy/env.sh
python3 tools/bringup.py --platform ebaz gpio-map                    # EMIO numbers and Linux line numbers
python3 tools/bringup.py --platform ebaz synth-ce read --pl-owner    # CE pad, owner must be the PS
```

The EMIO signals reach the pads only through a loaded bitstream: an unconfigured PL means no signal anywhere. A bitstream loaded at run time is gone after a reboot. The `BOOT.BIN` of 2026-11-15 14:53 in the PetaLinux project holds register map 1.2, which the software now refuses: load the map 2.x bitstream with `./fpga.sh`.

Start the server and the GUI:

```
./bench.sh                                          # board, from ~/sadiy (runs ./fpga.sh first); stop with Ctrl-C or ./stop.sh
sh zynq-ebaz/sw/pc/gui.sh <ebaz-ip>                 # PC, from the checkout
```

`sweepd` logs `build: sadiy ..., commit <hash> (main)`: it must be the commit you deployed (`python -m sadiy.buildinfo` in the checkout). In the GUI: Pins tab, **Enter bench mode**, answer the confirm. The status bar shows `LO not programmed`.

## 1. PCF8574 (the attenuator's port expander)

Wiring: `hw/boards/pe4302.md` (SCL = DATA2.20, SDA = DATA2.11, expander board on **3.3 V**, P0..P2 = V1..V3, P4..P6 = V4..V6, 2.2 kohm pull-ups from each V line to 3.3 V). Take the old attenuator wires off DATA2.14 to .19.

- On the board, `sweepd` stopped: `sudo i2cdetect -y -r 0`. Expect the PCF8574 at 0x27 (a PCF8574A: 0x38..0x3F; then set `[attenuator] pcf8574_address`).
- Enter bench mode. Expect no warning. "PE4302 not available: no answer from the PCF8574 ..." means wiring, supply or address. "the PCF8574 pins do not follow what was written (V...)" means that these lines have no working pull-up, or a short.
- With a DMM at power-up of the expander and in bench mode (31.5 dB): all six V lines above 2.3 V.

## 2. PE4302

First the logic, then the RF:

1. Pins tab, Raw access, PE4302: "Raw: one byte (wiring test)", tick one V box at a time and measure V1..V6 at the PE4302 header; or the Patterns page, "PE4302 stage by stage", with the DSLogic. V1 = 0.5 dB, V2 = 1, V3 = 2, V4 = 4, V5 = 8, V6 = 16, high = stage in. If polarity is as assumed (high = stage in): default 31.5 dB = all six high, 0 dB = all low; if you see the opposite, report it, the polarity in `config/default.toml` is then wrong. V6 goes through a 10 kohm series resistor: check that 3.3 V really switches the 16 dB stage. P3 is the backlight LED of the expander board (`pcf8574_backlight`).
2. RF check (needs the LO running if you measure after the mixer, so do step 3 first, with the main output on, at LO = RF + 10.7 MHz): generator at -40 dBm into the PE4302 input, measure behind it with the scope (the log detector is dead) while changing the attenuation in 8 dB steps. Expect 8 dB steps in level. A constant offset or a wrong step means a wrong weight or polarity: report which dB value gave which level. `python3 tools/bringup.py --platform ebaz pe4302-walk` (as root, `sweepd` stopped) does the same one stage at a time.

## 3. ADF4351 lock from the GUI

Synth tab. The frequency is the **LO**: LO = RF + 10.7 MHz. Use **Apply** with "Turn the main output on after lock" off first; read `LD` in the status bar (`LO 110.700000 MHz   LD 1`).

| LO to apply | RF it stands for | Expect |
|---|---|---|
| 40.7 MHz | 30 MHz | LD 1 (lowest RF in the sweep range) |
| 110.7 MHz | 100 MHz | LD 1 (preset) |
| 200.7 MHz | 190 MHz | LD 1 |
| 310.7 MHz | 300 MHz | LD 1 |
| 490.7 MHz | 480 MHz | LD 1 (highest) |
| 20 MHz | - | below the ADF4351 range: the frequency planner raises an error, the GUI must refuse it and nothing is written (`bringup.py pll --mhz 20` fails the same way) |

For every locked frequency: tick the main output, Apply, confirm, and measure RFOUTA with the MSO5354 (350 MHz) or a counter: the frequency must match the one you set (all five frequencies above are exact on the 25 MHz PFD grid: planned error 0 Hz, so any offset is the reference oscillator's, or a wrong register word; `python tools/bringup.py pll --mhz 110.7` prints the six words and the planned error). Above 350 MHz use the spectrum analyzer or only check LD. **RF off** after each. The register words are not yet compared with the datasheet or ADI's software: a wrong frequency with LD 1 means a wrong divider setting, report the value you measured and the words from the Device log.

Also try: Apply twice in a row (must stay locked), and Apply a new frequency while the output is on (Apply switches the outputs off first, then writes R5 to R0).

## 4. After

**Leave bench mode** (or close the GUI: the lines go back to safe), stop `sweepd` with Ctrl-C. To sweep again run `./sweep.sh` (needs register map 2.x in the PL; with no detector there is nothing to measure yet).

## Send back

The `sweepd` log lines of the session (GUI Advanced tab, Device log, or the ssh terminal), the status bar line per frequency, the DMM and scope readings, and which dB value gave which level. Write them into `ebaz-bringup.md` (S4/S7 table) from what you report.

Known: the GUI may show "sweepd sent no log" while a sweep runs; in bench-only mode `sweepd` answers at once, so it should not appear here.
