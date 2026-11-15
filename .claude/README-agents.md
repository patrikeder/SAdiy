# Project agents

Subagent definitions for Claude Code (terminal and VS Code). A session in this workspace can delegate to them by
name ("use the rtl-verifier agent to ..."). They were written from what worked in the EBAZ4205 RTL lane
(session R, November 2026); each one carries the rules and commands of its job, so a session without that history
can use it.

| Agent | Use it for | Model |
|---|---|---|
| `rtl-maintainer` | changing the PL sweep engine (`zynq-ebaz/rtl/src`) according to `rtl-spec.md` | sonnet |
| `rtl-verifier` | writing or extending a testbench, checking it by deliberate faults | sonnet |
| `regmap-editor` | adding or changing a register (map, generated files, model, tests, docs) | sonnet |
| `dsp-module-builder` | a new standalone DSP module: Python reference first, then RTL, testbench, isolated build | opus |
| `fpga-build` | bitstream or out-of-context build, timing and utilisation report | haiku |
| `ebaz-platform-sw` | Python side of the engine: `sadiy_ebaz`, model, offload, sweepd backend | sonnet |
| `board-bringup` | package for the board, `pl_bringup.py`, reading its output, measurement log | sonnet |
| `pinmap-keeper` | constraints, PS7 settings check, pin map documents and figures | sonnet |
| `docs-auditor` | are the documents current? finds stale statements, fixes them | sonnet |

Rules that hold for all of them (from `CLAUDE.md`): install nothing without asking, commit only when asked, the
RTL lane works in the worktree `/media/patrik/Workspaces/uC/SAdiy-rtl` (branch `rtl`), session L owns
`zynq-ebaz/rtl/vivado`, `zynq-ebaz/sw/deploy` and its own documents. Report what was verified and what was not.
