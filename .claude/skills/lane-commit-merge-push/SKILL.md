---
name: lane-commit-merge-push
description: Commit the work of a lane (L or R) on its own branch, merge it into main and push. Use only when the user says "commit", "merge to main" or "push" (or all three). Never on your own initiative.
---

# Commit, merge, push (two worktrees)

| Lane | Worktree | Branch |
|---|---|---|
| L (Linux) | `/media/patrik/Workspaces/uC/SAdiy-linux` | `linux` |
| R (RTL) | `/media/patrik/Workspaces/uC/SAdiy-rtl` | `rtl` |
| meeting point | `/media/patrik/Workspaces/uC/SAdiy` | `main` (only merges, no edits) |

Do each step only for what was asked: "commit" = steps 1 to 3, "merge to main" adds 4 to 5, "push" adds 6.

1. **Where am I.** `git branch --show-current` in the lane worktree: it must be the lane's branch. Edits belong
   there, never in the main checkout.
2. **Bring the branch up to date.** `git merge main` (main may hold the other lane's merges and files that exist
   only there, e.g. `.claude/`). Resolve conflicts in the own files only; ask for the other lane's files.
3. **Test, then commit.** Run the `run-tests` skill (RTL lane: `rtl-check`). Look at `git status --short` and
   `git diff --stat`: stage by name, not `git add -A` (after a `git reset <dir>` that silently drops files).
   Generated files (`hw/netlist.md`, diagrams, `regs_*`) only together with their source. Message: short subject,
   a paragraph on what and why, then the attribution line of the session:
   `Co-Authored-By: Claude Sonnet 5.5 <noreply@anthropic.com>` (use the model of the running session).
   Edits outside `zynq-ebaz/` get a `seam:` subject prefix (rule in `zynq-ebaz/docs/ebaz4205-zynq-plan.md`).
4. **Look at main before merging.** In `/media/patrik/Workspaces/uC/SAdiy`: `git status --short`. Files staged or
   modified there are someone else's work: do not discard them. A staged file that the merge would overwrite:
   `git restore --staged <file>` (the file stays on disk); an untracked file with the same name: ask.
   Main must be on branch `main`.
5. **Merge.** `git merge --no-ff linux -m "Merge branch 'linux': <what>"` (same with `rtl`). Then
   `git log --oneline -3` and `git status -sb`.
6. **Push** (only when asked): `git push` from the main checkout. Then bring the lane up:
   `git -C <lane worktree> merge --ff-only main`.

Never force-push, never rewrite pushed commits, never `--no-verify`. Say at the end what is committed, merged and
pushed, and what is left uncommitted in either worktree. The "State at last handoff" part of `docs/handoff.md`
is updated before the commit when the session ends (skill `ebaz-session`).
