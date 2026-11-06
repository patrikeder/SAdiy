#!/bin/sh
# Sets the BBB pin modes SAdiy needs. config-pin settings do not survive a reboot, so
# sadiy-pinmux.service runs this at boot. Must match src/sadiy/pinmap.py (tests/test_deploy.py checks).
# Mode names are the usual ones, not yet verified on a real image: check with config-pin -l P9_17.
set -u

if ! command -v config-pin >/dev/null 2>&1; then
    # Normal on the Trixie images: no cape-universal, so the modes come from overlays and defaults.
    echo "sadiy-pinmux: config-pin not found, leaving the pin modes as they are"
    exit 0
fi

status=0
set_mode() {
    if ! config-pin "$1" "$2"; then
        echo "sadiy-pinmux: config-pin $1 $2 failed" >&2
        status=1
    fi
}

# ADF4351
set_mode P9_17 spi_cs
set_mode P9_18 spi
set_mode P9_22 spi_sclk
set_mode P9_23 gpio
set_mode P9_27 gpio
# ADS1115
set_mode P9_19 i2c
set_mode P9_20 i2c
# PE4302
set_mode P8_07 gpio
set_mode P8_08 gpio
set_mode P8_09 gpio
set_mode P8_10 gpio
set_mode P8_11 gpio
set_mode P8_12 gpio

exit "$status"
