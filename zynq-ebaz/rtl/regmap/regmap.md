<!-- generated from regmap.toml by gen_regs.py, do not edit -->
# Register map

Map `sadiy`, version 0x00010000, 12-bit address, 32-bit registers. Writes are full words (WSTRB ignored); bits without a field read 0.
Registers marked *ext* are implemented outside `axil_regs.sv`.

| Offset | Name | Reset | Description |
|---|---|---|---|
| 0x000 | ID | 0x53410001 | Magic number, identifies the core. |
| 0x004 | VERSION | 0x00010000 | Register map version (major << 16 \| minor). Equals [map] version. |
| 0x008 | CTRL | 0x00000000 | Control. Pulse bits read 0. |
| 0x00C | STATUS | 0x00000000 | Status, read-only. |
| 0x010 | N_ENTRIES | 0x00000000 | Number of table entries one sweep executes (1 .. 2^TABLE_AW). |
| 0x014 | N_AVG | 0x00000001 | Detector samples summed per measured point (1 .. 4095). 0 is treated as 1. |
| 0x018 | SPI_DIV | 0x00000005 | ADF4351 SPI half bit period in clk cycles (f_sclk = f_clk / (2 * div)). Values below 2 are treated as 2. Reset 5 = 10 MHz at 100 MHz. |
| 0x01C | T_ATT_GAP_CYC | 0x00000064 | PE4302 make-before-break: clk cycles the intermediate (make) state is held, and again after the final state before the entry continues. |
| 0x020 | T_MIN_US | 0x000000C8 | Microseconds after the last SPI word of a measured entry during which lock detect is ignored (VCO band selection). |
| 0x024 | T_LOCK_STABLE_US | 0x00000032 | Lock detect must stay high for this long without a break to count as locked. |
| 0x028 | T_LOCK_TIMEOUT_US | 0x00002710 | Give up waiting for lock after this long (counted from the end of T_MIN_US). |
| 0x02C | T_SETTLE_US | 0x000001F4 | Detector settling time between lock (or timeout) and the first sample. |
| 0x030 | PE4302 | 0x0000013F | PE4302 pin control of the engine. Reset state = all stages in (31.5 dB) for an active-high module. |
| 0x034 | PIN_STATE | 0x00000000 | Live pins after the pin mux, synchronised to clk. |
| 0x038 | DET_CFG | 0x00000000 | Detector sample source. |
| 0x03C | DET_TEST | 0x00000000 | Test generator: sample = (base + low 8 bits of the result index) mod 65536, one sample per microsecond tick while the sequencer is in SAMPLE. |
| 0x040 | DET_PUSH (ext) | 0x00000000 | Write: one detector sample (bits 15:0) for DET_CFG.src = 0. Counted only while STATUS.wait_sample = 1; otherwise dropped. Reads 0. |
| 0x044 | FIRST_ERR_INDEX | 0x00000000 | Result index of the first point with a lock timeout in the last sweep (valid when STATUS.err_lock = 1). |
| 0x048 | POINT_COUNT | 0x00000000 | Results stored so far in the current / last sweep (= number of measured entries completed). |
| 0x04C | SWEEP_COUNT | 0x00000000 | Sweeps completed since reset (normal end only), wraps. |
| 0x050 | ENTRY_INDEX | 0x00000000 | Table entry the sequencer is executing (or the one after the last, when done). |
| 0x060 | TABLE_ADDR (ext) | 0x00000000 | Table entry index for the next TABLE_W1 write. Read / write; increments by one on every TABLE_W1 write. Writes are ignored while busy. |
| 0x064 | TABLE_W0 | 0x00000000 | Word 0 of the table entry being written: the 32-bit SPI word (sent MSB first). |
| 0x068 | TABLE_W1 (ext) | 0x00000000 | Word 1 of the table entry (flags). Writing it stores {W1, TABLE_W0} at TABLE_ADDR and increments TABLE_ADDR. Ignored while busy. Reads 0. |
| 0x070 | RESULT_ADDR (ext) | 0x00000000 | Result index for the next RESULT_DATA read. Read / write; increments by one on every RESULT_DATA read. |
| 0x074 | RESULT_DATA (ext) | 0x00000000 | Result word at RESULT_ADDR (read-only, read increments RESULT_ADDR). Wait at least 2 clk cycles after writing RESULT_ADDR (always true from the PS). |
| 0x078 | CAPS | 0x00000000 | Build parameters. |

## ID (0x000)

Magic number, identifies the core.

| Bits | Name | Access | Reset | Description |
|---|---|---|---|---|
| 31:0 | magic | const | 0x53410001 | 'SA' 0001 |

## VERSION (0x004)

Register map version (major << 16 \| minor). Equals [map] version.

| Bits | Name | Access | Reset | Description |
|---|---|---|---|---|
| 31:0 | version | const | 0x10000 | must equal map.version (gen_regs.py checks) |

## CTRL (0x008)

Control. Pulse bits read 0.

| Bits | Name | Access | Reset | Description |
|---|---|---|---|---|
| 6 | irq_ack | w1p | 0x0 | Clear STATUS.done (and so the irq). |
| 5 | stop_on_err | rw | 0x0 | 1 = end the sweep at the first lock timeout (done and err_lock set). 0 = flag the point and continue. |
| 4 | pin_owner | rw | 0x0 | Requested owner of the ADF4351 SPI pins and the PE4302 pins: 0 = PS (EMIO), 1 = engine. Takes effect only while idle (see STATUS.pin_owner_act). |
| 3 | irq_en | rw | 0x0 | irq output = irq_en AND STATUS.done. |
| 2 | soft_reset | w1p | 0x0 | Reset the sequencer and status bits. Configuration registers and the tables keep their content. |
| 1 | abort | w1p | 0x0 | Stop the running sweep after the current SPI word; sets aborted. No effect when idle. |
| 0 | start | w1p | 0x0 | Start a sweep over table entries 0..N_ENTRIES-1. Ignored while busy. Clears done, err_lock, aborted, err_table. |

## STATUS (0x00C)

Status, read-only.

| Bits | Name | Access | Reset | Description |
|---|---|---|---|---|
| 11:8 | state | ro | 0x0 | Sequencer state, for debugging (encoding in rtl-spec.md). |
| 7 | pin_owner_act | ro | 0x0 | Owner in effect: follows CTRL.pin_owner while not busy. |
| 6 | err_table | ro | 0x0 | Sticky: start was refused (N_ENTRIES = 0 or above the table depth, or pin_owner_act = 0) or the result memory overflowed. Cleared by start, soft_reset. |
| 5 | wait_sample | ro | 0x0 | The sequencer is in SAMPLE and waits for detector samples (with DET_CFG.src = 0 the PS must write DET_PUSH now). |
| 4 | ld_now | ro | 0x0 | Synchronised live level of the ADF4351 lock detect pin. |
| 3 | aborted | ro | 0x0 | Sticky: the last sweep was ended by abort. Cleared by start, soft_reset. |
| 2 | err_lock | ro | 0x0 | Sticky: at least one measured point timed out waiting for lock detect. Cleared by start, soft_reset. |
| 1 | done | ro | 0x0 | Sticky: the last sweep ended (normally, by stop_on_err, or by abort). Cleared by start, irq_ack, soft_reset. |
| 0 | busy | ro | 0x0 | A sweep is running. |

## N_ENTRIES (0x010)

Number of table entries one sweep executes (1 .. 2^TABLE_AW).

| Bits | Name | Access | Reset | Description |
|---|---|---|---|---|
| 15:0 | n | rw | 0x0 |  |

## N_AVG (0x014)

Detector samples summed per measured point (1 .. 4095). 0 is treated as 1.

| Bits | Name | Access | Reset | Description |
|---|---|---|---|---|
| 11:0 | n | rw | 0x1 |  |

## SPI_DIV (0x018)

ADF4351 SPI half bit period in clk cycles (f_sclk = f_clk / (2 * div)). Values below 2 are treated as 2. Reset 5 = 10 MHz at 100 MHz.

| Bits | Name | Access | Reset | Description |
|---|---|---|---|---|
| 7:0 | div | rw | 0x5 |  |

## T_ATT_GAP_CYC (0x01C)

PE4302 make-before-break: clk cycles the intermediate (make) state is held, and again after the final state before the entry continues.

| Bits | Name | Access | Reset | Description |
|---|---|---|---|---|
| 15:0 | cycles | rw | 0x64 | 100 = 1 us at 100 MHz |

## T_MIN_US (0x020)

Microseconds after the last SPI word of a measured entry during which lock detect is ignored (VCO band selection).

| Bits | Name | Access | Reset | Description |
|---|---|---|---|---|
| 19:0 | us | rw | 0xC8 |  |

## T_LOCK_STABLE_US (0x024)

Lock detect must stay high for this long without a break to count as locked.

| Bits | Name | Access | Reset | Description |
|---|---|---|---|---|
| 19:0 | us | rw | 0x32 |  |

## T_LOCK_TIMEOUT_US (0x028)

Give up waiting for lock after this long (counted from the end of T_MIN_US).

| Bits | Name | Access | Reset | Description |
|---|---|---|---|---|
| 19:0 | us | rw | 0x2710 |  |

## T_SETTLE_US (0x02C)

Detector settling time between lock (or timeout) and the first sample.

| Bits | Name | Access | Reset | Description |
|---|---|---|---|---|
| 19:0 | us | rw | 0x1F4 |  |

## PE4302 (0x030)

PE4302 pin control of the engine. Reset state = all stages in (31.5 dB) for an active-high module.

| Bits | Name | Access | Reset | Description |
|---|---|---|---|---|
| 8 | active_high | rw | 0x1 | 1 = a high pin switches the stage in (make state = old OR new). 0 = low switches in (make state = old AND new). |
| 5:0 | manual | rw | 0x3F | Pin levels V1..V6 (bit 0 = V1). A write while the engine owns the pins and is idle moves the pins there, make-before-break, if they differ. A write at any other time only stores the value. Taking the pins loads this value directly. |

## PIN_STATE (0x034)

Live pins after the pin mux, synchronised to clk.

| Bits | Name | Access | Reset | Description |
|---|---|---|---|---|
| 29:24 | pe_t | ro | 0x0 | 1 = that PE4302 pin is not driven (PS owner with the GPIO line as input). |
| 21:16 | pe_out | ro | 0x0 | Levels driven on the PE4302 pins (meaningful where pe_t = 0). |
| 11 | dat | ro | 0x0 | adf4351_dat as driven |
| 10 | clk | ro | 0x0 | adf4351_clk as driven |
| 9 | le | ro | 0x0 | adf4351_le as driven |
| 8 | ld | ro | 0x0 | adf4351_ld |
| 5:0 | pe_in | ro | 0x0 | Levels read back from the PE4302 pins. |

## DET_CFG (0x038)

Detector sample source.

| Bits | Name | Access | Reset | Description |
|---|---|---|---|---|
| 1:0 | src | rw | 0x0 | 0 = PS push (DET_PUSH), 1 = test generator (DET_TEST), 2 = external stream (det_ext_*, the PL ADC reader of S10), 3 = reserved (no samples). |

## DET_TEST (0x03C)

Test generator: sample = (base + low 8 bits of the result index) mod 65536, one sample per microsecond tick while the sequencer is in SAMPLE.

| Bits | Name | Access | Reset | Description |
|---|---|---|---|---|
| 15:0 | base | rw | 0x0 |  |

## DET_PUSH (0x040) ext

Write: one detector sample (bits 15:0) for DET_CFG.src = 0. Counted only while STATUS.wait_sample = 1; otherwise dropped. Reads 0.

| Bits | Name | Access | Reset | Description |
|---|---|---|---|---|
| 15:0 | sample | rw | 0x0 | unsigned ADC code |

## FIRST_ERR_INDEX (0x044)

Result index of the first point with a lock timeout in the last sweep (valid when STATUS.err_lock = 1).

| Bits | Name | Access | Reset | Description |
|---|---|---|---|---|
| 15:0 | index | ro | 0x0 |  |

## POINT_COUNT (0x048)

Results stored so far in the current / last sweep (= number of measured entries completed).

| Bits | Name | Access | Reset | Description |
|---|---|---|---|---|
| 15:0 | count | ro | 0x0 |  |

## SWEEP_COUNT (0x04C)

Sweeps completed since reset (normal end only), wraps.

| Bits | Name | Access | Reset | Description |
|---|---|---|---|---|
| 31:0 | count | ro | 0x0 |  |

## ENTRY_INDEX (0x050)

Table entry the sequencer is executing (or the one after the last, when done).

| Bits | Name | Access | Reset | Description |
|---|---|---|---|---|
| 15:0 | index | ro | 0x0 |  |

## TABLE_ADDR (0x060) ext

Table entry index for the next TABLE_W1 write. Read / write; increments by one on every TABLE_W1 write. Writes are ignored while busy.

| Bits | Name | Access | Reset | Description |
|---|---|---|---|---|
| 15:0 | index | rw | 0x0 |  |

## TABLE_W0 (0x064)

Word 0 of the table entry being written: the 32-bit SPI word (sent MSB first).

| Bits | Name | Access | Reset | Description |
|---|---|---|---|---|
| 31:0 | word | rw | 0x0 |  |

## TABLE_W1 (0x068) ext

Word 1 of the table entry (flags). Writing it stores {W1, TABLE_W0} at TABLE_ADDR and increments TABLE_ADDR. Ignored while busy. Reads 0.

| Bits | Name | Access | Reset | Description |
|---|---|---|---|---|
| 11 | skip_lock | rw | 0x0 | with measure: do not wait for lock detect (debug, or no LD wired) |
| 10 | measure | rw | 0x0 | after the SPI word: wait, lock, settle, sample, store one result |
| 9 | att_en | rw | 0x0 | apply att, make-before-break, before the SPI word |
| 8 | spi_en | rw | 0x0 | send word 0 to the ADF4351 |
| 5:0 | att | rw | 0x0 | PE4302 pin levels V1..V6 (bit 0 = V1), used when att_en = 1 |

## RESULT_ADDR (0x070) ext

Result index for the next RESULT_DATA read. Read / write; increments by one on every RESULT_DATA read.

| Bits | Name | Access | Reset | Description |
|---|---|---|---|---|
| 15:0 | index | rw | 0x0 |  |

## RESULT_DATA (0x074) ext

Result word at RESULT_ADDR (read-only, read increments RESULT_ADDR). Wait at least 2 clk cycles after writing RESULT_ADDR (always true from the PS).

| Bits | Name | Access | Reset | Description |
|---|---|---|---|---|
| 31 | unlocked | ro | 0x0 | lock detect timed out for this point |
| 27:0 | sum | ro | 0x0 | sum of N_AVG samples |

## CAPS (0x078)

Build parameters.

| Bits | Name | Access | Reset | Description |
|---|---|---|---|---|
| 31:16 | clk_mhz | ro | 0x0 | fabric clock in MHz (the microsecond tick divides by this) |
| 15:8 | result_aw | ro | 0x0 | result depth = 2^result_aw points |
| 7:0 | table_aw | ro | 0x0 | table depth = 2^table_aw entries |
