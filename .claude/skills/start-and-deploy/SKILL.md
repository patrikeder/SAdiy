---
name: start-and-deploy
description: Get SAdiy running - put the Python code on the EBAZ4205 or the BBB, start sweepd on the target and the GUI on the PC, or fix "No module named sadiy" on a target. Use when the user asks how to start, update or deploy.
---

# Start and deploy

The user-facing steps are in `docs/how-to-start.md`; keep that file the single source and update it when a step
changes. You cannot reach the boards: give commands, the user runs them and pastes output.

**PC only, no hardware**
```
. .venv/bin/activate
python -m sadiy.ui.sa_gui --sim                      # own simulator
python -m sadiy.server.sweepd --sim &                # or a separate server (tcp 5556 frames, 5557 commands)
python -m sadiy.ui.cli_client --count 5              # terminal client
```

**EBAZ4205** (user `petalinux`)
```
sh zynq-ebaz/sw/deploy/deploy_to_board.sh <ip>       # PC: copies src, zynq-ebaz/sw, tools/bringup.py, writes ~/sadiy/env.sh
ssh petalinux@<ip>
. ~/sadiy/env.sh                                     # PYTHONPATH; without it "No module named 'sadiy'"
sudo env PYTHONPATH=$PYTHONPATH python3 -m sadiy.server.sweepd --platform ebaz               # PL engine, root for /dev/mem
sudo env PYTHONPATH=$PYTHONPATH python3 -m sadiy.server.sweepd --platform ebaz --bench-only  # wiring tests, no sweeping
python3 -m sadiy.server.sweepd --platform ebaz --sim                                         # simulated chain
```
`sudo` drops PYTHONPATH, hence the `env`. `python tools/bringup.py ...` on the board works from `~/sadiy`
without PYTHONPATH (it adds its own paths). `deploy_to_board.sh` after every change of code the board runs;
a new boot image is a different thing (agent `ebaz-image-builder`).

**BBB**
```
python tools/make_bbb_package.py                     # PC: dist/ (git-ignored); rebuild after every change the BBB runs
# on the BBB: unpack, then
python -m sadiy.server.sweepd [--bench-only]         # --sim for the fake board
```

**GUI on the PC against a target**
```
python -m sadiy.ui.sa_gui --platform ebaz --host <ip> --connect       # or --platform bbb
```
`--platform` fixes the pin map shown on the Pins tab; without it the tab has a selector.

Checks before telling the user to run it: the code is deployed from the current branch (`git status`), the
tests pass (`run-tests`), and which parts are untested on hardware (say so; CLAUDE.md "Not done yet").
Messages: `-v` more, `-q` less; log history with `python -m sadiy.ui.cli_client --log-level warning`.
Port in use: an old `sweepd` is still running (`pgrep -af sweepd` on the target).
