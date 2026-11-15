---
name: ebaz-session
description: Start or end a working session on the EBAZ4205 (Zynq) part of SAdiy. Use at the beginning of a session ("where are we?", "continue the RTL / Linux lane") and before stopping ("wrap up", "hand over").
---

# Session routine for the EBAZ4205 lanes

Two lanes share the repo: **R** (RTL, worktree `/media/patrik/Workspaces/uC/SAdiy-rtl`, branch `rtl`, log
`zynq-ebaz/log_rtl.md`) and **L** (Linux, worktree `/media/patrik/Workspaces/uC/SAdiy-linux`, branch `linux`, log
`zynq-ebaz/log_linux.md`). `main` is where they meet. Find out which lane this session is before anything else
(ask the user if it is not clear from the request or the working directory).

## Start

1. `git status --short` and `git log --oneline -5` in the own worktree and in the main checkout
   (`/media/patrik/Workspaces/uC/SAdiy`). Uncommitted changes in the main checkout that are not yours mean
   another session is working there: do not touch those files, and wait with merges.
2. `git merge main` into the own branch when main is ahead and clean.
3. Read the top of both logs: the "State in one line" and the newest two entries. Entries marked "for L" / "for R"
   are requests to the other lane.
4. RTL lane: `zynq-ebaz/docs/rtl-spec.md` is the specification, `zynq-ebaz/docs/dsp-modules.md` the modules not
   yet integrated, `zynq-ebaz/docs/ebaz-pl-measurements.md` what has run on the board.
5. Tell the user in a few lines: what is committed and merged, what is only built or simulated, what has run on
   the board, and what the open decisions are.

## During the session

- Install nothing without asking. Commit only when asked. One Vivado build and one PetaLinux build at a time.
- Each lane edits only its own files (ownership table in `zynq-ebaz/docs/ebaz4205-zynq-plan.md` and in
  `.claude/README-agents.md`). A needed change in the other lane's file: make it small, test it, and write it
  into the own log under "for L" / "for R".
- Delegate to the project agents where they fit (`.claude/README-agents.md`).

## End

1. `zynq-ebaz/rtl/scripts/test.sh` (RTL lane) or `python -m pytest -q` (Linux lane) must pass.
2. Documents: use the `docs-auditor` agent, or check by hand that the state line of the own log, the handover
   files and the numbers in them match what is true now.
3. A dated log entry at the top: done, verified (how), not verified, open points for the user.
4. Commit and merge only if the user asked. Say plainly what is left uncommitted or unpushed.
