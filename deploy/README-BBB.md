# SAdiy package for the BeagleBone Black

Mirrors the target file system: `opt/sadiy` -> `/opt/sadiy`, `etc/sadiy/local.toml` -> `/etc/sadiy/local.toml`
(kept if it already exists), `etc/systemd/system/*.service` -> `/etc/systemd/system/`.
Not included: the Qt GUI (`sa_gui`, runs on the PC), tests, KiCad files, photos, diagrams, `.venv`.

None of the hardware paths have been tried on a real BBB yet. Full notes: `opt/sadiy/docs/bbb-setup.md`.

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
- `tools/bringup.py`: `pe4302-walk --gpio 66,67,69,68,45,44` (GPIO as root), `pe4302-pattern`, `pll`.
- **Sweeping on real hardware is not implemented:** `build_hw_engine`, ADF4351 register packing R0..R3/R5.
  The service therefore runs with `--bench-only`.
