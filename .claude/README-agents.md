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

## Linux lane (session L), added 2026-11-15

Written from what worked in the Linux lane: platform selection, bench mode on the real board, image builds, deployment,
documentation sweeps. Worktree `/media/patrik/Workspaces/uC/SAdiy-linux` (branch `linux`).

| Agent | Use it for | Model |
|---|---|---|
| `linux-sw-maintainer` | sweepd, hal, drivers, bench mode, platform backends, `tools/bringup.py`, with tests | sonnet |
| `sbc-pinmap-keeper` | BBB / EBAZ pin maps, `platforms.py`, generated netlist and wiring figures | sonnet |
| `ebaz-image-builder` | PetaLinux rebuild (XSA, device tree, kernel fragment), SD card file list | sonnet |
| `target-deployer` | deploy to BBB or EBAZ, how to start server and GUI, "No module named sadiy" | sonnet |
| `gui-tester` | offscreen GUI tests, dry runs of `sweepd --sim`, Qt aborts in the full run | sonnet |
| `repo-docs-auditor` | repo-wide documents against code and hardware state (mechanical checks first) | sonnet |
| `ebaz-linux-bench` | Linux-side board checks: baseline, EMIO readback, LCD, LEDs, keys, top on the LCD, CE | sonnet |

The RTL-lane agents above work in the other worktree; the pairs `pinmap-keeper` / `sbc-pinmap-keeper` and `docs-auditor` /
`repo-docs-auditor` split the same job by lane.

Rules that hold for all of them (from `CLAUDE.md`): install nothing without asking, commit only when asked, the
RTL lane works in the worktree `/media/patrik/Workspaces/uC/SAdiy-rtl` (branch `rtl`), the Linux lane in `/media/patrik/Workspaces/uC/SAdiy-linux` (branch `linux`); session L owns
`zynq-ebaz/rtl/vivado`, `zynq-ebaz/sw/deploy` and its own documents. Report what was verified and what was not.

## Skills (`.claude/skills/<name>/SKILL.md`)

Routines that are invoked by name or picked by their description; they call the agents above where one fits.

| Skill | Lane | Use |
|---|---|---|
| `ebaz-session` | both | start / end a session |
| `rtl-check`, `fpga-bitstream`, `board-test` | R | RTL checks, bitstream and package, bench tests of the PL engine |
| `lane-commit-merge-push` | both | commit on the lane branch, `--no-ff` merge into main, push (only on request) |
| `run-tests` | L | pytest run (offscreen Qt), generated-file checks, reading failures |
| `start-and-deploy` | L | deploy to BBB / EBAZ, start `sweepd` and the GUI (single source `docs/how-to-start.md`) |
| `doc-sweep` | L | mechanical doc checks, then agent `repo-docs-auditor` |
