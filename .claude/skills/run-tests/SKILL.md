---
name: run-tests
description: Run the Python test suite of SAdiy (PC side, GUI offscreen, EBAZ software) and read a failure. Use before every commit, after changes to src/, tools/ or zynq-ebaz/sw, or when asked "do the tests pass?".
---

# Running the tests

Work in the lane's worktree (Linux lane: `/media/patrik/Workspaces/uC/SAdiy-linux`). The worktree has no `.venv`;
use the one of the main checkout and install nothing (PyQt5, pyqtgraph, pyzmq must already be there; if not, ask).

```
cd /media/patrik/Workspaces/uC/SAdiy-linux
PYTHONPATH=src QT_QPA_PLATFORM=offscreen /media/patrik/Workspaces/uC/SAdiy/.venv/bin/python -m pytest -q
```

`pyproject.toml` collects `tests/`, `zynq-ebaz/sw/tests/` and `zynq-ebaz/rtl/tests/`; the count is in `CLAUDE.md`
("N passed at last check"): update the number there when it changes. A quick run without GUI tests:
`-k "not gui"`; one file: `pytest -q tests/test_platforms.py`.

Also, when the matching files changed:
- `python tools/gen_diagrams.py` then `git status`: `hw/netlist.md` and `hw/diagrams/*` must show no change
  (keep regenerated SVGs only where the content changed).
- `zynq-ebaz/rtl/scripts/gen.sh --check` (register files, vectors current).

Reading a failure:
- **"Fatal Python error: Aborted" / "pure virtual method called"** in a GUI test: Qt object collected inside
  `processEvents`. `tests/conftest.py` runs `gc.collect()` after GUI tests; a new GUI test that creates windows
  must go through that fixture. Not a logic failure: rerun the file alone to see it.
- **Hangs or port errors**: leftover `sweepd --sim` processes. List with `pgrep -af sweepd`; kill only those whose
  config is `/tmp/sadiy-sim-*.toml` (the user may run a real one).
- **Skipped GUI tests**: the GUI dependencies are missing in the interpreter that was used.
- **test_gen_diagrams / test_platforms fail after a pin change**: regenerate (above), then compare with the
  expectation in the test: update the test only if the new pin map is intended.
- **ModuleNotFoundError: sadiy**: `PYTHONPATH=src` was left out.

Report with numbers: passed, skipped, failed, duration. Never "tests pass" without the line of pytest.
