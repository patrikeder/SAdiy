# BeagleBone Black setup notes

None of this has been tried on a real BBB yet. Verify every pin and overlay name on your image (`uname -r`, `cat /etc/dogtag`, `config-pin -q`).

## Install

1. Debian IoT image, headless. Check `python3 --version`: the project needs 3.9 or newer.
2. Install the packages:
   ```bash
   sudo apt install python3-numpy python3-zmq python3-spidev i2c-tools
   ```
   Below Python 3.11, also install `python3-tomli`.
3. Get the code into `/opt/sadiy`:
   ```bash
   sudo git clone https://github.com/patrikeder/SAdiy.git /opt/sadiy
   ```
   The BBB needs no Qt.

## Buses and pins

4. Enable SPI0 with the spidev overlay (U-Boot overlay line in `/boot/uEnv.txt`, name depends on the image). Then run `ls /dev/spidev*` and note the bus number: `/dev/spidev1.0` means 1, `/dev/spidev0.0` means 0.
5. Check the wiring against the map: SPI0 (ADF4351) on P9.17 CS0, P9.18 MOSI, P9.22 SCLK. PE4302 V1..V6 as plain GPIO on P8.7, 8, 9, 10, 11, 12 (kernel GPIO 66, 67, 69, 68, 45, 44). See `hw/wiring-bbb.md`.
6. Set the pin modes. Check what your image offers with `config-pin -l P9_17`, then run the script:
   ```bash
   sudo /opt/sadiy/deploy/sadiy-pinmux.sh
   ```
   If a mode name differs on your image, correct it in both the script and `src/sadiy/pinmap.py` (`mux=`). Newer images may not have `config-pin`: the script then stops with an error, and the pin modes have to come from overlays. Bench mode also calls `config-pin` when a bus pin is used as GPIO and back, so that feature won't work without it.
7. ADS1115 (main ADC, on I2C2, P9.19 / P9.20): `i2cdetect -y -r 2` should show 0x48. I2C2 is usually `/dev/i2c-2` on recent kernels and `/dev/i2c-1` on old 3.8 kernels. The same bus probes cape EEPROMs, so other addresses may show up.
8. On-chip ADC, used as a cross-check: IIO, `/sys/bus/iio/devices/iio:device0/in_voltage0_raw`. 0 to 1.8 V only.
9. CPU governor: `sudo cpufreq-set -g performance`.

## Configure

10. Create the local config, then set the SPI and I2C bus numbers you found above in it:
    ```bash
    sudo mkdir -p /etc/sadiy
    ```
    ```bash
    sudo cp /opt/sadiy/deploy/local.toml.example /etc/sadiy/local.toml
    ```

## Run

11. Try it by hand first. It runs as root, the simple way to reach GPIO, SPI, I2C and `config-pin`:
    ```bash
    cd /opt/sadiy && sudo PYTHONPATH=src python3 -m sadiy.server.sweepd --bench-only --config /etc/sadiy/local.toml
    ```
12. From a PC, connect and use the Pins tab (`docs/gui.md`). Both ports (5556 frames, 5557 commands) must be reachable from the PC:
    ```bash
    python -m sadiy.ui.sa_gui --host <bbb-ip> --connect
    ```
13. To start it at boot, stop the manual run and install the services. `sadiy-pinmux.service` sets the pin modes, which do not survive a reboot:
    ```bash
    sudo cp /opt/sadiy/deploy/sweepd.service /opt/sadiy/deploy/sadiy-pinmux.service /etc/systemd/system/
    ```
    ```bash
    sudo systemctl daemon-reload
    ```
    ```bash
    sudo systemctl enable --now sadiy-pinmux sweepd
    ```
    Check it with `systemctl status sweepd` and `journalctl -u sadiy-pinmux`. Stop the service before running `sweepd` by hand, because both use the same ports.

The service uses `--bench-only` until `build_hw_engine` exists, because `sweepd` exits at once on hardware without it, so the Run button is refused for now. Remove the flag when sweeps work on hardware. `sweepd` touches no pin until a client opens bench mode, so until then the PE4302 stays at the 31.5 dB default set by the adapter's pull-ups.

## Network safety

`sweepd` has no authentication and binds all interfaces by default. Anyone who can reach port 5557 can open bench mode and drive pins, including the RF outputs. Keep the BBB on a trusted network, or set `[server]` in `local.toml` to listen on one address (see `local.toml.example`).
