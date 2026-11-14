# SAdiy PL sweep engine: specification

Owner: session R (RTL lane). This is the reference for the RTL in `zynq-ebaz/rtl/`, for the Python model
`zynq-ebaz/sw/sadiy_ebaz/ebaz_pl_model.py` and for the `ebaz-pl` backend (S7). It replaces appendices A and B of
`ebaz4205-zynq-plan.md` (their drafts were reviewed here; differences are listed in section 11).
When RTL, model and this text disagree, this text wins: fix the code, or change the text first and say so in
`zynq-ebaz/log_rtl.md`.

Written so that a later session (Sonnet) can maintain the RTL without the history. Section 12 is the how-to.

## 1. Purpose and limits

The Zynq PL takes over the per-point timing of a sweep: write the ADF4351, wait for lock, let the detector
settle, sum N detector samples, store the sum. Python on the PS prepares everything and reads the results.

Rules that must survive every change:

1. **The PL only transports words.** Every ADF4351 register word is packed by `src/sadiy/drivers/adf4351.py`
   and uploaded in a table. The RTL never builds, modifies or repeats a register word on its own.
2. **RF outputs.** The RTL sends nothing by itself: not at reset, not when taking the pins, not on abort.
   Whether an RF output is on is decided only by the R4 words Python puts into the table.
3. **Attenuator is safe by default.** At reset the engine's PE4302 value is all pins high, which is all
   stages in for an active-high module only. Software therefore writes `PE4302.manual` (and `active_high`)
   from the present pad levels (`PIN_STATE.pe_in`) before it sets `pin_owner`; `RegOffload.acquire_pins()`
   does this. Every change of the
   PE4302 pins made by the engine is make-before-break. With the PS as pin owner and its GPIO lines still
   inputs, the pins are not driven and the adapter's pull-ups give 31.5 dB.
4. **Pin ownership changes only while idle**, and changing it produces no edge on LE or CLK.
5. No vendor IP inside `rtl/src/` (plain SystemVerilog, inferred block RAM). Vendor IP lives only in the block
   design (`rtl/fpga/`).

## 2. Files

| Path (under `zynq-ebaz/`) | Content | Edited by hand |
|---|---|---|
| `rtl/regmap/regmap.toml` | register map, single source | yes |
| `rtl/regmap/gen_regs.py` | generator | yes |
| `rtl/regmap/axil_regs.sv`, `regs.py`, `regs.h`, `regmap.md` | generated | no |
| `rtl/src/sadiy_top.sv` | top of the engine (no pads, no vendor cells) | yes |
| `rtl/src/sweep_seq.sv` | sequencer FSM | yes |
| `rtl/src/adf4351_spi.sv` | 32-bit SPI writer | yes |
| `rtl/src/pe4302_mbb.sv` | make-before-break pin driver | yes |
| `rtl/src/det_sampler.sv` | sample source select and accumulator | yes |
| `rtl/src/pin_mux.sv` | PS / engine pin owner | yes |
| `rtl/src/sdp_ram.sv` | inferred simple dual port RAM | yes |
| `rtl/sim/tb_*.sv` | self-checking testbenches | yes |
| `rtl/sim/gen_vectors.py`, `rtl/sim/vectors/*.hex` | golden vectors from the Python drivers and the model | generator yes, vectors no |
| `rtl/fpga/` | Vivado project scripts, block design Tcl, board top `ebaz_sadiy_top.sv`, constraints | yes |
| `rtl/scripts/` | `gen.sh`, `sim.sh`, `test.sh`, `create_project.sh`, `build_bit.sh` | yes |
| `sw/sadiy_ebaz/ebaz_pl_model.py` | Python model of the register behaviour | yes |

The Vivado project itself is generated into `/media/patrik/Workspaces/HW/Vivado/EBAZ_SAdiy` (not in git).

## 3. Top level `sadiy_top`

One clock (`clk`, FCLK0, 100 MHz), synchronous active-low reset `resetn`.

```
module sadiy_top #(
  parameter int TABLE_AW  = 12,          // table depth 2^TABLE_AW entries of 64 bit
  parameter int RESULT_AW = 12,          // result depth 2^RESULT_AW words of 32 bit
  parameter int CLK_HZ    = 100_000_000
) (
  input  logic        clk, resetn,
  // AXI4-Lite slave, 32 bit data, 12 bit address
  input  logic [11:0] s_axil_awaddr,  input  logic s_axil_awvalid, output logic s_axil_awready,
  input  logic [31:0] s_axil_wdata,   input  logic [3:0] s_axil_wstrb,
  input  logic        s_axil_wvalid,  output logic s_axil_wready,
  output logic [1:0]  s_axil_bresp,   output logic s_axil_bvalid,  input  logic s_axil_bready,
  input  logic [11:0] s_axil_araddr,  input  logic s_axil_arvalid, output logic s_axil_arready,
  output logic [31:0] s_axil_rdata,   output logic [1:0] s_axil_rresp,
  output logic        s_axil_rvalid,  input  logic s_axil_rready,
  output logic        irq,
  // PS side (EMIO): SPI0 and the six GPIO lines of the PE4302
  input  logic        emio_adf_clk, emio_adf_dat, emio_adf_le,
  input  logic [5:0]  emio_pe_o,      // level the PS drives
  input  logic [5:0]  emio_pe_t,      // 1 = PS line is an input (not driven)
  // pins (pads and IOBUFs are in rtl/fpga/ebaz_sadiy_top.sv)
  output logic        adf4351_clk, adf4351_dat, adf4351_le,
  input  logic        adf4351_ld,
  output logic [5:0]  pe4302_v_o,     // level to drive
  output logic [5:0]  pe4302_v_t,     // 1 = do not drive
  input  logic [5:0]  pe4302_v_i,     // pad level
  // detector sample stream of a PL ADC reader (S10); tie valid to 0 until it exists
  input  logic        det_ext_valid,
  input  logic [15:0] det_ext_data
);
```

Not routed through `sadiy_top` (the board top wires them straight between EMIO and the pads): `adf4351_ce`
(EMIO GPIO 6, tri-stated until software drives it), lock detect to the PS (EMIO GPIO 7, in parallel to
`adf4351_ld`), I2C0, Ethernet. EMIO GPIO 0..5 are the PE4302 lines; their read-back (`emio_tri_i[5:0]`) is the
pad level `pe4302_v_i`. This is the same EMIO line map as the Phase 1 design of session L.

## 4. Registers

`rtl/regmap/regmap.md` (generated) lists offsets and fields; `regmap.toml` holds the per-register wording.
AXI4-Lite, 32-bit words, 4 KiB address space, base address `0x43C0_0000` in the block design (Python gets
it from UIO / the device tree, never hard-coded). Writes are full words, `WSTRB` is ignored. Unknown
addresses read 0 and ignore writes; the response is always OKAY.

### Generated module `axil_regs` (port rules)

For a register `FOO` with field `bar` the port is `foo_bar`:

- `rw` field: `output logic [w-1:0] foo_bar` (storage inside, reset value from the TOML)
- `ro` field: `input logic [w-1:0] foo_bar`
- `const` field: no port
- `w1p` field: `output logic foo_bar`, high for one clock when a 1 is written
- register with `wr_strobe = true` (not ext): additionally `output logic foo_wr`, high for one clock on every
  write, in the clock in which the new `rw` values appear (used by `PE4302`).
- register with `ext = true`: `output logic foo_wr` (one clock, write data on the shared
  `output logic [31:0] reg_wdata` in the same clock), `output logic foo_rd` (one clock), and
  `input logic [31:0] foo_rdata`, which is sampled in the clock in which `foo_rd` is high.

Bus timing as generated: when `awvalid` and `wvalid` are both seen and no response is pending, `awready` and
`wready` are high for one clock (T0). In the next clock (T1) the new `rw` value, the `w1p` pulse or `foo_wr`
strobe, `reg_wdata` and `bvalid` all appear together, so logic that sees `ctrl_start` already sees the other
CTRL bits of the same write. A read: `arready` and `foo_rd` are high for one clock, the data is sampled at
the end of it, `rvalid` follows. No combinational path from an AXI input to an AXI output.

## 5. Sweep table and results

Table entry, 64 bit, written as two words (`TABLE_W0`, then `TABLE_W1`, which commits and increments
`TABLE_ADDR`):

| Bits | Name | Meaning |
|---|---|---|
| W0 31:0 | word | SPI word for the ADF4351, sent MSB first |
| W1 5:0 | att | PE4302 pin levels V1..V6, bit 0 = V1 (levels, not dB: Python applies weights and polarity) |
| W1 8 | spi_en | send `word` |
| W1 9 | att_en | apply `att` (make-before-break) before the SPI word |
| W1 10 | measure | after the SPI word take one measurement and store one result |
| W1 11 | skip_lock | with `measure`: skip the lock wait |

One sweep executes entries `0 .. N_ENTRIES-1` in order. A point of the sweep is a run of entries that ends
with a `measure` entry; Python sends only the register words that changed since the previous point (R0 always,
last, because it starts the VCO band selection), so most points are one or two entries. An entry with neither
`spi_en`, `att_en` nor `measure` is a no-op.

Result word, 32 bit, one per `measure` entry, index = order of the `measure` entries:

| Bits | Name | Meaning |
|---|---|---|
| 27:0 | sum | sum of N_AVG unsigned 16-bit samples |
| 30:28 | 0 | reserved (30 is planned for ADC over-range) |
| 31 | unlocked | lock detect timed out; the sum was still taken |

Read back: write `RESULT_ADDR`, then read `RESULT_DATA` repeatedly (auto-increment).
Python median / outlier handling does not exist in the PL; an offloaded sweep returns sums (mean).

## 6. Sequencer (`sweep_seq`)

`STATUS.state` encoding: 0 IDLE, 1 FETCH, 2 ATT, 3 SPI, 4 WAIT_MIN, 5 WAIT_LOCK, 6 SETTLE, 7 SAMPLE, 8 STORE,
9 NEXT.

```
IDLE  --start--> FETCH (entry 0)          start is refused (err_table, done) if N_ENTRIES == 0,
                                          N_ENTRIES > 2^TABLE_AW, or the engine did not own the pins
                                          before this write (pin_owner and start in one write: the
                                          pins are taken, the start is refused)
FETCH : read the entry (2 clocks: synchronous RAM)
ATT   : if att_en: pins = make(old, att); wait T_ATT_GAP_CYC; pins = att; wait T_ATT_GAP_CYC
SPI   : if spi_en: send word (section 7)
        if not measure -> NEXT
WAIT_MIN  : T_MIN_US
WAIT_LOCK : skipped if skip_lock. Locked when LD was high for T_LOCK_STABLE_US in a row (0 = the first
            clock with LD high). Timeout after T_LOCK_TIMEOUT_US in this state: the point is flagged
            (result bit 31, STATUS.err_lock, FIRST_ERR_INDEX on the first one). With CTRL.stop_on_err the
            sweep ends here (no result stored for this point), otherwise it goes on.
SETTLE    : T_SETTLE_US
SAMPLE    : sum N_AVG samples from the selected source (section 8); STATUS.wait_sample = 1
STORE     : result[POINT_COUNT] = {unlocked, 3'b0, sum}; POINT_COUNT += 1.
            If the result memory is already full: err_table, the sweep ends.
NEXT      : entry += 1; entry == N_ENTRIES -> IDLE with done = 1, SWEEP_COUNT += 1; else FETCH
```

- All microsecond times count `CLK_HZ / 1e6` clocks per unit, restarted when the state is entered (no free
  running tick, so the timing is identical from sweep to sweep). A time of N takes N x 100 + 1 clocks.
- `start` is latched: if an attenuator change from `PE4302.manual` or a pin owner change is still in
  progress, the sweep begins when that is finished. `STATUS.busy` is high from the `start` write on.
- `abort` is honoured in every state except in the middle of an SPI word or of an attenuator change, which
  finish first. Then: IDLE, `done = 1`, `aborted = 1`, no result for the unfinished point, PE4302 pins stay
  at their last value, the synthesiser is not touched.
- `soft_reset` returns the sequencer to IDLE and clears `done`, `err_lock`, `aborted`, `err_table`,
  `POINT_COUNT`, `FIRST_ERR_INDEX`, `ENTRY_INDEX`, `SWEEP_COUNT`. In one CTRL write it wins over the other
  pulses. An SPI word or attenuator change that is in progress
  finishes on its own (a word is never cut short: a rising LE on a partial word would load garbage into the
  ADF4351). Not touched: configuration registers, the tables, the result memory, the pin owner and the
  PE4302 pins.
- `start` clears `done`, `err_lock`, `aborted`, `err_table`, `POINT_COUNT`, `FIRST_ERR_INDEX`. It is ignored
  while busy, and a refused start clears the same things before it sets `err_table` and `done`. While busy,
  `TABLE_ADDR` and `TABLE_W1` writes are ignored (`TABLE_W0` is plain storage); other register writes are not
  blocked (do not change timing registers during a sweep).
- `stop_on_err` and `abort` leave `ENTRY_INDEX` at the entry that was running and do not count in
  `SWEEP_COUNT`. Table and result indices beyond the depth wrap (the address is truncated).
- `irq = CTRL.irq_en & STATUS.done` (level). `done` is cleared by `irq_ack`, `start`, `soft_reset`.
- There is no watchdog on SAMPLE: with source 0 the PS decides the pace. Recovery is `abort`.

## 7. ADF4351 SPI writer (`adf4351_spi`)

Mode 0, MSB first, 32 bits, LE is the frame signal (low during the word, the rising edge loads the ADF4351).
`H` = `SPI_DIV` clocks (minimum 2). Idle: CLK low, LE high, DAT low.

```
LE  ‾‾‾\_______________________________ ... ______________/‾‾‾‾‾‾‾‾
CLK ________/‾‾‾\___/‾‾‾\___/‾‾‾\___    ...  /‾‾‾\___________________
DAT ----<  b31  ><  b30  ><  b29  >     ... <  b0   >________________
       |<-H->|<-H->|<-H->|                         |<-H->|<-- 2H -->| busy ends
```

LE falls and b31 is put out together; after H the first rising edge; DAT changes on falling edges; after the
last falling edge H later LE rises; busy ends 2 H after that. A word takes 67 H (3.35 us at the reset value,
10 MHz). The ADF4351 needs 10 ns setup, 25 ns clock high / low and 20 ns LE width: any H >= 3 at 100 MHz is
inside; H = 2 is 20 ns per half period and is outside the datasheet value, do not use it on hardware.

## 8. Detector samples (`det_sampler`)

A sample is a 16-bit unsigned code with a valid strobe. Source per `DET_CFG.src`:

| src | Source | Use |
|---|---|---|
| 0 | each write of `DET_PUSH` | Phase 2 on hardware: the PS reads the ADS1115 and pushes; also unit tests |
| 1 | test generator: `(DET_TEST.base + (result_index & 0xFF)) & 0xFFFF`, one sample every microsecond | simulation and HIL timing tests without an ADC |
| 2 | `det_ext_valid` / `det_ext_data` | the SPI ADC reader of S10 |
| 3 | nothing | |

Samples count only in SAMPLE; anything arriving in another state is dropped. `N_AVG = 0` is treated as 1.

## 9. PE4302 (`pe4302_mbb`) and pin owner (`pin_mux`)

Make-before-break: `make = old | new` for `PE4302.active_high = 1`, `old & new` for 0. Sequence: `make`,
hold `T_ATT_GAP_CYC` clocks, `new`, hold `T_ATT_GAP_CYC` clocks, ready. If `make == old == new` nothing
changes but the time is the same. This equals what `drivers/pe4302.py` reaches after its "turning on" writes,
for all 64 x 64 transitions (vectors `mbb_high.hex`, `mbb_low.hex`).

Who changes the engine's PE4302 value: (a) a table entry with `att_en`; (b) a write of `PE4302` while the
engine owns the pins and is idle, if `manual` differs from the levels the engine drives (make-before-break; a
`start` written meanwhile waits for it). A write at any other time only stores the value and is not applied
later; (c) taking ownership loads `PE4302.manual` directly, because the old state was the PS's. After a sweep
the pins stay at the last table value; they do not fall back to `manual`.

Pin owner: `STATUS.pin_owner_act` follows `CTRL.pin_owner` only while the sequencer is idle and no SPI word
or attenuator change is running.

| Pin | owner 0 (PS) | owner 1 (engine) |
|---|---|---|
| `adf4351_clk/dat/le` | `emio_adf_*` | SPI writer |
| `pe4302_v_o`, `pe4302_v_t` | `emio_pe_o`, `emio_pe_t` | engine value, `t = 0` |

A `CTRL.pin_owner` write during a sweep is remembered and takes effect when the sweep has ended.
The outputs of the mux are registered (one clock of delay on the PS path, irrelevant at 10 MHz SPI). Both
owners idle with LE high and CLK low, so a switch makes no edge as long as the PS SPI is idle too: software
must not switch during a PS transfer. `PIN_STATE` shows the pins after the mux.

Software sequence for an offloaded sweep (S7): with the PS as owner program the synth as today (outputs off,
tune, wait for lock, enable the output); write `PE4302.manual` = the current pin levels; set `pin_owner`;
upload the table (its R4 words carry the output state Python wants); `start`; wait for `done`; read results.
Hand the pins back only when the PS GPIO lines already drive the wanted levels.

## 10. Verification

| Testbench | Checks |
|---|---|
| `tb_axil_regs` | reset values, rw / ro / const / w1p / ext behaviour, bus handshakes |
| `tb_adf4351_spi` | bit stream of every word in `spi_words.hex` decoded as an ADF4351 would; frame shape; divider values |
| `tb_pe4302_mbb` | all 64 x 64 transitions against `mbb_high.hex` / `mbb_low.hex`, gap length |
| `tb_sweep` | `sadiy_top` through AXI: table upload, full sweep with a behavioural lock model, SPI words and results against `sweep_*.hex`; lock timeout with and without stop_on_err; abort; PS push source; pin owner; refused start |

The testbenches were checked by breaking the RTL on purpose (lost lock flag, ignored stop_on_err / abort,
table write while busy, wrong sample count, break-before-make, lost SPI bit, owner change during a sweep):
each of these makes a testbench fail. Repeat such a check when you add a feature and its test.

RTL files carry no `timescale`; `sim.sh` passes `-timescale 1ns/1ps` to xelab.

Every testbench prints `TB PASS` or `TB FAIL: <reason>` and ends with `$finish`. `rtl/scripts/sim.sh` runs
them in xsim and fails on anything else. The same vectors are produced from the Python model, so model and
RTL are checked against each other.

## 11. Differences to the plan (appendices A, B, contract in 1a)

- Table entries are generic SPI words with flags instead of "R0 plus resend-shadow bits". Reason:
  `Adf4351.registers()` changes R1 (MOD, prescaler), R2 / R3 (integer mode) and R4 (divider) between points;
  shadow registers in the PL could not follow that without knowing register contents. So `SHADOW_R1..R5` and
  `CTRL.send_init` do not exist.
- Table and results are reached through address / data registers instead of windows at 0x1000 / 0x4000: the
  core fits one 4 KiB page for UIO and the depth is a parameter (default 4096 entries, 4096 results).
- `N_POINTS` became `N_ENTRIES`; the number of points is `POINT_COUNT`.
- Result words carry the per-point lock flag in bit 31.
- Agreed with the Python model on 2026-11-14 (the model's readings are listed in `handover-F1.md`): the points
  above on refused start, table writes while busy, soft reset and the `PE4302` write are the result.
- Added: `DET_CFG`, `DET_TEST`, `DET_PUSH` (PS-fed samples make Phase 2 measure with the ADS1115), `CAPS`,
  `PE4302.active_high`, `CTRL.stop_on_err`, `CTRL.irq_ack`.
- `sadiy_top` has `_o / _t / _i` triples for the PE4302 pins instead of plain outputs, so the tri-state
  boot default of Phase 1 survives; CE, I2C and LD-to-PS bypass it.
- Session R also owns the Vivado project for the engine (`rtl/fpga/`, user decision 2026-11-14). Session L's
  `rtl/vivado/` (Phase 1, `pins.toml`) is untouched and stays the master for pin locations.

## 12. How to change things (for the maintaining session)

Always: edit, `rtl/scripts/test.sh` (generators, pytest, all testbenches), then `rtl/scripts/build_bit.sh` if
the change must go to hardware, then add a dated entry to `zynq-ebaz/log_rtl.md`.

- **New or changed register**: edit `regmap.toml` (bump `[map] version` and the `VERSION` reset value if
  software must notice), run `rtl/scripts/gen.sh`, connect the new port in `sadiy_top.sv`, mirror the
  behaviour in `ebaz_pl_model.py`, describe it in this file, extend `tb_sweep` or `tb_axil_regs`.
- **New sequencer step**: add the state at the end of the encoding (do not renumber), describe it in
  section 6 first, mirror in the model, regenerate vectors (`gen.sh`), extend `tb_sweep`.
- **New sample source (S10)**: write the reader as its own module with a `valid / data[15:0]` output,
  instantiate it in `ebaz_sadiy_top.sv` and connect it to `det_ext_*`; add its pins to session L's
  `pins.toml` (ask L, via the log). `sadiy_top` does not change.
- The SPI and PE4302 pads are false paths in `rtl/fpga/constraints/timing.xdc` (slow signals, DAT changes
  half a bit away from the sampling edge). If the SPI is ever run faster than 10 MHz, put the three output
  registers of `pin_mux` into the IOBs instead.
- **Timing fails** (`build_bit.sh` reports WNS < 0): do not relax constraints. Report the path in the log;
  typical fix is one more register stage on the failing path. If two attempts fail, write an escalation
  (plan, section 1).
- Do not: add vendor primitives to `rtl/src/`, drive pins from anywhere but `pin_mux`, make the RTL emit an
  SPI word that is not in the table, change the reset value of `PE4302.manual` or the idle levels of LE / CLK.
