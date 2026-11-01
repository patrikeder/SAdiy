# BeagleBone Black setup notes

Verify every pin and overlay name on your image (`uname -r`, `cat /etc/dogtag`, `config-pin -q`).

1. Debian IoT image, headless. `sudo apt install python3-numpy python3-zmq python3-spidev`.
2. Enable SPI0 with the spidev overlay (U-Boot overlay line in `/boot/uEnv.txt`, name depends on the image).
3. SPI0 (ADF4351): P9.17 CS0, P9.18 MOSI, P9.22 SCLK. PE4302 inputs V1..V6 as plain GPIO on P8.7, 8, 9, 10, 11, 12 (kernel GPIO 66, 67, 69, 68, 45, 44); P8 has no SPI, none is needed. See `hw/wiring-bbb.md`.
4. On-chip ADC is IIO: `/sys/bus/iio/devices/iio:device0/in_voltage0_raw`. 0 to 1.8 V only.
5. CPU governor: `sudo cpufreq-set -g performance`.
6. Copy the project to `/opt/sadiy`, config to `/etc/sadiy/local.toml`, install `deploy/sweepd.service`
   into `/etc/systemd/system/`, then `systemctl enable --now sweepd`.
7. View from a PC: `python -m sadiy.ui.qt_client --host <bbb-ip>`.
