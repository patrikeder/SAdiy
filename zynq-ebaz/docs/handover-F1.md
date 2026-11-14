# Handover F1: contracts, PL model, offload seam (for the Linux lane: S5, S7, S13)

Written by session R. Spec of the engine: `rtl-spec.md` (it wins over everything here).

## What exists

| Path (under `zynq-ebaz/`) | Content |
|---|---|
| `sw/sadiy_ebaz/platform.py` | `TableEntry`, `OffloadResult`, `Capabilities`, `SweepOffload` and `Platform` protocols, `build_table()`, `att_pins_for()` |
| `sw/sadiy_ebaz/regmap_toml.py` | offsets and field positions read from `rtl/regmap/regmap.toml` (env `SADIY_REGMAP_TOML` overrides the path) |
| `sw/sadiy_ebaz/reg_offload.py` | `RegOffload(reg_read, reg_write, ...)`: the whole software side of the engine, backend independent |
| `sw/sadiy_ebaz/offload_sweep.py` | `OffloadSweep`: what `SweepEngine` calls (`run_points`); builds, uploads and runs the table |
| `sw/sadiy_ebaz/ebaz_pl_model.py` | `PlModel`: register-level model of the engine (no timing) |
| `sw/sadiy_ebaz/platforms/fake_pl.py` | `FakePlPlatform` and `build_engine(cfg)` on the model: the worked example |
| `sw/tests/contract/`, `sw/tests/test_platform_hook.py` | contract tests |
| `rtl/sim/gen_vectors.py`, `rtl/sim/vectors/` | golden vectors (`rtl/scripts/gen.sh` regenerates, `--check` verifies) |

Seam edits outside `zynq-ebaz/` (to be committed as `seam:`): `core/sweep.py` (optional `offload`),
`server/sweepd.py` (`build_hw_engine` plugin hook), `pyproject.toml` (test paths), `.gitignore`.

## What the engine does with an offload

`SweepEngine(..., offload=OffloadSweep(...))`: `run()` calls `offload.run_points(points, atten_db, averages)` and
gets `(volts, unlocked, atten_db_set)`. It does not tune the synthesiser and does not set the attenuator itself:
the table does both. dBm, range flags and stats are computed as in the per-point loop. There is no median and no
outlier flag (the PL sums N samples, so the result is a mean). `run_rejecting` works unchanged (two `run()` calls,
two table uploads). `engine.safe_state()` first calls `offload.safe_state()` (abort, PS lines to all stages in,
pins back to the PS), then the synthesiser goes off over the PS SPI.

## Contract of `RegOffload(reg_read, reg_write, *, sample_source, volts_per_count, det_src, det_test_base, stop_on_err, ...)`

- `reg_read(offset) -> int` and `reg_write(offset, value) -> None`: 32-bit access at a byte offset in the 4 KiB
  window of the core. Nothing else is needed from a backend.
- The constructor reads ID, VERSION and CAPS. It raises `RuntimeError` for a wrong magic or a different major
  version. It writes `CTRL.stop_on_err`, and `DET_CFG` / `DET_TEST` when `det_src` / `det_test_base` are given.
- `upload(entries)`: `TABLE_ADDR = 0`, then `TABLE_W0`, `TABLE_W1` per entry; checks `TABLE_ADDR`. `ValueError` when
  the table is larger than the core.
- `run(n_avg, timeout_s)`: takes the pins if the engine does not own them yet (`acquire_pins()`), writes
  `N_ENTRIES`, `N_AVG`, sets `CTRL.start`, polls `STATUS`. With `DET_CFG.src = 0` it feeds `sample_source()` (raw
  16-bit code) `n_avg` times into `DET_PUSH` each time `STATUS.wait_sample` is set. On `done` it reads
  `POINT_COUNT` results through `RESULT_ADDR` / `RESULT_DATA`. `TimeoutError` after writing abort;
  `RuntimeError` on `err_table`; `ValueError` for `n_avg` outside 1..4095.
- `acquire_pins()` copies the PE4302 pin levels read from `PIN_STATE.pe_in` into `PE4302.manual`, then sets
  `pin_owner`. `release_pins()` clears it: call it only when the PS GPIO lines already drive `pin_levels()` and
  the PS SPI is idle. `set_att_pins(levels)` changes the engine's PE4302 state (make-before-break, idle and owner only).
- `status()` dict, `abort()`, `soft_reset()`, `counts_to_volts(mean) = mean * volts_per_count`.

## What an `ebaz_pl` platform module must provide

File `zynq-ebaz/sw/sadiy_ebaz/platforms/ebaz_pl.py` (`[platform] name = "ebaz-pl"` resolves to it):

1. `build_engine(cfg: dict) -> SweepEngine`.
2. A UIO mmap of the core: find the UIO device by name from the device tree, never hard-code the base address
   (`0x43C0_0000` in the block design). `reg_read` / `reg_write` are 32-bit loads and stores at
   `base + offset`. Use `mmap` with `ACCESS_WRITE` and `struct`/`memoryview` cast to `'I'`; no read-modify-write
   tricks, the registers are full words.
3. The software sequence of rtl-spec.md section 9, in this order:
   a. PS owns the pins: program the synthesiser as today (outputs off, tune, wait for lock, enable the output).
   b. Build the engine: `Adf4351` and `PE4302` on the EMIO lines (PS SPI0 and six GPIO), `RegOffload(reg_read,
      reg_write, sample_source=..., det_src=...)`, `OffloadSweep(offload, synth, steps, active_high, atten=pe4302)`,
      `SweepEngine(..., offload=that)`. `RegOffload.run()` does `acquire_pins()` itself.
   c. The R4 words in the table carry the output state of `synth.outputs`: set the outputs before the first run.
   d. Sample source: `det_src=0` with `sample_source` reading the ADS1115 (phase 2), later `det_src=2` (PL ADC).
      With the ADS1115 (860 SPS) the sweep rate is set by the PS, not by the engine.
   e. `volts_per_count` = ADC full scale / 32768 for the ADS1115 (4.096 V range).
4. Pins must be handed back (`release_pins()`) before anything uses the PS SPI or the PS PE4302 GPIO again. The
   engine's `safe_state()` hook already does it; the platform should also call it on shutdown.
5. `capabilities`: `Capabilities("ebaz-pl", True, 16, 2**CAPS.table_aw, 2**CAPS.result_aw)` (`RegOffload.max_entries`,
   `max_points` have the values).

An `ebaz-ps` platform (no offload) does not need any of this: `SweepEngine` without `offload` is the per-point loop.

## Adding a backend to the contract tests

Edit `OFFLOAD_PLATFORMS` in `sw/tests/contract/test_offload_contract.py`: add `("ebaz_pl", factory)`. `factory(**kw)`
returns a `Platform` whose `offload()` is the `RegOffload`; `kw` may carry `det_src` and `sample_source`. Tests that
steer the engine through a `model` attribute (lock failures, `det_src = 3`) skip a backend without one; the others
run against the real core in a hardware-in-the-loop run. Do not weaken a test to make a backend pass: change
`rtl-spec.md` first and tell lane R.

## Running the tests

```
cd /media/patrik/Workspaces/uC/SAdiy-rtl          # or the main checkout after the merge
. .venv/bin/activate                              # the worktree uses ../SAdiy/.venv
pytest -q                                         # everything, including zynq-ebaz/sw/tests and zynq-ebaz/rtl/tests
pytest -q zynq-ebaz/sw/tests/contract             # only the contract tests
zynq-ebaz/rtl/scripts/gen.sh --check              # generated files and vectors are current
```

`zynq-ebaz/sw` is on pytest's `pythonpath`. For `sweepd` runs set `PYTHONPATH=zynq-ebaz/sw`. A quick try without
hardware: `[platform] name = "fake-pl"`, then `build_hw_engine(cfg)` returns an engine on the model.

## Proposal for S13 (do not edit `server/protocol.py` before this is agreed)

All additive in the frame header (like `flags`), `VERSION` stays 1. Defaults keep old readers working.

| Item | Where | Proposal |
|---|---|---|
| ADC source | frame header `adc` | string: `"ads1115"`, `"pl_push"`, `"pl_ext"`, `"bbb_iio"`, `"sim"` |
| Averages | frame header `n_avg` | int, samples summed per point (the engine's `averages`) |
| Combine | frame header `combine` | `"median"`, `"trimmed"`, `"mean"`; offloaded sweeps always `"mean"` |
| Lock errors | frame header `lock_errors` | int, points with a lock timeout in this sweep (flags carry them per point) |
| Offload | frame header `offload` | bool, true when the PL ran the sweep |
| RBW | `set` command `rbw` and frame header `rbw_hz` | read-only enum first: `{"rbw": "auto"}` accepted, header reports the real RBW (low-IF filter value now, DDC value later); the GUI shows it, does not set it |
| Capabilities | `status` reply `platform` | `{"name", "sweep_offload", "detector_bits", "max_entries", "max_points"}` from `Capabilities` |
| Offload status | `status` reply `offload` | the dict of `SweepOffload.status()` when present (counters, `err_lock`, `first_err_index`) |

## Readings of the spec that the model took (agreed with the RTL on 2026-11-14 and written into rtl-spec.md)

- `start` clears status, `POINT_COUNT` and `FIRST_ERR_INDEX` even when it is refused; a refused start then sets `err_table` and `done`.
- Within one `CTRL` write: `soft_reset` wins, then `irq_ack`, `abort`, `start`. `start` sees `pin_owner_act` as before the write.
- `TABLE_ADDR` and `TABLE_W1` writes are ignored while busy; `TABLE_W0` is plain storage and is always written. A table index above the depth wraps (RAM address truncated).
- `PE4302.manual` written while idle and owner starts make-before-break only if it differs from the engine value. Written while busy or not owner: no action, not applied later.
- Taking the pins loads `manual`. Result memory full: sweep ends with `done` and `err_table`, `SWEEP_COUNT` not incremented. `stop_on_err` and `abort` leave `ENTRY_INDEX` at the current entry.
- `soft_reset` clears `POINT_COUNT`, `ENTRY_INDEX`, `FIRST_ERR_INDEX` and `SWEEP_COUNT`.
- `DET_CFG.src = 2` with no stream behaves like `src = 3`. Unwritten table RAM is zero (no-op entries).
- The engine's reset PE4302 value is `0x3F` levels: all stages in only for an active-high module. For an active-low module write `PE4302.manual` before taking the pins (`acquire_pins()` does).
