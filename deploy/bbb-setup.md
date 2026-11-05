# BeagleBone Black setup notes

Verify every pin and overlay name on your image (`uname -r`, `cat /etc/dogtag`, `config-pin -q`).

1. Debian IoT image, headless. `sudo apt install python3-numpy python3-zmq python3-spidev`.
2. Enable SPI0 with the spidev overlay (U-Boot overlay line in `/boot/uEnv.txt`, name depends on the image). Then `ls /dev/spidev*` and put the bus number in `[bench] spi_bus` (`/dev/spidev1.0` means 1, `/dev/spidev0.0` means 0).
3. SPI0 (ADF4351): P9.17 CS0, P9.18 MOSI, P9.22 SCLK. PE4302 inputs V1..V6 as plain GPIO on P8.7, 8, 9, 10, 11, 12 (kernel GPIO 66, 67, 69, 68, 45, 44); P8 has no SPI, none is needed. See `hw/wiring-bbb.md`.
4. Pin mux. Check the modes your image offers with `config-pin -l P9_17`, then set them. The mode names below are the usual ones; they are in `src/sadiy/pinmap.py` (`mux=`), so correct them there if yours differ:
   ```
   config-pin P9_17 spi_cs; config-pin P9_18 spi; config-pin P9_22 spi_sclk
   config-pin P9_19 i2c; config-pin P9_20 i2c
   config-pin P9_23 gpio; config-pin P9_27 gpio
   for p in 07 08 09 10 11 12; do config-pin P8_$p gpio; done
   ```
   These do not survive a reboot unless they are in a boot script. The bench mode also calls `config-pin` itself when a bus pin is used as GPIO and back, so the `sweepd` user needs to be allowed to run it.
5. ADS1115 (main ADC, on I2C2, P9.19 / P9.20): `i2cdetect -y -r 2` should show 0x48. I2C2 is usually `/dev/i2c-2` on recent kernels and `/dev/i2c-1` on old 3.8 kernels; put the number in `[bench] i2c_bus`. The same bus probes cape EEPROMs, so other addresses may show up.
6. On-chip ADC, used as a cross-check: IIO, `/sys/bus/iio/devices/iio:device0/in_voltage0_raw`. 0 to 1.8 V only.
7. CPU governor: `sudo cpufreq-set -g performance`.
8. Copy the project to `/opt/sadiy`, config to `/etc/sadiy/local.toml`, install `deploy/sweepd.service`
   into `/etc/systemd/system/`, then `systemctl enable --now sweepd`.
9. View from a PC (the BBB needs no Qt): `python -m sadiy.ui.sa_gui --host <bbb-ip> --connect`. `sweepd` binds `tcp://*:5556` (frames) and `tcp://*:5557` (commands), so both ports must be reachable from the PC. Use `--sim` only for a simulator on the PC itself.
10. Bench mode (Pins tab) before the sweep hardware code exists: stop the service and run `python -m sadiy.server.sweepd --bench-only --config /etc/sadiy/local.toml`. It needs access to `/sys/class/gpio`, `/dev/spidev*`, `/dev/i2c-*` and `config-pin`. None of this has been tried on a real BBB yet; see `docs/gui.md`.
