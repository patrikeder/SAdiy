# Bench test: ADS1115, PE4302, ADF4351 lock (EBAZ4205, Linux owns the pins)

Goal: check the detector ADC, the attenuator and whether the LO locks at the frequencies set in the GUI. Nothing here has run on the board yet; every "expect" below is from the datasheets and the code, not a measurement. Mode: `sweepd --platform ebaz --bench-only` (PS path: `/dev/spidev0.0`, `/dev/i2c-0`, EMIO GPIO; the sweep engine is not used).

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

On the board (`ssh petalinux@<ebaz-ip>`):

```
cat /sys/class/fpga_manager/fpga0/state          # must say: operating (else: cd ~/sadiy/bringup-pkg && sudo ./sadiy_pl_load.sh)
ls /dev/spidev0.0 /dev/i2c-*                     # both must exist
. ~/sadiy/env.sh
python3 ~/sadiy/tools/bringup.py --platform ebaz gpio-map          # EMIO numbers and Linux line numbers
python3 ~/sadiy/tools/bringup.py --platform ebaz synth-ce read --pl-owner    # CE pad, owner must be the PS
```

The EMIO signals reach the pads only through a loaded bitstream: an unconfigured PL means no signal anywhere. A bitstream loaded at run time is gone after a reboot; the SD card holds it only when `BOOT.BIN` and `image.ub` of 2026-11-15 14:53 (PetaLinux project, `images/linux/`) were copied to it.

Start the server and the GUI:

```
sudo env PYTHONPATH=$PYTHONPATH python3 -m sadiy.server.sweepd --platform ebaz --bench-only     # board
python -m sadiy.ui.sa_gui --platform ebaz --host <ebaz-ip> --connect                             # PC
```

`sweepd` logs `build: sadiy ..., commit <hash> (main)`: it must be the commit you deployed (`python -m sadiy.buildinfo` in the checkout). In the GUI: Pins tab, **Enter bench mode**, answer the confirm. The status bar shows `LO not programmed`.

## 1. ADS1115 (detector ADC)

Pins tab, Raw access, ADC: convert channel 0 (AIN0 of the ADS1115 is the detector).

- Expect: no error; code, volts, config and conversion register shown. An I2C error (nack) means wiring (SDA = DATA2.11, SCL = DATA2.20), address pin (0x48 = ADDR to GND), supply or pull-ups.
- Compare the volts with a DMM at the detector output: agree within a few mV (ADS1115 default range 4.096 V, 125 microvolt per code). With no RF the AD8318-class detector sits high, up to about 1.9 V.
- Repeat on channels 1 to 3 (open inputs float: only the error-free read counts).

## 2. PE4302

First the logic, then the RF:

1. Patterns page, "PE4302 stage by stage" with a DMM or the DSLogic on V1..V6 (DATA2.14 to .19): V1 = 0.5 dB, V2 = 1, V3 = 2, V4 = 4, V5 = 8, V6 = 16, high = stage in. If polarity is as assumed (high = stage in): default 31.5 dB = all six high, 0 dB = all low; if you see the opposite, report it, the polarity in `config/default.toml` is then wrong. V6 goes through a 10 kohm series resistor: check that 3.3 V really switches the 16 dB stage.
2. RF check (needs the LO running, so do step 3 first, with the main output on, at LO = RF + 10.7 MHz): generator at -40 dBm into the PE4302 input, read the detector through step 1 while changing the attenuation in 8 dB steps. Expect the detector voltage to move about 25 mV per dB (negative slope: more attenuation, higher voltage), so 8 dB is about 200 mV. A constant offset or a wrong step means a wrong weight or polarity: report which dB value gave which voltage.

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

**Leave bench mode** (or close the GUI: the lines go back to safe), stop `sweepd` with Ctrl-C. To sweep again run `sweepd --platform ebaz` (needs map 1.1 or newer in the PL).

## Send back

The `sweepd` log lines of the session (GUI Advanced tab, Device log, or the ssh terminal), the status bar line per frequency, the DMM and scope readings, and which dB value gave which detector voltage. Write them into `ebaz-bringup.md` (S4/S7 table) from what you report.

Known: the GUI may show "sweepd sent no log" while a sweep runs; in bench-only mode `sweepd` answers at once, so it should not appear here.
