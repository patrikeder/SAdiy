# Ramp self-test (pass/fail, no RF)

What it tests: the whole software/hardware path of the PL sweep engine without any analog part, using the engine's own
test generator. The answer is known in advance, so the result is PASS or FAIL, not "looks plausible".

    ~/sadiy/selftest.sh [--sweeps 5] [--points 401 | --fill] [--n-avg 4] [--base 10000] [--wrap] [-v]     # exit 0 PASS, 1 FAIL, 2 could not run
    GUI, Advanced tab: "Ramp self-test" button   # while sweepd sweeps: the `selftest` command, see below
    ~/sadiy/sweep.sh --test-ramp        # not a test: sweepd with the ramp as detector, to look at it in the GUI

Code: `zynq-ebaz/sw/sadiy_ebaz/ramp_test.py` (`check_sweep` holds the criteria), tests in `zynq-ebaz/sw/tests/test_ramp_test.py`
(the same code runs against the PL model on a PC: `python -m sadiy_ebaz.ramp_test --model --wrap`). The interface and
the expected values were agreed with the RTL session (answers below, read from `sweep_seq.sv`, `det_sampler.sv`,
`pin_mux.sv` and the spec; not yet confirmed on the board).

## From the GUI (sweepd running)

`sweepd` has the command `selftest` (parameters `points`, `n_avg`, `base`, `sweeps`, `wrap`, `fill`; reply `passed`, `checks`,
`failed`, `lines`, `seconds`; `status.selftest_available`; `server/protocol.py`). It runs between two sweeps and the sweeping
goes on afterwards (`OffloadSweep.self_test` -> `ramp_test.run_on_core(release=False)`), so differently from `selftest.sh`:
the engine keeps the pins it has, no `soft_reset` and no release, PE4302 and ADF_PINS are not written (a PE4302.manual write moves the pins, ADF_PINS.ce could flip CE), and only N_AVG, DET_CFG (src 3 -> 1 -> 3), DET_TEST, T_MIN_US and T_SETTLE_US are restored. The sweep table is uploaded
again at the next sweep. Tests that would take longer than 30 s are refused. GUI: Advanced tab, box "Ramp self-test".

## Set-up the test makes

| Item | Value |
|---|---|
| Source | `DET_CFG.src = 1` (test generator), `DET_CFG.mode = 0` (video path; mode 1 ignores src), stream 0, no `DET_PUSH` |
| Table | `points` entries, each `measure = 1, skip_lock = 1, spi_en = 0, att_en = 0` (W1 = 0xC00). Nothing is sent to the ADF4351 |
| `DET_TEST.base` | 10000 by default, written again before every sweep (+1 per sweep, idle only). One poison sweep with `base ^ 0x5555` comes first. `--wrap` adds a second run with N_AVG 1, base 0xFFF0 for the 16-bit wrap |
| `T_MIN_US` / `T_SETTLE_US` | set to 20 / 20 for the test (`--t-min`, `--t-settle`) so that the time floor can detect waits that are not applied; all registers the test writes (N_AVG, DET_CFG, DET_TEST, T_*, ADF_PINS, PE4302) are restored at the end |
| N_AVG | 4 by default (1..4095 valid; 0 counts as 1) |
| Points | 401 by default: at least 257 so the 8-bit index wraps. `--fill` uses all 4096 (table and result memory exactly full, about 181 ms per sweep at 20/20/4): covers the 12-bit addressing |
| Pins | `pin_owner = 1` is required for `start`. The test writes `PE4302.manual` = levels read back from the pins and `ADF_PINS.ce` = the CE level of the pad before taking them (only when the engine does not own the pins yet: an owning engine drives `ADF_PINS.ce` already, and a write with a different pad level would flip the pin), so nothing changes; gives them back at the end and `soft_reset`s |
| sweepd | must not run (`selftest.sh` checks) |

## Expected result and pass criteria

Sample of result point `i` = `(base + (i & 0xFF)) & 0xFFFF`; sum = `N_AVG * sample`. `i` is the result index (counts
measure entries only), restarts at 0 for every `start`. Sum field is 28 bit (max 4095 * 65535 < 2^28: no overflow).

A sweep passes when all of this holds (one line per failed check, with the first wrong index):

1. the run finished (no timeout, not aborted, no `err_table`)
2. `STATUS`: done = 1, busy = 0, state = 0, wait_sample = 0, err_lock = 0, err_table = 0, aborted = 0, pin_owner_act = 1
3. `FIRST_ERR_INDEX = 0`; no result has `unlocked` set (skip_lock on every entry: never)
4. `POINT_COUNT` = number of measured entries = `points`; `ENTRY_INDEX` = `N_ENTRIES` after a normal end
5. `SWEEP_COUNT` goes up by exactly 1 per sweep (compared before/after, not absolute; `soft_reset` clears it)
6. every result sum equals `expected_sums()`; result bits 31:28 are 0 (bit 31 unlocked, 30 ovr is IF-path only, 29:28 reserved)
7. every sweep must produce new values: the result memory is not cleared by `start` and the host cannot write it, so with one base a
   second sweep (or a second run of `selftest.sh`) would pass on stale data even if the engine stored nothing. Hence the poison sweep and a
   different base per sweep; with 3 or more sweeps the last one repeats the first base and must equal sweep 1 exactly
8. pins unchanged: `PIN_STATE.pe_out` (what the engine drives) equals the PE4302 levels read from the pads before the run, and the CE pad level is unchanged, after every sweep
9. time per sweep: not below the hardware floor `points * (T_MIN_US + T_SETTLE_US + N_AVG) us`, not above
   `1.3 * floor + 2 ms` (sequencer overhead and the 1 ms poll). The time measured is `RegOffload.last_sweep_s`
   (start pulse to done seen), so the host's readout of the results (`last_read_s`, listed as information) is not part
   of it. An offload without these times (value 0.0 or no attribute) is timed by the wall clock around `run()` and
   judged against the older loose ceiling `2 * points * (T_MIN_US + T_SETTLE_US + N_AVG + 0.11) us + 50 ms`

Point time in the hardware (R): FETCH 2 clk + ATT 1 clk + SPI 1 clk (spi_en = 0) + T_MIN + T_SETTLE + N_AVG us + STORE and
NEXT 2 clk, about `T_MIN + T_SETTLE + N_AVG + 0.11 us`. With T_MIN 20, T_SETTLE 20, N_AVG 4: 44.1 us per point, 17.7 ms
for 401 points. With one SPI word per entry add about 2.04 us at SPI_DIV 3.

## What a failure usually means

| Report | Likely cause |
|---|---|
| "fits N_AVG=a, DET_TEST.base=b" | wrong value reached the engine (register write, regmap offset, stale PL map) |
| every result equal / all zero | generator not selected (mode 1? src not 1?), or sampler not running |
| "everything from there on differs" | a point skipped or repeated (sequencer, result address) |
| first wrong index at 256 or 257 | 8-bit index wrap or result address handling |
| POINT_COUNT / ENTRY_INDEX / SWEEP_COUNT | counters, table length, a refused start (needs pin owner before `start`) |
| faster than the floor | waits not applied (T_MIN / T_SETTLE register values) |
| slower than the limit | engine stalled between points, or the poll loop is starved (CPU load) |
| `unlocked` / err_lock | skip_lock not applied for some entry (table word 1 bit 11) |

## Not covered (other tests)

Real SPI frames, lock detect, the ADS1115 reader and the analog chain: `pl_bringup.py` stages `spi`, `lock`, `adc`, and the
bench checklist `bench-test-adc-att-lock.md`. The register-level generator check of the RTL lane is `pl_bringup.py gen`;
this self-test goes through the same software layers as a real sweep (`RegOffload`), which is the difference.

## Agreed with the RTL session (2026-11-21)

The formula is exact for every N_AVG and base; no dummy sweep is needed after a table upload or a base change (do not
change the base during a sweep); entries with spi_en = 0 and measure = 1 are legal and leave the ADF4351 pins idle;
`start` needs the pins owned first; SWEEP_COUNT counts normal ends only. If the RTL changes any of this, change
`ramp_test.py` and this page in the same commit.
