# zynq-ebaz

EBAZ4205 (Zynq 7010) port of the SAdiy spectrum analyzer: Linux software, FPGA RTL and the adapter PCB.

Start with `docs/ebaz4205-zynq-plan.md` (handover, work packages, ownership, repo layout in section 1b).

| Folder | Content | Written by |
|---|---|---|
| `sw/` | Linux side: `sadiy_ebaz` package, config, deploy, tools, tests | session L |
| `rtl/` | FPGA side: `src`, `sim`, `model`, `regmap` (session R), `vivado` (session L) | R and L |
| `hw/` | PCB files (adapter v2, KiCad) | user only |
| `docs/` | plan, handover-F*.md, STATUS-*.md, escalations, reports | R and L |
| `build/` | generated output, git-ignored | tools |

Subfolders are created by the session that owns them. The existing BBB code in `src/sadiy`, `config/`, `tools/`, `deploy/`, `docs/` and `hw/` is only touched through the three `seam:` commits listed in the plan.
