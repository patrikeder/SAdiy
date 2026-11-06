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

## Without internet

This replaces steps 2 and 3 when the BBB has only SSH and SFTP from a PC, and it is also how to update later. The examples use the usual default user `debian`; change it if yours differs.

### Copy the code

On the PC, from the repo root, pack `main` and send it. The archive holds commits only, so commit first:

```bash
git archive --format=tar.gz --prefix=sadiy/ -o ~/sadiy.tar.gz main
```

```bash
sftp debian@<bbb-ip>
```

At the `sftp>` prompt, replacing `<pc-home>` with your home folder on the PC:

```
put <pc-home>/sadiy.tar.gz
bye
```

On the BBB, unpack it:

```bash
rm -rf ~/sadiy-new && mkdir ~/sadiy-new && tar -xzf ~/sadiy.tar.gz -C ~/sadiy-new
```

If the service is installed, stop it:

```bash
sudo systemctl stop sweepd
```

Swap the folders. The previous copy is kept as `/opt/sadiy.old` until the next update, and `/etc/sadiy/local.toml` is not touched:

```bash
if [ -d /opt/sadiy ]; then sudo rm -rf /opt/sadiy.old; sudo mv /opt/sadiy /opt/sadiy.old; fi
```

```bash
sudo mv ~/sadiy-new/sadiy /opt/sadiy && sudo chown -R root:root /opt/sadiy
```

A BBB without internet may have the wrong time, so `tar` can warn about timestamps in the future. That is harmless. If you correct something directly on the BBB, such as a `config-pin` mode name, copy the change back to the PC, or the next update replaces it.

### Check the packages

```bash
python3 --version
```

```bash
cd /opt/sadiy && PYTHONPATH=src python3 -c "import numpy, zmq, spidev; import sadiy.server.sweepd; print('ok')"
```

```bash
which i2cdetect
```

It needs Python 3.9 or newer. If the second command prints `ok` and `i2cdetect` is found, nothing is missing. Otherwise the error names the missing module.

### Install missing packages

On the BBB, list the download links, including dependencies. Below Python 3.11, add `python3-tomli`:

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

### After copying

On a first install, continue with step 4. On an update, set the pin modes again if the boot service is not installed (step 6), then start `sweepd` by hand (step 11). If you use the services, install their unit files again in case they changed (step 13), which restarts nothing that is already running, so finish with:

```bash
sudo systemctl restart sadiy-pinmux sweepd
```

## Network safety

`sweepd` has no authentication and binds all interfaces by default. Anyone who can reach port 5557 can open bench mode and drive pins, including the RF outputs. Keep the BBB on a trusted network, or set `[server]` in `local.toml` to listen on one address (see `local.toml.example`).
