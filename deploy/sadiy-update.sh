#!/bin/sh
# Updates an existing /opt/sadiy from a package made on the PC with tools/make_bbb_package.py.
#
# Run on the BBB, using the script from the new package:
#   tar -xzf ~/sadiy-bbb-<name>.tar.gz -C /tmp sadiy-bbb/sadiy-update.sh
#   sudo sh /tmp/sadiy-bbb/sadiy-update.sh ~/sadiy-bbb-<name>.tar.gz
#
# Nothing on the running system changes until the new code has been unpacked and has loaded
# /etc/sadiy/local.toml. That file and the calibration data in /opt/sadiy/cal are kept. The previous copy
# stays in /opt/sadiy.old. If sweepd was running as a service and does not come back, the previous copy
# and unit files are restored.
#
# SADIY_DIR, SADIY_CONFIG, SADIY_UNIT_DIR, SADIY_PYTHON and SADIY_SETTLE_S exist for the tests.
set -u

DIR=${SADIY_DIR:-/opt/sadiy}
CONFIG=${SADIY_CONFIG:-/etc/sadiy/local.toml}
UNIT_DIR=${SADIY_UNIT_DIR:-/etc/systemd/system}
PYTHON=${SADIY_PYTHON:-python3}
SETTLE_S=${SADIY_SETTLE_S:-10}       # imports are slow on a BBB, and a crash has to show up in this time
STAGE=$DIR.new                       # same file system as $DIR, so moving it into place is one step
OLD=$DIR.old
SERVICE_WAS_ACTIVE=no
SWAPPED=no

say() { echo "sadiy-update: $*"; }
die() { echo "sadiy-update: $*" >&2; exit 1; }

service_active() {
    command -v systemctl >/dev/null 2>&1 && systemctl is-active --quiet sweepd
}

start_service_again() {
    if [ "$SERVICE_WAS_ACTIVE" = yes ]; then
        systemctl start sweepd || echo "sadiy-update: could not start sweepd" >&2
    fi
}

restore_units() {
    [ -d "$OLD/.units" ] || return 0
    cp "$OLD"/.units/* "$UNIT_DIR"/ && rm -rf "$OLD/.units"
    systemctl daemon-reload
}

roll_back() {
    say "$1. Putting the previous installation back"
    if [ "$SERVICE_WAS_ACTIVE" = yes ]; then
        systemctl stop sweepd
    fi
    restore_units
    if [ "$SWAPPED" = yes ]; then
        rm -rf "$DIR"
    fi
    mv "$OLD" "$DIR" || die "could not restore $OLD to $DIR: do it by hand"
    start_service_again
    die "update failed, the previous installation is back in $DIR"
}

# ---- check everything before touching the running system
[ $# -eq 1 ] || die "usage: sadiy-update.sh <sadiy-bbb-name.tar.gz>"
ARCHIVE=$1
[ -f "$ARCHIVE" ] || die "no such file: $ARCHIVE"
[ -d "$DIR" ] || die "no installation in $DIR: for a first install use install.sh"
[ -w "$(dirname "$DIR")" ] || die "no write access to $(dirname "$DIR"): run with sudo"

LISTING=$(tar -tzf "$ARCHIVE" 2>/dev/null) || die "$ARCHIVE is not a readable tar.gz"
if printf '%s\n' "$LISTING" | grep -q -v -e '^sadiy-bbb/' -e '^pax_global_header$'; then
    die "$ARCHIVE has files outside sadiy-bbb/: make it with tools/make_bbb_package.py"
fi
if printf '%s\n' "$LISTING" | grep -q -e '^\.\./' -e '/\.\./'; then
    die "$ARCHIVE has paths with .."
fi
printf '%s\n' "$LISTING" | grep -q '^sadiy-bbb/opt/sadiy/src/sadiy/server/sweepd\.py$' || die "$ARCHIVE is not a SAdiy package"

trap 'rm -rf "$STAGE"' EXIT
rm -rf "$STAGE"
mkdir "$STAGE" || die "could not create $STAGE"
tar -xzf "$ARCHIVE" --no-same-owner --strip-components=1 -C "$STAGE" || die "could not unpack $ARCHIVE"

(
    cd "$STAGE/opt/sadiy" && PYTHONPATH=src "$PYTHON" - "$CONFIG" <<'PY'
import os
import sys

import numpy, zmq                       # noqa: E401
from sadiy import config
import sadiy.server.sweepd              # noqa: F401

config.load(sys.argv[1] if os.path.exists(sys.argv[1]) else None)
PY
) || die "the new code does not load on this board or with $CONFIG; nothing was changed"
"$PYTHON" -c "import spidev" 2>/dev/null || say "warning: python3-spidev is missing, bench mode will have no SPI"

COMMIT=$("$PYTHON" -c "import sys, tarfile; print(tarfile.open(sys.argv[1]).pax_headers.get('comment', 'unknown'))" "$ARCHIVE" 2>/dev/null) || COMMIT=unknown

if service_active; then
    SERVICE_WAS_ACTIVE=yes
elif command -v pgrep >/dev/null 2>&1 && pgrep -f 'sadiy\.server\.sweepd' >/dev/null; then
    die "sweepd is running by hand: stop it with Ctrl-C and try again; nothing was changed"
fi

# ---- from here on the running system changes
if [ "$SERVICE_WAS_ACTIVE" = yes ]; then
    say "stopping sweepd"
    systemctl stop sweepd || die "could not stop sweepd; nothing was changed"
fi

rm -rf "$OLD"
if ! mv "$DIR" "$OLD"; then
    start_service_again
    die "could not move $DIR aside"
fi
mv "$STAGE/opt/sadiy" "$DIR" || roll_back "could not move the new code into place"
SWAPPED=yes
printf '%s\n' "$COMMIT" > "$DIR/.installed-commit"

# Calibration data is measured on this board and is in no package. Copied, so $OLD stays complete.
if [ -d "$OLD/cal" ]; then
    mkdir -p "$DIR/cal" && cp -a "$OLD/cal/." "$DIR/cal/" || roll_back "could not keep the calibration data"
fi

if [ ! -e "$CONFIG" ]; then
    mkdir -p "$(dirname "$CONFIG")" && cp "$STAGE/etc/sadiy/local.toml" "$CONFIG" || roll_back "could not create $CONFIG"
    say "created $CONFIG from the package: set the SPI and I2C bus numbers in it"
fi

# Only units that are already installed: enabling new ones is a decision, see docs/bbb-setup.md.
UNITS_CHANGED=no
for unit in sweepd.service sadiy-pinmux.service; do
    if [ -f "$UNIT_DIR/$unit" ] && ! cmp -s "$STAGE/etc/systemd/system/$unit" "$UNIT_DIR/$unit"; then
        mkdir -p "$OLD/.units" && cp "$UNIT_DIR/$unit" "$OLD/.units/" && cp "$STAGE/etc/systemd/system/$unit" "$UNIT_DIR/$unit" \
            || roll_back "could not update $unit"
        say "updated $unit, the previous one is in $OLD/.units"
        UNITS_CHANGED=yes
    fi
done
if [ "$UNITS_CHANGED" = yes ]; then
    systemctl daemon-reload || roll_back "systemctl daemon-reload failed"
fi

"$DIR/deploy/sadiy-pinmux.sh" || say "warning: could not set all pin modes, see the messages above"

if [ "$SERVICE_WAS_ACTIVE" = yes ]; then
    say "starting sweepd"
    systemctl start sweepd || roll_back "sweepd did not start"
    sleep "$SETTLE_S"
    service_active || roll_back "sweepd stopped again after starting (see journalctl -u sweepd)"
    say "sweepd is running"
else
    say "sweepd was not running as a service, so start it yourself:"
    say "  cd $DIR && sudo PYTHONPATH=src python3 -m sadiy.server.sweepd --bench-only --config $CONFIG"
fi

say "installed commit $COMMIT in $DIR; the previous copy is in $OLD"
