# EBAZ4205 bring-up (S4)

Status 2026-11-14: Phase 1 image boots (see `ebaz-baseline.md`); the EMIO readback below passed; the rebuilt image (LCD, LEDs, keys) is not booted yet; the other electrical checks need the user at the bench.

## Known from the first boot (S1 baseline, 2026-11-14)
- Kernel 6.12.40, Zynq PS7, PL state `operating` (Phase 1 bitstream from BOOT.BIN), Ethernet 100 Mbit/full, IP 192.168.88.244.
- The network interface is `enx000a35001e53` (renamed from eth0 by udev), MAC 00:0a:35:00:1e:53.
- `/dev/spidev0.0`, `/dev/i2c-0`, `/dev/gpiochip0` exist, all `root` only (mode 600): use sudo or add a udev rule / group.
- GPIO: `zynq_gpio`, sysfs base 512, 118 lines (54 MIO + 64 EMIO). Expected EMIO line n at gpiochip0 offset 54 + n
  (sysfs number 512 + 54 + n); check with `gpioinfo`.
- Python 3.12.11 with zmq, numpy, spidev, tomllib; no gpiod or smbus module; `devmem`, i2c-tools, gpiod tools present.
- Root is mounted `ro` (mmcblk0p2 ext4).

## Checklist for the bench session
Do each step with the PE4302 at 31.5 dB (nothing driven) before any RF is connected.

1. Boot the new image from the second SD card; `sh -s < sw/tools/ebaz_baseline.sh`. Expect
   `/dev/spidev0.0`, an I2C adapter, the Zynq gpiochip with 54+16 lines.
2. EMIO line numbering: with `gpioset`/libgpiod toggle line 54 + n and probe the adapter pin
   with a DMM or the DSLogic (n = 0..6 outputs, 7 input).
3. `python tools/bringup.py pe4302-walk` with the mapped lines: detector rises by weight x 24.5 mV.
4. DSLogic on CLK, DAT, LE: `adf4351-pattern` frames decode as in `patterns.py`.
5. ADF4351 at 100 MHz on the MSO5354 (outputs off until enabled after lock).
6. ADS1115 answers at 0x48 (`i2cdetect -y N`).
7. CE from software: `python3 tools/bringup.py --platform ebaz synth-ce read` (then `off` / `on` / `release`, with sudo -E; DMM on DATA2.13 / the CE header pin, J12 1-2 holds it high). After `off` then `on` the ADF4351 needs its registers again. Deploy the tools first with `sw/deploy/deploy_to_board.sh`.

Results go below (what was measured, instrument, date).

## Results, 2026-11-14 (nothing connected to DATA1/2/3; instruments: none)

Scripts: `sw/tools/ebaz_s4_readonly.sh`, `sw/tools/ebaz_s4_readback.sh`, run on the board with sudo; raw output was read from
`/tmp/s4_*.txt` on the board.

| Check | Result |
|---|---|
| EMIO direction after boot (DIRM_2, OEN_2) | 0x00000000: all EMIO lines are inputs, PE4302 and CE tri-stated. |
| Readback of EMIO n = 0..6 through sysfs (offset 512 + 54 + n) | **ALL PASS**: pad level, sysfs value, DIRM and OEN follow high and low for V1..V6 and CE. After the test DIRM_2 and OEN_2 are 0 again. |
| LD (n = 7) | 0 with nothing connected (pull-down in the XDC), as expected. |
| I2C bus 0 scan | Inconclusive and expected: nothing wired. The Cadence controller has no SMBus Quick Write, so `i2cdetect` skips 0x48 unless run as `-r`; use `i2cget -y 0 0x48 0x01 w` (expect 0x8583) once the ADS1115 is wired. |
| Pad levels of floating lines | Not meaningful. `gpioget` on 54..60 returned 1 and `devmem DATA_2_RO` returned 0 a moment apart; unexplained, most likely floating pads, repeat with the adapter connected. |

What this proves: line numbering 54 + n and the PL IOBUF path. What it does not prove: that each signal is on the right DATA2 pin
(needs a DMM or the DSLogic at the connector) and anything about the PE4302, ADF4351 or ADS1115.

## Still open (needs the user at the bench)
- Pin location: drive each line and probe the DATA2 pins (G20 CLK, G19 DAT, H20 LE, J19 LD in, K19 CE, J20 L16 L19 M18 L20 M20 V1..V6, K18 L17 I2C).
- SPI frames from `/dev/spidev0.0` on the DSLogic (needs `adf4351-pattern`-style words; mode 0, 10 MHz, LE low for the whole word).
- With the adapter connected: pad levels with pull-ups (expect V1..V6 = 1, CE = 1), PE4302 walk, ADF4351 at 100 MHz, ADS1115.


## Adapter LCD, LEDs and keys (image rebuilt 2026-11-14, NOT yet booted)

Session R's engine design changed the PS7 (SPI1 on EMIO, 18 EMIO GPIO lines) and wires the adapter's ST7789 LCD,
three LEDs and five keys to Linux: see `docs/lcd-st7789.md`. The boot image is now built from R's XSA
(`xsa/ebaz_sadiy_20261114_1709.xsa` in the PetaLinux project, a snapshot of `build/fpga/ebaz_sadiy.xsa`), so BOOT.BIN
contains the engine bitstream (it was `BOOT_engine.BIN` before) and the PS7 and FSBL match. Phase 1 files: `BOOT.BIN`,
`image.ub`, `boot.scr`, `system.dtb` are saved in `images/phase1-backup/` of the project.

| What | Where |
|---|---|
| Device tree | `sw/deploy/petalinux/system-user.dtsi`: `&spi1` with `sitronix,st7789v` (DC = line 62, RES = 63), `gpio-leds` (64..66), `gpio-keys` (67..71) |
| Kernel | fragment `sw/deploy/petalinux/kernel/user_lcd.cfg`: `FRAMEBUFFER_CONSOLE` and fonts. fbtft ST7789V, `LEDS_GPIO`, `KEYBOARD_GPIO`, `SPI_CADENCE` were in already |
| Test on the board | `sw/tools/ebaz_lcd_test.py` (`info`, `bars`, `clear`, `leds`, `keys`) |

With the framebuffer console the kernel messages and the login prompt also appear on the LCD (`tty1`); the serial
console stays `ttyPS0`. Panel size (240x240 is a guess), colour order and RAM offset are the open points: `bars` shows them.
Phase 1 (`rtl/vivado/phase1.tcl`) now has the same PS7 (SPI1 EMIO, 18 GPIO) but does not wire the LCD pads: a Phase 1 image
shows nothing on the LCD.

Checks after booting (user at the board, sudo needed for /dev and sysfs):
1. `dmesg | grep -i -E "st7789|fbtft|spi1|fb0|Console: switching"`: the display driver binds, a framebuffer appears.
2. `python3 ebaz_lcd_test.py info` then `sudo python3 ebaz_lcd_test.py bars`: border on all four sides, corners red / green / blue / yellow.
3. `sudo python3 ebaz_lcd_test.py leds` and `keys`.
4. The old checks still hold: eth0 up, `gpioinfo` now shows 118 lines with EMIO 0..17 (lines 54..71) in use by the leds / keys / display.

### `top` on the LCD instead of a login prompt (2026-11-15)

The image starts a login on tty1 (`1:12345:respawn:/sbin/getty 38400 tty1` in `/etc/inittab`), which is useless on the
LCD: no keyboard, about 30 text columns. `sw/tools/ebaz_lcd_top.sh` replaces it with a continuously updated `top`
(time and load, tasks, CPU, memory, then PID, %CPU, %MEM, COMMAND; the wrapper takes the last frame of `top -b` and
shortens it to the console size, because plain `top` would cut off %CPU and the command at 30 columns).

```
sh ~/sadiy/zynq-ebaz/sw/deploy/deploy_to_board.sh <ebaz-ip>      # on the PC, copies the script (it is in sw/tools)
sudo sh ~/sadiy/zynq-ebaz/sw/tools/ebaz_lcd_top.sh status         # console size, what is installed
sudo sh ~/sadiy/zynq-ebaz/sw/tools/ebaz_lcd_top.sh install        # tty1 shows top from now on, also after reboots
sudo sh ~/sadiy/zynq-ebaz/sw/tools/ebaz_lcd_top.sh remove         # login prompt back
sh ~/sadiy/zynq-ebaz/sw/tools/ebaz_lcd_top.sh frame               # one frame on the terminal, to see the layout
```
`install` remounts `/` read-write for a moment (the inittab lives on the SD card, so no new image is needed), keeps the old
file as `/etc/inittab.sadiy-orig` and leaves the serial console login on ttyPS0 alone. Number of rows follows the console
font (15 rows with 8x16, 30 with 8x8): `status` prints it. Notes: `ebaz_lcd_test.py bars` draws on the same screen, so
run `remove` first or the next `top` frame overwrites the bars; pressing KEY1..KEY5 types `1`..`5` into the console
(harmless, top ignores them). Works on the board (user report 2026-11-15); also checked with the host's `top` and fake
`top` output in `sw/tests/test_lcd_top.py`.
