---
name: doc-sweep
description: Check that the repo documents match the code and hardware state, and fix what is stale. Use before a handoff or commit, after a larger change, or when asked "do the docs match?" or for a doc sweep.
---

# Doc sweep

Scope: README, CLAUDE.md, `docs/`, `hw/` (not the generated files), `zynq-ebaz/docs`, deploy READMEs, logs. The
RTL lane's own files go through the agent `docs-auditor`; everything else through `repo-docs-auditor`.

1. Run the mechanical checks first (they are cheap and find most drift):
   - test count in `CLAUDE.md` vs. the pytest line (`run-tests`);
   - `python tools/gen_diagrams.py` and `git status`: generated files must not change;
   - option names in docs vs. `--help` of `sweepd`, `sa_gui`, `cli_client`, `tools/bringup.py`;
   - `grep -rn "not done\|untested\|TODO" CLAUDE.md docs zynq-ebaz/docs` against what has since been verified;
   - links to files that no longer exist: `grep -o '\](\([^)#]*\)' -r docs | ...` and check each path.
2. Hand the rest to the agent `repo-docs-auditor` (Agent tool), with the list of what changed since the last
   sweep (`git log --oneline <last sweep>..`) so it reads the right places.
3. Rules that stay true while fixing: statements about hardware are marked "verified" or "untested on the board"
   only from what the user reported; no RPi support is added or removed; generated files are never hand-edited;
   a decision lives in `CLAUDE.md` or `docs/`, not only in memory.
4. Report: what was wrong (file, old claim, new claim), what was left because it needs a decision of the user.
   Update "State at last handoff" in `docs/handoff.md` and the state line of the lane's log. Commit only on request
   (`lane-commit-merge-push`).
