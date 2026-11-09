# Working from another PC (session handoff)

**One machine works on the project at a time.** The GitHub repository (`origin`, `https://github.com/patrikeder/SAdiy.git`) is the single source of truth. Nothing that matters may live only on one PC: not in the working tree, not in `dist/`, `captures/` or `cal/*.json`, and not in Claude Code's local memory.

## Leaving a machine

1. Run the tests: `QT_QPA_PLATFORM=offscreen pytest -q` (all pass at last check, see the State section).
2. Commit what is wanted and `git push`. Check with `git status` and `git log origin/main..` that nothing is left behind.
3. Measurements are git-ignored on purpose (`captures/`, `*.csv`, `*.sr`, `cal/*.json`). If a measurement should travel, copy it by hand, or for a small per-board file such as `cal/gain.json` use `git add -f cal/gain.json`.
4. Write down what is open in the State section below (and tick or note the bring-up boxes in `docs/bringup*.md`), so the next session starts from the page and not from a guess.

## Arriving on a machine

1. `git clone https://github.com/patrikeder/SAdiy.git`, or `git pull` in an existing clone. Check `git status` and `git log -3`.
2. Python 3.9 or newer (developed on 3.13). Setting up the environment installs software, so run it yourself, or let Claude Code ask you first (`CLAUDE.md`, Rules):
   ```bash
   python3 -m venv .venv && . .venv/bin/activate
   pip install -e .[dev,ui]
   ```
   On aarch64 (Raspberry Pi) or when the distribution packages are preferred, use the Debian packages and a venv that can see them: see the README quick start. On the BBB the daemon needs only numpy, pyzmq, spidev and i2c-tools (`deploy/bbb-setup.md`); the GUI runs on a PC.
3. `QT_QPA_PLATFORM=offscreen pytest -q`. GUI tests are skipped when PyQt5 or pyqtgraph are missing.
4. Start Claude Code in the repository root. It reads `CLAUDE.md` by itself. A good first message: "Read docs/handoff.md and the README status table, then continue with <task>."
5. To talk to the BBB from this PC: `python -m sadiy.ui.sa_gui --host <bbb-ip> --connect`. The BBB's address and user are not in the repository. The BBB keeps its own `/etc/sadiy/local.toml` (bus numbers and so on, example in `deploy/local.toml.example`). To put new code on it, rebuild the package on whichever PC has the change: `python tools/make_bbb_package.py`, then the update steps in `deploy/bbb-setup.md`. Packages in `dist/` are build outputs, never copy them between PCs.

The scripts and notes assume Linux. `.gitattributes` keeps the shell scripts and units on LF line endings, so a clone on another OS still works for editing and tests; the BBB side has not been tried from Windows or macOS.

## What is not in the repository

- **Claude Code's memory** (`~/.claude/projects/<folder>/memory/`) is per machine, and was empty. Durable facts and decisions belong in `CLAUDE.md` or `docs/`, not only in memory.
- **The design review and the claude.ai Project "DIY Spectrum analyzer"** are not in the repo; the facts that matter are summarised in `CLAUDE.md`. Open the Project on claude.ai from the same account if more is needed.
- **Git-ignored local files:** `.venv/`, `dist/`, `captures/`, `cal/*.json`, `*.csv`, `*.sr`, KiCad's local state (`*.kicad_prl`, backups), `.claude/settings.local.json`. Hardware, instruments, the BBB image and the board photos (`hw/photos`, which are tracked) are the only physical context; the bench itself is where it is.
- **No credentials** are needed or stored anywhere in the project.

## Optional: shared Claude Code permissions

No `.claude/settings.json` is committed. If the same prompts should be skipped or enforced on every PC, add one yourself (a session may not write its own permission settings). For example, to run tests and read-only git without asking, and to ask before any install, as `CLAUDE.md` requires:

```json
{
  "permissions": {
    "allow": ["Bash(pytest *)", "Bash(python -m pytest *)", "Bash(git status *)", "Bash(git diff *)", "Bash(git log *)"],
    "ask": ["Bash(pip install *)", "Bash(pip3 install *)", "Bash(apt *)", "Bash(sudo apt *)", "Bash(npm install *)"]
  }
}
```

## State at last handoff (2026-11-07)

Update this section at the end of every session. Details live in the README status table, `CLAUDE.md` ("Not done yet") and the bring-up plan, so this is only the pointer.

- **Tests:** 504 passed (Linux, Python 3.13, PyQt5 5.15, pyqtgraph 0.14, pyzmq 27).
- **Software:** the simulator, the GUI, bench mode, device logging, per-point lock gating and flags, and the optional image rejection are written and tested on a PC. **Nothing of the sweep path has run on a real BBB.** ADF4351 registers `R0..R5` are written but not checked against ADI's evaluation software; `build_hw_engine` (real SPI, GPIO, ADS1115 for the sweep) is not written.
- **Next on the bench:** `docs/bringup-2026-11-07.md` (SPI0, I2C2 and the ADS1115, ADF4351 lock, detector curve, PE4302 weights). Open parts: IF filter, IF amp, LPFs, LO pad (`hw/todo-parts.md`).
- **Next in code, after the bench:** `build_hw_engine`, the `registers()` check, replacing `settle_s` and the thresholds (`floor_dbm`, `max_dbm`, `outlier_db`) with measured values, and the time per point (`docs/architecture.md`, "Time per point and the PRUs").
