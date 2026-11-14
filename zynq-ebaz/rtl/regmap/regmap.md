<!-- generated from regmap.toml by gen_regs.py, do not edit -->
# Register map

Map `sadiy`, version 0x00010002, 12-bit address, 32-bit registers. Writes are full words (WSTRB ignored); bits without a field read 0.
Registers marked *ext* are implemented outside `axil_regs.sv`.

| Offset | Name | Reset | Description |
|---|---|---|---|
| 0x000 | ID | 0x53410001 | Magic number, identifies the core. |
| 0x004 | VERSION | 0x00010002 | Register map version (major << 16 \| minor). Equals [map] version. |
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
| 0x080 | ADC_CFG | 0x0048C3E3 | ADS1115 reader (DET_CFG.src = 3): what is written to the ADC for every sample. |
| 0x084 | ADC_I2C_DIV | 0x00000046 | ADS1115 reader: I2C quarter bit period in clk cycles (f_scl = f_clk / (4 * div)). Values below 4 are treated as 4. Reset 70 = 357 kHz at 100 MHz (t_low 1.4 us). |
| 0x088 | ADC_T_CONV_US | 0x00000578 | ADS1115 reader: microseconds between the config write (conversion start) and the read. Must exceed the conversion time of the data rate in ADC_CFG.config plus its 10 % tolerance. Reset 1400 for 860 SPS. |
| 0x08C | ADC_STAT | 0x00000000 | ADS1115 reader status, read-only. |
| 0x090 | ADF_PINS | 0x00000001 | ADF4351 pins outside the SPI, driven while the engine owns the pins. |
| 0x0A0 | GEN_CFG | 0x400003E8 | Sample generator: plays the pattern written through GEN_ADDR / GEN_DATA as a sample stream, in place of an ADC. |
| 0x0A4 | GEN_ADDR (ext) | 0x00000000 | Pattern index for the next GEN_DATA write. Read / write; increments by one on every GEN_DATA write. |
| 0x0A8 | GEN_DATA (ext) | 0x00000000 | Write: one pattern sample (stream format: 16 bit two's complement) to GEN_ADDR, then GEN_ADDR + 1. Reads 0. Write only while the generator is disabled or idle. |
| 0x0B0 | IF_NCO | 0x00000000 | IF path: NCO phase increment of the first point of a sweep (f = inc * fs / 2^32, two's complement for negative frequencies). |
| 0x0B4 | IF_NCO_STEP | 0x00000000 | IF path: added to the NCO increment at every further measured point of the sweep (digital sweep inside the IF window). 0 = the same IF for all points. |
| 0x0B8 | IF_CIC | 0x040B0010 | IF path: decimating filter. The resolution bandwidth is about fs / r. |

## ID (0x000)

Magic number, identifies the core.

| Bits | Name | Access | Reset | Description |
|---|---|---|---|---|
| 31:0 | magic | const | 0x53410001 | 'SA' 0001 |

## VERSION (0x004)

Register map version (major << 16 \| minor). Equals [map] version.

| Bits | Name | Access | Reset | Description |
|---|---|---|---|---|
| 31:0 | version | const | 0x10002 | must equal map.version (gen_regs.py checks) |

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
| 15 | i2c_pl | ro | 0x0 | 1 = the ADS1115 reader of the PL owns the I2C pins (engine owns the pins and DET_CFG.src = 3); 0 = PS I2C0. |
| 14 | sda | ro | 0x0 | i2c_sda pad level |
| 13 | scl | ro | 0x0 | i2c_scl pad level |
| 12 | ce | ro | 0x0 | adf4351_ce pad level |
| 11 | dat | ro | 0x0 | adf4351_dat as driven |
| 10 | clk | ro | 0x0 | adf4351_clk as driven |
| 9 | le | ro | 0x0 | adf4351_le as driven |
| 8 | ld | ro | 0x0 | adf4351_ld |
| 5:0 | pe_in | ro | 0x0 | Levels read back from the PE4302 pins. |

## DET_CFG (0x038)

Detector sample source.

| Bits | Name | Access | Reset | Description |
|---|---|---|---|---|
| 8 | stream | rw | 0x0 | Sample stream for src = 2 and for the IF path: 0 = det_ext_* port of sadiy_top (an ADC adapter), 1 = sample generator (GEN_* registers). |
| 4 | mode | rw | 0x0 | 0 = video path: a result is the sum of N_AVG detector samples. 1 = IF path: the sample stream goes through NCO, mixer, CIC and power detector (IF_* registers); a result is {exp[5:0], mant[21:0]} of the power sum, bit 30 = over-range. |
| 1:0 | src | rw | 0x0 | Video path (mode = 0): 0 = PS push (DET_PUSH), 1 = test generator (DET_TEST), 2 = sample stream selected by `stream` (negative samples count as 0), 3 = ADS1115 reader in the PL (ADC_* registers; the engine then owns the I2C pins while it owns the other pins). |

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

## ADC_CFG (0x080)

ADS1115 reader (DET_CFG.src = 3): what is written to the ADC for every sample.

| Bits | Name | Access | Reset | Description |
|---|---|---|---|---|
| 22:16 | addr | rw | 0x48 | I2C address of the ADS1115 (0x48 = ADDR pin to GND). |
| 15:0 | config | rw | 0xC3E3 | ADS1115 config register word, written before every sample; must have OS = 1 and MODE = 1 (single shot). Reset: AIN0 to GND, +/-4.096 V, 860 SPS, comparator off. |

## ADC_I2C_DIV (0x084)

ADS1115 reader: I2C quarter bit period in clk cycles (f_scl = f_clk / (4 * div)). Values below 4 are treated as 4. Reset 70 = 357 kHz at 100 MHz (t_low 1.4 us).

| Bits | Name | Access | Reset | Description |
|---|---|---|---|---|
| 11:0 | div | rw | 0x46 |  |

## ADC_T_CONV_US (0x088)

ADS1115 reader: microseconds between the config write (conversion start) and the read. Must exceed the conversion time of the data rate in ADC_CFG.config plus its 10 % tolerance. Reset 1400 for 860 SPS.

| Bits | Name | Access | Reset | Description |
|---|---|---|---|---|
| 19:0 | us | rw | 0x578 |  |

## ADC_STAT (0x08C)

ADS1115 reader status, read-only.

| Bits | Name | Access | Reset | Description |
|---|---|---|---|---|
| 31:24 | count | ro | 0x0 | Conversions read since reset, wraps. |
| 17 | busy | ro | 0x0 | A sample (bus transaction or conversion wait) is in progress. |
| 16 | err_nack | ro | 0x0 | Sticky: the ADC did not acknowledge (missing, wrong address, bus held). That sample was delivered as 0. Cleared by start and soft_reset. |
| 15:0 | last | ro | 0x0 | Conversion register of the last sample as read from the ADC (two's complement). |

## ADF_PINS (0x090)

ADF4351 pins outside the SPI, driven while the engine owns the pins.

| Bits | Name | Access | Reset | Description |
|---|---|---|---|---|
| 0 | ce | rw | 0x1 | Level of adf4351_ce while the engine owns the pins (1 = chip enabled). With the PS as owner the pin follows EMIO GPIO 6. |

## GEN_CFG (0x0A0)

Sample generator: plays the pattern written through GEN_ADDR / GEN_DATA as a sample stream, in place of an ADC.

| Bits | Name | Access | Reset | Description |
|---|---|---|---|---|
| 31 | enable | rw | 0x0 | 1 = play. |
| 30 | sync | rw | 0x1 | 1 = the playback restarts at sample 0 when a measurement (SAMPLE) starts, so results are repeatable. 0 = free running like an ADC. |
| 27:16 | len_m1 | rw | 0x0 | Last sample index of the pattern (length - 1); the playback wraps to 0 after it. |
| 15:0 | div | rw | 0x3E8 | clk cycles per sample (0 and 1 = one sample every clock). Reset 1000 = 100 kSPS at 100 MHz. |

## GEN_ADDR (0x0A4) ext

Pattern index for the next GEN_DATA write. Read / write; increments by one on every GEN_DATA write.

| Bits | Name | Access | Reset | Description |
|---|---|---|---|---|
| 11:0 | index | rw | 0x0 |  |

## GEN_DATA (0x0A8) ext

Write: one pattern sample (stream format: 16 bit two's complement) to GEN_ADDR, then GEN_ADDR + 1. Reads 0. Write only while the generator is disabled or idle.

| Bits | Name | Access | Reset | Description |
|---|---|---|---|---|
| 15:0 | sample | rw | 0x0 |  |

## IF_NCO (0x0B0)

IF path: NCO phase increment of the first point of a sweep (f = inc * fs / 2^32, two's complement for negative frequencies).

| Bits | Name | Access | Reset | Description |
|---|---|---|---|---|
| 31:0 | inc | rw | 0x0 |  |

## IF_NCO_STEP (0x0B4)

IF path: added to the NCO increment at every further measured point of the sweep (digital sweep inside the IF window). 0 = the same IF for all points.

| Bits | Name | Access | Reset | Description |
|---|---|---|---|---|
| 31:0 | step | rw | 0x0 |  |

## IF_CIC (0x0B8)

IF path: decimating filter. The resolution bandwidth is about fs / r.

| Bits | Name | Access | Reset | Description |
|---|---|---|---|---|
| 27:24 | skip | rw | 0x4 | Filter outputs dropped at the start of every measurement (settling; at least 3). |
| 21:16 | shift | rw | 0xB | Arithmetic right shift after the filter, before the saturation to 18 bit; about 3 * log2(r) - 1. |
| 15:0 | r | rw | 0x10 | Decimation factor of the 3-stage CIC (1 .. 65535; 0 is treated as 1). Gain r^3. |
