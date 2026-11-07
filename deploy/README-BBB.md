# SAdiy package for the BeagleBone Black

Mirrors the target file system: `opt/sadiy` -> `/opt/sadiy`, `etc/sadiy/local.toml` -> `/etc/sadiy/local.toml`
(kept if it already exists), `etc/systemd/system/*.service` -> `/etc/systemd/system/`.
Not included: the Qt GUI (`sa_gui`, runs on the PC), tests, KiCad files, photos, diagrams, `.venv`.

None of the hardware paths have run on a real BBB yet (the image itself was read from one: Debian Trixie, kernel 6.18, no `config-pin`). Full notes: `opt/sadiy/docs/bbb-setup.md`. The diagrams are not in this package, so the images in `opt/sadiy/hw/wiring-bbb.md` do not show here.

## Update an existing installation

Upload the new `sadiy-bbb-*.tar.gz` and its `.sha256` to the BBB's home folder, then on the BBB:

    cd ~ && sha256sum -c sadiy-bbb-*.sha256
    tar -xzf sadiy-bbb-<name>.tar.gz -C /tmp sadiy-bbb/sadiy-update.sh
    sudo sh /tmp/sadiy-bbb/sadiy-update.sh ~/sadiy-bbb-<name>.tar.gz

It keeps `/etc/sadiy/local.toml` and the calibration data in `/opt/sadiy/cal`, leaves the previous copy in
`/opt/sadiy.old`, and restores it if the sweepd service does not come back. It replaces only the unit files
that are already installed.

## First install

    tar -xzf sadiy-bbb-<name>.tar.gz && cd sadiy-bbb && sudo ./install.sh

`install.sh` installs nothing from the network. If packages are missing it prints the `apt install` line and
stops. Without internet on the BBB, see "Install missing packages" in `opt/sadiy/docs/bbb-setup.md`.

## What works today

- Bench mode on real hardware, written but untested: `sweepd --bench-only`, used from the GUI's Pins tab on
  the PC with `python -m sadiy.ui.sa_gui --host <bbb-ip> --connect` (ports 5556 frames, 5557 commands).
- `sweepd --sim` on the BBB, viewed from the PC the same way.
- Messages: `journalctl -u sweepd -f` (levels error to trace; `-v`, `-vv`, `-q`, or `[log] level` in `local.toml`).
  The GUI shows error, warning, info and debug in the Device log of its Advanced tab.
- `tools/bringup.py`: `gpio-map`, `pe4302-walk --gpio 66,67,69,68,45,44` (GPIO as root), `pe4302-pattern`, `adf4351-pattern`, `pll`, `sim-sweep`.
- **Sweeping on real hardware is not implemented:** `build_hw_engine`. The ADF4351 register words exist but are unchecked against ADI's software.
  The service therefore runs with `--bench-only`.
