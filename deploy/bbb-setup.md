# BeagleBone Black setup notes

None of this has been tried on a real BBB yet. Verify every pin and overlay name on your image (`uname -r`, `cat /etc/dogtag`, `config-pin -q`).

## Install

1. Debian IoT image, headless. Check `python3 --version`: the project needs 3.9 or newer.
2. Install the packages:
   ```bash
   sudo apt install python3-numpy python3-zmq python3-spidev i2c-tools
   ```
   Below Python 3.11, also install `python3-tomli`. Without internet on the BBB, see [Without internet](#without-internet).
3. Get the code into `/opt/sadiy`:
   ```bash
   sudo git clone https://github.com/patrikeder/SAdiy.git /opt/sadiy
   ```
   The BBB needs no Qt. Without internet on the BBB, see [Without internet](#without-internet).

## Buses and pins

4. Enable SPI0 with the spidev overlay, a U-Boot overlay line in `/boot/uEnv.txt`. The name depends on the image. On Debian Trixie with kernel 6.18 the file is `/boot/dtbs/<kernel>/overlays/BB-SPIDEV0-00A0.dtbo`, and the line uses the bare name:
   ```
   uboot_overlay_addr4=BB-SPIDEV0-00A0.dtbo
   ```
   Keep a copy of `uEnv.txt`, then reboot. Run `ls /dev/spidev*` and note the bus number: `/dev/spidev1.0` means 1, `/dev/spidev0.0` means 0.
5. Check the wiring against the map: SPI0 (ADF4351) on P9.17 CS0, P9.18 MOSI, P9.22 SCLK. PE4302 V1..V6 as plain GPIO on P8.7, 8, 9, 10, 11, 12 (GPIO numbers 66, 67, 69, 68, 45, 44). See `hw/wiring-bbb.md`. Check how they map on this kernel; this only reads:
   ```bash
   cd /opt/sadiy && PYTHONPATH=src python3 tools/bringup.py gpio-map
   ```
6. Set the pin modes where the image has `config-pin`:
   ```bash
   sudo /opt/sadiy/deploy/sadiy-pinmux.sh
   ```
   If a mode name differs on your image (`config-pin -l P9_17`), correct it in both the script and `src/sadiy/pinmap.py` (`mux=`). The Debian Trixie image has no `config-pin`: the script then says so and does nothing, I2C2 is already on, SPI0 comes from step 4, and the rest stay at their defaults. Check that the GPIO pins really are in GPIO mode, shown by a last digit of 7 (or `f`) in the register value. Pins 12, 13, 17, 36, 37, 38, 39 and 105 are P8.12, P8.11, P9.23, P8.7, P8.8, P8.10, P8.9 and P9.27:
   ```bash
   sudo grep -E '^pin (12|13|17|36|37|38|39|105) ' /sys/kernel/debug/pinctrl/*pinmux*/pins
   ```
   Without `config-pin`, bench mode refuses to use SPI and I2C pins as GPIO.
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

## Without internet

This replaces steps 2 and 3 when the BBB has only SSH and SFTP from a PC, and it is also how to update later. The code goes over as a package built on the PC. The examples use the usual default user `debian`; change it if yours differs.

### Build the package

On the PC, from the repo root:

```bash
python tools/make_bbb_package.py
```

This writes `dist/sadiy-bbb-<version>-<commit>.tar.gz` and its `.sha256`. The name ends in `-dirty` if there are uncommitted changes, which are included. Send both files with SFTP. At the `sftp debian@<bbb-ip>` prompt, from the repo root:

```
put dist/sadiy-bbb-<name>.tar.gz
put dist/sadiy-bbb-<name>.tar.gz.sha256
bye
```

On the BBB, check the copy:

```bash
sha256sum -c sadiy-bbb-<name>.tar.gz.sha256
```

### Update an existing installation

On the BBB, take the update script from the new package and run it:

```bash
tar -xzf ~/sadiy-bbb-<name>.tar.gz -C /tmp sadiy-bbb/sadiy-update.sh
```

```bash
sudo sh /tmp/sadiy-bbb/sadiy-update.sh ~/sadiy-bbb-<name>.tar.gz
```

Stop `sweepd` first if it is running by hand; the script refuses otherwise. It then:

- checks the package and that the new code loads with your `local.toml`, before changing anything
- stops the `sweepd` service if it is running, which returns any driven lines to the safe state
- swaps the code, keeping one previous copy in `/opt/sadiy.old`
- keeps `/etc/sadiy/local.toml` and the calibration data in `/opt/sadiy/cal`
- replaces the unit files that are already installed, keeping the old ones in `/opt/sadiy.old/.units`
- sets the pin modes again and starts the service again, if it was running
- restores the previous copy and unit files if the service does not come back

To install the pin mode service on a board that does not have it yet, see step 13. If you correct something directly on the BBB, such as a `config-pin` mode name, copy the change back to the PC, or the next update replaces it. A BBB without internet may have the wrong time, so `tar` can warn about timestamps in the future. That is harmless.

### First install

On the BBB, from your home folder:

```bash
tar -xzf sadiy-bbb-<name>.tar.gz && cd sadiy-bbb && sudo ./install.sh
```

It reports any missing packages, then stops. Next, continue with step 4.

### Install missing packages

`install.sh` lists what is missing. On the BBB, list the download links, including dependencies. Below Python 3.11, add `python3-tomli`:

```bash
apt-get install --print-uris -qq python3-numpy python3-zmq python3-spidev i2c-tools | cut -d"'" -f2 > ~/debs.txt
```

On the PC, fetch the list and download the packages:

```bash
sftp debian@<bbb-ip>:debs.txt ~/debs.txt
```

```bash
mkdir -p ~/bbb-debs && wget -P ~/bbb-debs -i ~/debs.txt
```

Send them to the BBB:

```bash
sftp debian@<bbb-ip>
```

At the `sftp>` prompt, replacing `<pc-home>` with your home folder on the PC:

```
mkdir debs
put <pc-home>/bbb-debs/* debs/
bye
```

On the BBB, install them:

```bash
sudo apt install ~/debs/*.deb
```

The BBB's package lists may be old, so some links can return 404 and the list can come out empty. Then download the same packages for your Debian release (`cat /etc/os-release`) and `armhf` from packages.debian.org.

## Network safety

`sweepd` has no authentication and binds all interfaces by default. Anyone who can reach port 5557 can open bench mode and drive pins, including the RF outputs. Keep the BBB on a trusted network, or set `[server]` in `local.toml` to listen on one address (see `local.toml.example`).
