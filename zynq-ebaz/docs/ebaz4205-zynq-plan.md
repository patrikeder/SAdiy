# EBAZ4205 port: handover to the executing project (v2)

Written 2026-11-14, replaces the 2026-11-13 plan. Audience: the Claude Code project that owns the SAdiy repo (`/media/patrik/Workspaces/uC/SAdiy`). Read this file first, then `repo-status.md` and `chain-review-supplies-sw-plan.md`. Where the repo has moved on since those notes (dated 2026-11-01), the repo is the source of truth. Items marked (verify) come from web research or general knowledge, not from a schematic or datasheet check.

## 0. Status and ground rules
Stated by the user on 2026-11-14:
- ADF4351 is known working. PE4302, detector and the rest of the chain are being proven on the existing PCBs.
- The GUI runs on a PC or a Raspberry Pi, not on the controller. `sweepd` runs on the controller and publishes over Ethernet (ZeroMQ).
- The EBAZ4205 is up with a PetaLinux base already and boots from the SD card (TF), so the boot resistor and TF socket are done.
- Decided 2026-11-14: Phase 1 uses EMIO (not AXI IP).
- The BBB is the validation vehicle until the chain is proven, then the EBAZ replaces it. Do not maintain both long term: freeze the BBB path once parity is shown (same discipline as the RPi removal on 2026-11-01).
- Work to do: (a) port the BBB software, (b) generate the FPGA RTL.

Ground rules:
- No software installs without the user's consent (host or target rootfs). List what is needed and ask.
- KiCad files are hand-maintained; never run the old `gen_schematic.py` / `place_connectors.py` / `align_components.py` over them.
- PL only transports words. All ADF4351 register packing stays in Python (`drivers/adf4351.py`, single source of truth). The PL must never invent register contents, and RF outputs stay off until software enables them after lock (existing `safe_state` rule).
- Hardware actions (soldering, wiring, powering) are the user's. Never instruct power-up of a changed board without a checklist.

## 1. Model budget: who does what
Two tiers. The expensive model (Fable, limited quota) is spent only on design decisions, RTL, numerics and hard debugging, and must leave behind artifacts that make the rest mechanical. Everything else (interface adaptation, scripts, bring-up, test exercises) goes to a cost-effective model (Sonnet; Haiku where marked H).

Rules to save tokens:
- A Fable session starts from this file plus only the files named in its package. It does not re-read all project docs or the whole repo.
- Fable deliverables are self-contained: code, tests, and a one-page `zynq-ebaz/docs/handover-F<n>.md` listing what the S tier must do next and how to verify it. S packages must not need design decisions.
- S tier does not edit F-owned files (`zynq-ebaz/rtl/regmap/regmap.toml`, `zynq-ebaz/rtl/src/**`, `zynq-ebaz/rtl/model/**`, the interface contracts from F1). If one is wrong, write `zynq-ebaz/docs/escalations/NNN.md` with the template below and stop that package.
- Use the fake backend, the Python reference model and xsim wherever possible. Hardware loops are S/H work with small logs (quote at most about 100 lines).
- Suggested Fable budget split (my suggestion): F1 15 %, F2 40 %, F3 25 %, F4 escalation reserve 20 %.

Escalation template (S to F4): symptom; exact repro command; tool/kernel/Vivado versions; log excerpt (at most 100 lines); what was tried; two hypotheses; files touched.

## 1b. Repo layout: everything new lives under `zynq-ebaz/` (decided 2026-11-14)
```
zynq-ebaz/
  sw/                  Linux side (Python, systemd/init, tools)
    sadiy_ebaz/        Python package: platform contract, ebaz-ps / ebaz-pl backends, PL model
    config/            EBAZ config files (device names, EMIO lines, UIO path)
    deploy/            sweepd unit/init script, README for the PetaLinux steps, DT snippets
    tools/             ebaz_baseline.sh, parity.py, EBAZ bring-up helpers
    tests/             contract tests (contract/), backend tests
  rtl/                 FPGA side
    src/               SystemVerilog sources (sadiy_top.sv, sweep engine, later Stage B)
    sim/               xsim testbenches, gen_vectors.py, vectors/
    model/             bit-accurate Python reference models (Stage B)
    regmap/            regmap.toml, gen_regs.py, generated regs.h / regs.py / regmap.md
    vivado/            pins.toml, gen_xdc.py, constraints/, phase1.tcl, build.tcl, block design
  hw/                  PCB files (adapter v2, KiCad). Hand-maintained by the user; no session edits these
  docs/                this plan, handover-F*.md, STATUS-*.md, escalations/, ebaz-*.md reports
  build/               generated output of Vivado/xsim/PetaLinux helpers (git-ignored)
```
Rules:
- All new sources, scripts, tests, docs and PCB files go under `zynq-ebaz/`. The existing `src/sadiy`, `config/`, `tools/`, `deploy/`, `docs/` and `hw/` of the repo stay as they are (BBB path, frozen after parity).
- The EBAZ backends are a separate Python package `sadiy_ebaz` (under `zynq-ebaz/sw/`) that plugs into `sadiy`; it is not added to `src/sadiy/hal/`. Make it importable via the pytest `pythonpath` setting and `PYTHONPATH` for runs (no pip install without consent).
- The only edits allowed outside `zynq-ebaz/` ("seams"), each in its own commit with the message prefix `seam:`:
  1. F1: a plugin hook in the platform/engine builder (`[platform] name = "bbb" | "ebaz-ps" | "ebaz-pl"`, unknown names resolve to `sadiy_ebaz.platforms.<name>`), the optional offload call in `core/sweep.py`, and the pytest/`.gitignore` entries (`zynq-ebaz/build/`).
  2. S13: `server/protocol.py` and `ui/sa_core.py` extensions (RBW, frame metadata).
  3. S14: documentation updates in the existing `repo-status.md`, `docs/bring-up.md`, `hw/` wiring pages.
- `zynq-ebaz/hw/` holds only the user's KiCad work. `zynq-ebaz/rtl/vivado/pins.toml` is the master pin list; the PCB must match it or the change is made in `pins.toml` first and announced in `STATUS-linux.md`.

## 1a. Two parallel sessions (decided 2026-11-14)
Session R (RTL, Fable) and session L (Linux, Sonnet). Linux work is less complex, so L takes all S packages (it may hand H packages to Haiku subagents); R takes only F packages: F1 -> F2 -> F3, F4 on demand. Work in two git branches (`rtl`, `linux`), merged to main by the user; each session pulls main at start.

| | Session R | Session L |
|---|---|---|
| Model | Fable | Sonnet (Haiku for H) |
| Packages | F1, F2, F3, F4 | S1 to S14 |
| Owns (writes) | `zynq-ebaz/rtl/src/**`, `zynq-ebaz/rtl/sim/**`, `zynq-ebaz/rtl/model/**`, `zynq-ebaz/rtl/regmap/regmap.toml`, `zynq-ebaz/rtl/regmap/gen_regs.py`, `zynq-ebaz/rtl/sim/gen_vectors.py`, `zynq-ebaz/sw/sadiy_ebaz/platform.py`, `zynq-ebaz/sw/sadiy_ebaz/ebaz_pl_model.py`, `zynq-ebaz/sw/tests/contract/**`, `zynq-ebaz/rtl/regmap/**` (incl. generated files), `zynq-ebaz/docs/handover-F*.md`, `zynq-ebaz/docs/STATUS-rtl.md`, seam 1 (F1) | `zynq-ebaz/rtl/vivado/**` (pins.toml, constraints, Tcl, block design, build flow), the rest of `zynq-ebaz/sw/**` (backends, `config/`, `deploy/`, `tools/`, other tests), `zynq-ebaz/docs/ebaz-*.md`, `zynq-ebaz/docs/STATUS-linux.md`, `zynq-ebaz/docs/escalations/*`, seams 2 and 3 (S13, S14) |
| Reads only | `zynq-ebaz/rtl/vivado/pins.toml`, escalations | `zynq-ebaz/rtl/src/**`, `zynq-ebaz/rtl/regmap/**`, handover files |
| Nobody (user only) | `zynq-ebaz/hw/**` | `zynq-ebaz/hw/**` |

Shared existing files (`core/sweep.py`, the platform builder, `.gitignore`): only F1 touches them (seam 1) and merges to main first. EBAZ-specific config values live in `zynq-ebaz/sw/config/` and are owned by L; R never edits them.

Contract between the lanes (frozen now, changes only via a note in a STATUS file):
- Signal names (appendix D): `adf4351_clk/dat/le/ce/ld`, `pe4302_v[5:0]`, `det_spi_*`, `adc_d[11:0]`, `adc_otr`, `adc_clk`. L uses them in `pins.toml`/XDC and the Phase 1 EMIO wiring.
- `sadiy_top.sv` (R) has: `clk` (FCLK0, 100 MHz), `resetn`, an AXI-lite slave `s_axil_*` (32 bit), `irq`, EMIO-side inputs for the `pin_mux` (`emio_adf_*`, `emio_pe_v`), and the physical pins as outputs. In Phase 1 L wires EMIO straight to the pins; from Phase 2 L inserts `sadiy_top` in between.
- The AXI base address is assigned by L in the Vivado address editor and reaches Python through the UIO/device tree; R never hard-codes it.

Sync points:
- P0 (now): signal names and `sadiy_top` ports as above.
- P1: F1 merged to main -> L starts S5, S7, S13. Before that L does S1 to S4, which change no repo code (scripts, docs, boot image only).
- P2: `zynq-ebaz/docs/handover-F2.md` -> L does S8, S9, S10.
- P3: `zynq-ebaz/docs/handover-F3.md` -> L does S11, S12 (needs adapter v2).
Mailboxes: each session ends by updating its own `zynq-ebaz/docs/STATUS-*.md` (at most 30 lines: done, next, blockers, questions to the other lane). L writes `zynq-ebaz/docs/escalations/NNN.md` for R. Neither session reads the other's code beyond the contracts. Linux-specific trouble (boot image, device tree, kernel quirks): L tries twice, then escalates; a short one-off Fable session is cheaper than letting L loop.

Worktree setup (both sessions run on the same machine: 24 cores, 64 GB RAM, one Vivado/PetaLinux installation):
1. Commit this file as `zynq-ebaz/docs/ebaz4205-zynq-plan.md` on main first, so both worktrees contain it.
2. Create the worktrees (user does this once):
   `cd /media/patrik/Workspaces/uC/SAdiy && git worktree add ../SAdiy-rtl -b rtl && git worktree add ../SAdiy-linux -b linux`
   Session R runs only in `../SAdiy-rtl`, session L only in `../SAdiy-linux`. The main checkout stays on main and is where the user merges. A session never switches branch and never edits the other worktree.
3. Build output stays inside the session's own worktree: `zynq-ebaz/build/` (Vivado, xsim, generated files that are not committed). `zynq-ebaz/build/` is in `.gitignore` (seam 1). Generated files that are committed (`regs.h`, `regs.py`, `regmap.md`, golden vectors) are produced by the owning lane and committed on its branch.
4. The existing PetaLinux project stays outside the repo at the path the user names; only session L touches it. Never run two PetaLinux builds at once, and no other session writes to that directory.
5. Resource rules (machine is large, but be explicit): each Vivado/xsim run uses at most 8 threads (`set_param general.maxThreads 8`, `-jobs 8`); one synthesis/implementation run per session at a time. One Vivado run per lane in parallel is fine. Tool installs are never done by a session (ground rules in section 0).
6. Sync: `git merge rtl` in the main checkout after F1/F2/F3, then `git merge main` inside `../SAdiy-linux` (and the same in the other direction after L merges to main). Each session starts with `git merge main` and ends with a commit plus an updated `zynq-ebaz/docs/STATUS-*.md`.
7. Both worktrees share one `.git`; do not run `git gc --prune=now`, `git worktree prune` or branch deletion without the user.

Kickoff prompts (copy-paste into each session; start the session in its worktree directory):
- R: "Read zynq-ebaz/docs/ebaz4205-zynq-plan.md (sections 0, 1, 1a, 1b, 3, 4 and appendices A, B, D). You are session R (RTL), working only in ../SAdiy-rtl on branch rtl (see the worktree setup in 1a). Do F1 now, write zynq-ebaz/docs/handover-F1.md and zynq-ebaz/docs/STATUS-rtl.md, then stop and report. Do not touch lane L files. Do not ask what the plan already answers."
- L: "Read zynq-ebaz/docs/ebaz4205-zynq-plan.md (sections 0, 1, 1a, 1b, 3, 5 and appendices A, D). You are session L (Linux), working only in ../SAdiy-linux on branch linux (see the worktree setup in 1a). Do S1 to S4 in order; S4 needs me at the bench, so stop and tell me exactly what to measure. S5, S7, S13 only after F1 is merged to main. Install nothing without my consent. Do not touch lane R files. Escalate with the template in section 1."

## 2. Work packages (complex first)
Tier F (Fable):

| ID | Title | Depends | Output |
|---|---|---|---|
| F1 | Spec freeze and interface contracts | none | `zynq-ebaz/rtl/regmap/regmap.toml`, sweep table format, Python `Platform` contracts + contract tests, protocol additions, golden-vector format |
| F2 | RTL: PL sweep engine | F1 | `zynq-ebaz/rtl/src/*`, register-file generator, xsim self-checking testbenches fed by Python golden vectors |
| F3 | Stage B numerics and architecture (IF digitizer) | F1 | bit-accurate Python reference model, word lengths, decimation/RBW table, IP configuration spec, clocking plan, test vectors |
| F4 | Escalation reserve | on demand | fixes for timing closure, sim/HW mismatch, hangs, coherency, analog surprises |

Tier S (Sonnet; H = Haiku is enough):

| ID | Title | Depends | Model |
|---|---|---|---|
| S1 | Board baseline capture script and report | none | H |
| S2 | `pins.toml` + `gen_xdc.py` | none | H |
| S3 | Phase 1 Vivado Tcl (PS7 + EMIO) and boot image | S2 | S |
| S4 | Linux device bring-up and electrical checks | S3 | S |
| S5 | `ebaz-ps` platform backend, ADS1115 driver, deploy unit | S4 | S |
| S6 | Parity tool and doc updates | S5 | H |
| S7 | `ebaz-pl` Python backend (UIO regs, table upload, offload run) | F1 | S |
| S8 | Vivado build flow for the F2 RTL, runtime bitstream load, UIO device tree | F2 | S |
| S9 | HIL tests for the PL engine (timing, jitter, parity) | F2, S7, S8 | S |
| S10 | Detector ADC reader in PL (SPI SAR ADC) | F2 | S |
| S11 | AD9226 capture bring-up (raw capture, ENOB check) | F3, adapter v2 | S |
| S12 | Stage B integration per the F3 spec, regression vs reference model | F3, S11 | S |
| S13 | Protocol/GUI extensions (RBW setting, frame fields) | F1 | S |
| S14 | Repo hygiene: repo-status, bring-up docs, remove BBB-as-GUI-host text | any | H |

Human tasks (user): U1 adapter PCB v2 (section 8); U2 check AD9226 module DRVDD = 3.3 V and fit an adapter for the 2.0 mm DATA headers; U3 (done: SD boot works; make sure the UART J7 is fitted for console access); U4 wiring and power-up with measurement.

Single-session run order (with two sessions, section 1a applies): F1 -> (S1, S2 in parallel) -> (S3 -> S4 -> S5 -> S6 while F2 runs) -> S7, S8 -> S9 and S10 -> F3 -> S13 -> S11 -> S12. F4 only on escalation. Phase 1 (S1 to S6) needs no Fable at all and already gives a working EBAZ system at BBB parity; it can start immediately.

## 3. Architecture decisions (fixed here so S packages do not reopen them)
Staged, PS first, PL later:
- **Phase 1 (S3 to S6): no custom RTL.** The PS7 routes its SPI, I2C and GPIO controllers through EMIO to PL pins on DATA2. The existing Python code (spidev, libgpiod, ADS1115 over i2c-dev) then runs unchanged apart from device names and the config. Reason: fastest path to parity, nothing new to debug in logic.
  - Enabling EMIO changes the PS7 configuration, so the FSBL/ps7_init, `BOOT.BIN` and device tree must be rebuilt once. Reuse the PS7 settings (DDR, clocks, MIO) from the existing working Vivado/PetaLinux project; do not re-derive DDR settings. After that, PL-only changes can load at runtime via fpga_manager (verify on this image).
  - **Decided: EMIO.** Since the board boots from SD, the rebuild is low risk: keep the current SD card as the known-good fallback, build the new `BOOT.BIN` + image on a second card (or a second partition set), no NAND flashing involved.
  - Do all PS7 changes in this one rebuild so later PL work needs no boot-image change: EMIO SPI/I2C/GPIO, FCLK0 (100 MHz), M_AXI_GP0 (for the Phase 2 AXI-lite engine), IRQ_F2P (done interrupt). Also check that the PL clock and AXI GP0 are enabled in the Linux device tree. After that, Phase 2 to 4 bitstreams load at runtime via fpga_manager (verify on this image).
  - Rejected alternative (kept for the record): AXI Quad SPI, AXI GPIO and AXI IIC IP. It would be throwaway work once the Phase 2 engine exists.
  - PS SPI through EMIO has a lower clock limit than MIO (verify in the Zynq data sheet). The ADF4351 needs 20 MHz or less, so 10 MHz SCLK is fine either way.
- **Phase 2 (F2, S7 to S9): PL sweep engine** behind an AXI-lite register interface (map in appendix A). A `pin_owner` bit selects who drives the ADF4351 SPI/LE/CE and PE4302 pins: 0 = PS EMIO (Phase 1 software keeps working, useful for debug), 1 = engine. Switching is only allowed when idle.
- **Phase 3 (S10): detector ADC read in the PL** (SPI SAR ADC, 16 bit, 100 kSPS or more, 3.3 V; candidates to verify: ADS8860, AD7685, MCP33131 class). Until then ADS1115 (860 SPS) over I2C.
- **Phase 4 (F3, S11, S12): AD9226 IF digitizer** with DDC, digital RBW and FFT (sections 6 and 7, appendix C).
- Stage A data volume is small (a trace is 4096 points x 32 bit per sweep). No DMA is needed until Phase 4; results are read through an AXI-lite window mapped with UIO. Add AXI DMA only for raw capture or waterfall data.
- Scheduling: `sweepd` on the PS, GUI and clients on PC/RPi over the 100 Mbit link. Only decimated traces cross the network (raw AD9226 data is about 1 Gbit/s).

## 4. Tier F packages (detail)
### F1 Spec freeze and interface contracts
Goal: make every later package mechanical.
Inputs: this file (appendices A and B are drafts to review, not to invent from scratch), `src/sadiy/{hal,drivers,core,server}` (read only apart from seam 1), `config/default.toml` (read only).
Deliverables:
1. `zynq-ebaz/rtl/regmap/regmap.toml` frozen (schema: name, offset, access, reset, fields with bit ranges, doc). The register-file RTL, `regs.h`, `regs.py` and `regmap.md` are generated from it by `zynq-ebaz/rtl/regmap/gen_regs.py` (stdlib only; `tomllib` needs Python 3.11 or newer, verify the repo and target versions).
2. Sweep table entry and result formats frozen (appendix B).
3. Python contracts in `zynq-ebaz/sw/sadiy_ebaz/platform.py`: a `Platform` protocol (`synth_link`, `atten_port`, `detector`, `capabilities`) and an optional `SweepOffload` capability (`upload(plan)`, `run(n_avg) -> counts`, `abort()`, `status()`). `core/sweep.py` uses offload when `capabilities.sweep_offload` is true, otherwise the existing per-point loop. Config: `[platform] name = "bbb" | "ebaz-ps" | "ebaz-pl"`, with the per-platform values (device names, EMIO lines, UIO path) in `zynq-ebaz/sw/config/` instead of editing the BBB `default.toml`. The `Platform` contract and the PL model live in `zynq-ebaz/sw/sadiy_ebaz/`; only the plugin hook and the offload call are seam edits in the existing code (section 1b).
4. Contract tests (pytest, in `zynq-ebaz/sw/tests/contract/`) that every backend must pass, including the fake backend and a Python model of the PL engine (`zynq-ebaz/sw/sadiy_ebaz/ebaz_pl_model.py`) that mimics register behaviour. These fail until S5/S7 implement the backends.
5. `zynq-ebaz/rtl/sim/gen_vectors.py`: writes golden vectors to `zynq-ebaz/rtl/sim/vectors/` (R0 words and expected SPI bit streams for sample sweeps from `freqplan`, PE4302 transition tables from the existing 64 x 64 test, expected sums for a synthetic detector sequence).
6. Protocol additions for S13 (RBW as a read-only/enum field first; frame metadata: ADC source, n_avg, lock errors).
7. `zynq-ebaz/docs/handover-F1.md`.
Acceptance: contract tests exist and run (fail only where a backend is missing); `gen_regs.py` output is committed and reproducible; a reviewer can write S7 without asking questions.

### F2 RTL: PL sweep engine
Inputs: F1 outputs, appendices A, B and D, the golden vectors.
Deliverables (`zynq-ebaz/rtl/src/`, SystemVerilog, no vendor IP in the engine):
- `adf4351_spi.sv`: 32-bit MSB-first writer, mode 0, LE = chip select, programmable divider (reset 10 MHz at a 100 MHz fabric clock).
- `pe4302_mbb.sv`: make-before-break application. Stages turning on first (new OR old), then the final value, with a programmable gap. Must match `drivers/pe4302.py` ordering for all 64 x 64 transitions (check against the vectors).
- `sweep_seq.sv`: FSM per appendix B (load entry, apply attenuation, optional shadow-register resend, write R0, minimum wait, lock wait with stable window and timeout, detector settle, sample accumulate, store). Abort and watchdog. Never leaves RF outputs enabled by itself.
- `det_sampler.sv`: interface block that accepts an ADC sample stream (valid/data); in Phase 2 fed by a placeholder (a PS-writable test sum), S10 plugs in the SPI ADC reader.
- `pin_mux.sv` (pin_owner), `axil_regs.sv` (generated), table and result BRAM (default 2048 entries x 64 bit = about 4 BRAM36 and 2048 x 32 bit = about 2 BRAM36, depth is a parameter, verify mapping).
- `sadiy_top.sv` and xsim self-checking testbenches: adf4351 stream, mbb vs vectors, full sweep with a behavioural ADF4351 lock model including timeout and missing-lock cases, abort mid-sweep, register access.
Acceptance: all testbenches pass in xsim (Vivado simulator, part of the user's toolchain, verify); SPI bit streams and PE4302 sequences are bit-identical to the Python vectors; a resource estimate from synthesis is recorded (expect well under 10 % LUT, verify); `zynq-ebaz/docs/handover-F2.md` tells S8 how to build and S9 what to measure.

### F3 Stage B numerics and architecture
Do this before any Stage B hardware exists; it is pure software.
Deliverables:
- `zynq-ebaz/rtl/model/` bit-accurate Python (stdlib plus numpy if the user consents; otherwise pure Python at small sizes) reference of: NCO and complex mixer, variable CIC, compensation/RBW FIR sets, power detect and log, windowed FFT, power-domain averaging.
- Decisions with numbers: ADC sample rate and its relation to the 10.7 MHz IF (keep clock harmonics out of the IF band), word lengths per stage, decimation plan, RBW table (about 1 kHz to 300 kHz), FFT size and overlap, stitching rule for LO steps, noise-bandwidth correction factors, overload handling using the OTR bit.
- Xilinx IP choices and exact configuration (FIR Compiler, CIC Compiler, DDS Compiler, FFT, as appropriate), plus a Tcl spec for S12.
- Clocking plan: MMCM from FCLK, ADC clock output via ODDR, whether the ADF4351 reference can be driven from the same MMCM (the board's MCLK is an input per the repo notes, verify) or stays on its own 25 MHz oscillator (then the DDC just measures the small frequency offset).
- Resource budget against the 7010 (appendix C) with BRAM as the binding constraint.
- Test vectors for S11/S12 (tones at known offsets, noise, overload).
Acceptance: the model reproduces a synthetic scene (two tones, a spur, noise floor) with correct amplitude after RBW/ENBW correction; documented error budget; `zynq-ebaz/docs/handover-F3.md`.

### F4 Escalation reserve
Triggers: timing closure fails after S-tier attempts (report slack and critical path); xsim and hardware disagree; PL or PS hangs; cache coherency or UIO/DMA issues; spurs or dynamic-range puzzles that need analysis. Input: the escalation template in section 1.

## 5. Tier S packages (detail)
S1 (H) Board baseline: `zynq-ebaz/sw/tools/ebaz_baseline.sh` that runs on the EBAZ and prints kernel version, `python3 --version`, `python3 -c "import zmq, numpy"`, presence of `spidev`, `gpiod`, `i2c-tools`, `devmem`, memory, IP address, `/sys/class/fpga_manager`, boot media. Output to `zynq-ebaz/docs/ebaz-baseline.md`. Acceptance: file committed. If Python modules are missing, list the PetaLinux rootfs packages needed and ask for consent (do not install).

S2 (H) `zynq-ebaz/rtl/vivado/pins.toml` + `zynq-ebaz/rtl/vivado/gen_xdc.py` (stdlib): one table of signal -> DATA connector pin -> ball -> IO standard (LVCMOS33). Generates `zynq-ebaz/rtl/vivado/constraints/ebaz4205.xdc`. Start from appendix D, check names against the schematic before committing (series resistors, any pin shared with other functions). Acceptance: XDC reproducible, schematic check noted in the file header.

S3 (S) Phase 1 Vivado: Tcl (`zynq-ebaz/rtl/vivado/phase1.tcl`) that builds PS7 (settings from the existing project) with EMIO SPI, I2C and GPIO (width 16) routed to the pins in `pins.toml`, plus FCLK0 = 100 MHz, M_AXI_GP0 (unused for now, with a minimal AXI-lite block or none) and IRQ_F2P enabled for Phase 2; exports the XSA; then the PetaLinux steps (`petalinux-config --get-hw-description`, `petalinux-build`, `petalinux-package`) documented in `zynq-ebaz/sw/deploy/README.md`; device-tree additions in `system-user.dtsi`: spidev child node (compatible string depends on the kernel version, verify), i2c-dev, gpio. Use the user's existing PetaLinux project path (ask). Acceptance: new boot image boots; `/dev/spidevX.Y`, `/dev/i2c-N` and the EMIO gpio lines are present. Back up the SD card (image copy) first; write the new boot files only to a second card or after the user confirms.

S4 (S) Bring-up and electrical checks (with the user at the bench): EMIO GPIO line numbering (EMIO line n is expected at 54 + n on the Zynq gpiochip, verify); `tools/bringup.py pe4302-walk` with the mapped lines (detector rises by weight x 24.5 mV); DSLogic decode of the SPI frames with `adf4351-pattern`; ADF4351 at 100 MHz on the MSO5354; ADS1115 at its I2C address. Acceptance: results in `zynq-ebaz/docs/ebaz-bringup.md`.

S5 (S) `ebaz-ps` backend in `zynq-ebaz/sw/sadiy_ebaz/` (config in `zynq-ebaz/sw/config/`, no edits to the BBB `default.toml`): device names, `build_hw_engine` for the EBAZ (SPI, GPIO via libgpiod, ADS1115 driver, enable outputs only after lock), `zynq-ebaz/sw/deploy/sweepd.service` (or the init-script format this PetaLinux uses, verify). Acceptance: `sweepd` on the EBAZ passes the contract tests on hardware; the GUI on PC/RPi with `--host <ebaz-ip> --connect` shows a live sweep.

S6 (H) `zynq-ebaz/sw/tools/parity.py`: compares an EBAZ trace to a stored BBB trace of the same tone (frequency and level within +/-0.5 dB after calibration). Update docs: GUI host is PC/RPi, BBB frozen after parity. Acceptance: parity report committed.

S7 (S) `ebaz-pl` backend in `zynq-ebaz/sw/sadiy_ebaz/` implementing the F1 contracts: UIO mmap register access (stdlib `mmap`), table upload, offloaded sweep run, readback, `pin_owner` handling, interrupt or polling for done. Tested against the F1 model, then on hardware after S8.

S8 (S) Build flow: `zynq-ebaz/rtl/vivado/build.tcl` (non-project batch flow for repeatability), report parsing (utilization, WNS), bitstream to `.bit.bin`, runtime load via fpga_manager with a device-tree overlay creating the UIO node (verify on this image), `make -C zynq-ebaz/rtl bitstream` wrapper. Acceptance: reproducible bitstream with timing met at 100 MHz fabric clock unless F2 states otherwise.

S9 (S) HIL tests: sweep time per point and jitter measured with the DSLogic; sweep result parity with S5 within +/-0.5 dB; lock-timeout behaviour with the synth disconnected; abort. Acceptance: `zynq-ebaz/docs/ebaz-pl-measurements.md`.

S10 (S) SPI ADC reader RTL (small; spec in the F2 handover) and ADC-on-adapter bring-up; compare against ADS1115 readings.

S11 (S) AD9226 bring-up: 12-bit parallel capture into BRAM at the F3 sample rate, scope-checked tone, ENOB/SNR measurement against the F3 expectations, OTR check. Needs adapter v2 and the DRVDD = 3.3 V check.

S12 (S) Stage B integration following the F3 Tcl spec; regression: RTL output vs reference model on the F3 vectors; utilization and timing reports; escalate to F4 on failures.

S13 (S) Protocol and GUI (seam 2, commit prefix `seam:`): extend `server/protocol.py` and `ui/sa_core.py` as defined in F1 (RBW selection, frame metadata). Tests via the simulator.

S14 (H) Hygiene (seam 3, commit prefix `seam:`): update `repo-status.md`, `docs/bring-up.md`, `hw/` wiring pages for the EBAZ, remove BBB-as-GUI-host wording.

## 6. DSP roadmap (what the engine and Stage B should enable)
Stage A (existing log detector): PL-timed sweep; oversampling and power-domain averaging (dB averaging biases noise by about 2.5 dB); calibration (piecewise detector linearization, flatness, temperature); detector modes (sample, peak, RMS, negative peak; quasi-peak only if CISPR-calibrated); channel power, occupied bandwidth, noise-density marker; limit lines with transducer factors; overload detection; image rejection by two passes (LO = RF + 10.7 MHz and RF - 10.7 MHz, take the minimum) and the same idea for LO-harmonic responses with two or three different IF values.
Stage B (AD9226 on the 10.7 MHz IF): NCO + complex mixer, CIC and FIR chain, digital RBW about 1 kHz to 300 kHz, power detect and log, windowed FFT of a 1 to 2 MHz window per LO step, parabolic peak interpolation, zero span with trigger, waterfall/persistence, AM/FM/SSB demodulation, signal detection. Limits: scalar only (one ADC channel, no reference path), phase noise floor set by the ADF4351.
Most trace maths (hold, IIR, markers, limit lines, channel power, demodulation) belongs on the PS to save BRAM.

## 7. Board facts, unknowns, resources
Confirmed by at least one source: XC7Z010-CLG400, dual Cortex-A9 at 666.66 MHz, 256 MB DDR3, 128 MB SLC NAND, IP101GA 10/100 Ethernet, no USB. Boot via resistors R2584 (NAND) / R2577 (TF). TF socket, UART J7, JTAG J8 and diode D24 are unpopulated by default. Power in via DATA1/2/3 pins 1 and 2 (5 to 12 V, at least 400 mA) or J3/J4/J5 with D24 fitted. PL banks 34 and 35 are 3.3 V (LVCMOS33); 5 V on a pin misbehaved for one user. External XADC pins are reportedly not exposed (verify); only internal sensors.
DATA1/2/3: 2.0 mm, 2x10 each; pins 1-2 supply (up to 12 V, never wire to peripherals), 3-4 and 12 GND, 10 NC, 14 usable I/O each = 42 PL I/Os (bank 35: 30, bank 34: 12). Complete P/N pairs by name: 14 in bank 35, 3 in bank 34.
To measure or verify at S1/S2: series resistors on DATA nets (the schematic text seems to show 22 ohm), pin sharing with other functions, DDR width and clock, whether fpga_manager runtime load works, Python module availability.
Device (XC7Z010): 17,600 LUT, 35,200 FF, 80 DSP, 60 BRAM36 (verify in the data sheet).
Estimated utilization (no synthesis yet, +/-30 to 40 %): everything in the PL would need about 90 % LUT and 100 % BRAM, so BRAM is the limit. Recommended partition: PL = sweep sequencer, ADC capture, DDC, power/log, FFT; PS = trace maths, waterfall, zero-span buffer, markers. That gives roughly 60 to 70 % LUT, 30 % DSP, 50 to 60 % BRAM including an ILA. Run synthesis early and replace these estimates.
PS vs BBB (estimates): single thread BBB A8 at 1 GHz about 15 to 20 % ahead of one A9 at 667 MHz; two A9 cores about 1.5 to 1.8x in aggregate; float64 faster on the A9. The PRU (200 MHz integer cores, 8 KB program and 8 KB data, 5 ns per instruction) is enough for Stage A control but not for tens of MSPS capture; only the PL does Stage B.

## 8. Adapter PCB v2 (user task U1; files in `zynq-ebaz/hw/`, edited only by the user)
- Power entry: a single 12 V brick into the adapter, buck to 5 V, 5 V to the EBAZ via the DATA VCC pins, own clean 3.3 V (LDO) for PE4302 and the ADC, ferrite-filtered module supplies as on the cape. Do not rely on a 3.3 V rail from the EBAZ.
- Keep DATA VCC pins away from signal headers; use a 2.0 mm to 2.54 mm interface (a daughter board for the EBAZ exists on GitHub: dave18/EBAZ4205-Daughter-Board) or a direct 2.0 mm mating connector.
- Reuse from the cape: 220 ohm series resistors, 2.2 kohm PE4302 pull-ups (boot default 31.5 dB), CE jumper, PDR jumper, test points. The detector divider/clamp is only needed if the BBB path is kept (the EBAZ uses an external ADC).
- Add: SPI SAR ADC for the detector, ADS1115 footprint, AD9226 header with DRVDD = 3.3 V, 10 MHz reference footprint (optional), spare header for triggers/LEDs.
- Hand-placed in KiCad, ERC/DRC by the user.

## 9. Open decisions for the user
1. ~~EMIO or AXI IP for Phase 1~~ decided: EMIO (section 3).
2. Which SPI SAR ADC for the detector.
3. Is the 500 MHz ceiling acceptable for v1 (AD831 limit)?
4. Shared reference for ADF4351 and ADC clock, or two clocks.
5. Path of the existing PetaLinux project and the exported XSA.
6. Python on the target rootfs (needs consent) or a C++ `sweepd` later in `native/`.

## Appendix A: register map v0 (F1 reviews and freezes; generator source `zynq-ebaz/rtl/regmap/regmap.toml`)
Base address assigned in the Vivado address editor; 32-bit AXI-lite; offsets in hex.
- 0x000 ID (RO) magic `0x53410001`
- 0x004 VERSION (RO) build stamp
- 0x008 CTRL: bit0 start (self-clearing), bit1 abort, bit2 soft_reset, bit3 irq_en, bit4 pin_owner (0 = PS EMIO, 1 = engine), bit5 send_init (write shadow R5..R1 before the first point)
- 0x00C STATUS: bit0 busy, bit1 done, bit2 err_lock, bit3 aborted, bit4 ld_now, bit5 table_empty
- 0x010 N_POINTS, 0x014 N_AVG, 0x018 SPI_DIV, 0x01C T_ATT_GAP_CYC
- 0x020 T_MIN_US (after R0 write), 0x024 T_LOCK_STABLE_US, 0x028 T_LOCK_TIMEOUT_US, 0x02C T_SETTLE_US
- 0x040..0x054 SHADOW_R1..SHADOW_R5 (words as produced by Python)
- 0x060 FIRST_ERR_INDEX (RO), 0x064 POINT_COUNT (RO), 0x068 SWEEP_COUNT (RO)
- 0x070 PE4302_MANUAL (value used when pin_owner = 1 and idle), 0x074 PIN_STATE (RO, live pins)
- 0x1000 TABLE window (write, 2 words per entry), 0x4000 RESULT window (read, 1 word per point)

## Appendix B: sweep table, results, FSM
Table entry (64 bit, two little-endian words): word0 = R0 (32 bit); word1 bits [5:0] PE4302 code (V1..V6 order as in `drivers/pe4302.py`), bit [8] resend shadow R1, R2 before R0, bit [9] skip lock wait (debug). Results: 32-bit sum of N_AVG detector samples per point; N_AVG is a register; per-sweep errors in STATUS, first failing index in FIRST_ERR_INDEX.
FSM per point: LOAD -> ATT (set OR(old,new), wait T_ATT_GAP_CYC, set new) -> SYNTH (optional R1/R2 resend, then R0) -> WAIT_MIN (R0 triggers VCO autocal, ignore LD for T_MIN_US) -> WAIT_LOCK (LD high for T_LOCK_STABLE_US, else timeout -> err_lock, point marked, sweep continues or aborts per a CTRL option) -> SETTLE (T_SETTLE_US for the detector) -> SAMPLE (N_AVG samples) -> STORE -> next or DONE (irq). Abort returns to IDLE with PE4302 at its last value and the synth untouched.

## Appendix C: resource budget (typical values, LUT / DSP / BRAM36)
Stage A minimal: AXI glue 1.2k/0/0; engine incl. SPI and table 0.8k/0/4; detector path 0.5k/1/0; DMA (only if used) 1.5k/0/2. Stage B: AD9226 interface 0.3k; NCO + mixer 0.5k/3/1; CIC 1.5k; FIR sets 1k/6/3; power/log 0.5k/2/1; 4096-point FFT with window and buffers 3k/10/16; ILA 1k/0/8. F3 replaces these by measured numbers.

## Appendix D: pin map proposal (adapter v2 defines the final map; S2 verifies against the schematic)
Balls from the community pinout table. All LVCMOS33.
- DATA1 (AD9226): D0 1-5 A20, D1 1-7 B19, D2 1-8 B20, D3 1-9 C20, D4 1-13 D20, D5 1-14 D18, D6 1-16 D19, D7 1-17 F20, D8 1-18 E19, D9 1-19 F19, D10 1-15 H18, D11 1-11 H17, OTR 1-6 H16, ADC_CLK 1-20 K17
- DATA2 (control): ADF4351 CLK 2-5 G20, DAT 2-7 G19, LE 2-8 H20, LD 2-9 J19, CE 2-13 K19; PE4302 V1..V6 2-14 J20, 2-15 L16, 2-16 L19, 2-17 M18, 2-18 L20, 2-19 M20; I2C SCL 2-20 L17, SDA 2-11 K18; spare 2-6 J18
- DATA3 (mostly bank 34, spare): triggers, LEDs, second channel; 3-5 and 3-8 are bank 35 (M19, M17)

## Appendix E: ADC selection and LVDS notes (from v1)
- Recommended: AD9226 module. 12 bit, 65 MSPS, parallel CMOS; datasheet SNR 69 dB @ 31 MHz, ENOB 11.1 @ 10 MHz; 5 V analog supply, 3 V or 5 V driver supply; pin-compatible family AD9220..AD9225. An EBAZ4205 project already uses it as a 0 to 32 MHz spectrum viewer (FPGA supplies the 64 MHz clock, 16384-sample frames, zoom DDCs from 10 MHz down to 10 kHz).
- Check DRVDD = 3.3 V; the module attenuates its input by about 8.4 dB (one user modified it for gain).
- LVDS is not needed for a 10.7 MHz IF. On 3.3 V HR banks LVDS_25 works as an input only; on-chip DIFF_TERM needs a matching VCCO, so terminate with 100 ohm externally. TMDS_33 does not fit ADC LVDS outputs (needs about 2.7 to 3.23 V common mode). The FPGA cannot drive an LVDS sample clock here. Vivado may warn about LVDS_25 and LVCMOS33 in one bank (verify, test early).
- No cheap LVDS ADC breakout found; known options are eval boards (TI ADS4122/ADS4222 class, ADI AD9253, Digilent Zmod) needing adapters, SYZYGY or FMC. A custom serial-LVDS board needs only a few pairs, but one lane at 12 bit x 65 MSPS is 780 Mb/s, probably near the HR-bank limit (verify in DS187); use two lanes or 40 MSPS.

## Sources
- EBAZ4205 summary: https://gitee.com/jinnxf/EBAZ4205
- DATA connector pinout: https://github-wiki-see.page/m/xjtuecho/EBAZ4205/wiki/Data-Connectors
- XADC not exposed: http://kofa.mmto.arizona.edu/fpga/plans.html
- AD9226 on EBAZ4205: https://hackaday.io/project/186329-32mhz-spectrum-sdr-ft8-in-an-fpga and https://github.com/wallufo/EBAZ4205_SDR
- Vivado board files (3.3 V banks): https://www.hackster.io/mindaugas2/creating-xilinx-vivado-board-files-for-ebaz4205-a7b120
- LVDS_25 inputs at 3.3 V: https://discuss.pynq.io/t/syzygy-vio-on-rfsoc-4x2/8715
- AD9226 datasheet summary: https://datasheetq.com/pdf-html/10507/ADI/1page/AD9226.html
- PRU subsystem: https://ti.com/lit/sprace9 and https://ti.com/lit/sprace8
