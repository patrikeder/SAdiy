// Self-checking testbench for sadiy_top through its AXI-lite interface (docs/rtl-spec.md section 10).
// Vectors (vectors/sweep_*.hex) come from the Python model, so RTL and model are checked against
// each other: the SPI words seen on the pins and the result words must be identical.
// Scenarios: refused start, taking the pins, full sweep with a lock model (two points time out),
// irq / irq_ack, stop_on_err, PS-pushed samples, abort, table write while busy, manual attenuator
// change, soft reset, pins handed back to the PS, and "no SPI word that is not in the table".
`timescale 1ns / 1ps
module tb_sweep;
  // register offsets (rtl/regmap/regmap.md)
  localparam logic [11:0] ID = 12'h000, VERSION = 12'h004, CTRL = 12'h008, STATUS = 12'h00C,
    N_ENTRIES = 12'h010, N_AVG = 12'h014, SPI_DIV = 12'h018, T_ATT_GAP = 12'h01C, T_MIN = 12'h020,
    T_STABLE = 12'h024, T_TIMEOUT = 12'h028, T_SETTLE = 12'h02C, PE4302 = 12'h030,
    PIN_STATE = 12'h034, DET_CFG = 12'h038, DET_TEST = 12'h03C, DET_PUSH = 12'h040,
    FIRST_ERR = 12'h044, POINT_COUNT = 12'h048, SWEEP_COUNT = 12'h04C, ENTRY_INDEX = 12'h050,
    TABLE_ADDR = 12'h060, TABLE_W0 = 12'h064, TABLE_W1 = 12'h068, RESULT_ADDR = 12'h070,
    RESULT_DATA = 12'h074, CAPS = 12'h078;
  localparam logic [31:0] C_START = 32'h01, C_ABORT = 32'h02, C_SRST = 32'h04, C_IRQ_EN = 32'h08,
    C_OWNER = 32'h10, C_STOP = 32'h20, C_ACK = 32'h40;
  localparam logic [31:0] S_BUSY = 32'h01, S_DONE = 32'h02, S_ERR_LOCK = 32'h04, S_ABORTED = 32'h08,
    S_WAIT = 32'h20, S_ERR_TABLE = 32'h40, S_OWNER = 32'h80;

  logic clk = 0, resetn = 0;
  always #5 clk = ~clk;

  logic [11:0] awaddr = '0, araddr = '0;
  logic [31:0] wdata = '0, rdata;
  logic awvalid = 0, wvalid = 0, bready = 0, arvalid = 0, rready = 0;
  logic awready, wready, bvalid, arready, rvalid;
  logic [1:0] bresp, rresp;
  logic irq;
  logic emio_clk = 0, emio_dat = 0, emio_le = 1;
  logic [5:0] emio_pe_o = 6'h00, emio_pe_t = 6'h3F;
  logic adf_clk, adf_dat, adf_le, ld = 0;
  logic [5:0] pe_o, pe_t;
  wire  [5:0] pe_pad = pe_t | pe_o;              // not driven = pulled up on the adapter

  sadiy_top dut (
    .clk, .resetn,
    .s_axil_awaddr(awaddr), .s_axil_awvalid(awvalid), .s_axil_awready(awready),
    .s_axil_wdata(wdata), .s_axil_wstrb(4'hF), .s_axil_wvalid(wvalid), .s_axil_wready(wready),
    .s_axil_bresp(bresp), .s_axil_bvalid(bvalid), .s_axil_bready(bready),
    .s_axil_araddr(araddr), .s_axil_arvalid(arvalid), .s_axil_arready(arready),
    .s_axil_rdata(rdata), .s_axil_rresp(rresp), .s_axil_rvalid(rvalid), .s_axil_rready(rready),
    .irq,
    .emio_adf_clk(emio_clk), .emio_adf_dat(emio_dat), .emio_adf_le(emio_le),
    .emio_pe_o, .emio_pe_t,
    .adf4351_clk(adf_clk), .adf4351_dat(adf_dat), .adf4351_le(adf_le), .adf4351_ld(ld),
    .pe4302_v_o(pe_o), .pe4302_v_t(pe_t), .pe4302_v_i(pe_pad),
    .det_ext_valid(1'b0), .det_ext_data(16'd0)
  );

  task automatic fail(input string why);
    $display("TB FAIL: %s (time %0t)", why, $time);
    $finish;
  endtask

  // ---- AXI-lite master ----
  task automatic wr(input logic [11:0] a, input logic [31:0] d);
    @(posedge clk); awaddr <= a; wdata <= d; awvalid <= 1; wvalid <= 1; bready <= 1;
    fork
      begin do @(posedge clk); while (!awready); awvalid <= 0; end
      begin do @(posedge clk); while (!wready);  wvalid  <= 0; end
    join
    while (!bvalid) @(posedge clk);
    if (bresp !== 2'b00) fail("write response not OKAY");
    @(posedge clk); bready <= 0;
  endtask

  task automatic rd(input logic [11:0] a, output logic [31:0] d);
    @(posedge clk); araddr <= a; arvalid <= 1; rready <= 1;
    do @(posedge clk); while (!arready);
    arvalid <= 0;
    while (!rvalid) @(posedge clk);
    d = rdata;
    if (rresp !== 2'b00) fail("read response not OKAY");
    @(posedge clk); rready <= 0;
  endtask

  task automatic expect_reg(input logic [11:0] a, input logic [31:0] want, input string what);
    logic [31:0] d;
    rd(a, d);
    if (d !== want) fail($sformatf("%s: read %08x, expected %08x", what, d, want));
  endtask

  task automatic expect_status(input logic [31:0] mask, input logic [31:0] want, input string what);
    logic [31:0] d;
    rd(STATUS, d);
    if ((d & mask) !== want) fail($sformatf("%s: STATUS %08x, masked %08x, expected %08x", what, d, d & mask, want));
  endtask

  task automatic wait_status(input logic [31:0] mask, input logic [31:0] want, input string what);
    logic [31:0] d;
    for (int i = 0; i < 200000; i++) begin
      rd(STATUS, d);
      if ((d & mask) === want) return;
    end
    fail({"timeout waiting for ", what});
  endtask

  // ---- ADF4351 side: decode every frame on the pins ----
  logic [31:0] sh, spi_seen [0:8191];
  int nbits, n_seen = 0, r0_count = 0, lock_gen = 0;
  bit use_unlock_vec = 0, mon_en = 1;        // mon_en: the engine owns the pins
  logic [3:0] unlock_vec [0:4095];
  always @(negedge adf_le) begin nbits = 0; sh = '0; end
  always @(posedge adf_clk) begin sh = {sh[30:0], adf_dat}; nbits++; end
  always @(posedge adf_le) if (resetn && mon_en) begin
    if (nbits != 32) fail($sformatf("frame with %0d bits on the pins", nbits));
    spi_seen[n_seen] = sh; n_seen++;
    if (sh[2:0] == 3'd0) begin                  // R0: the PLL relocks, unless this point is to fail
      automatic int r = r0_count;
      automatic int g = ++lock_gen;
      r0_count++;
      ld = 0;
      if (!(use_unlock_vec && unlock_vec[r][0])) fork
        begin #60us; if (g == lock_gen) ld = 1; end
      join_none
    end
  end

  // ---- PE4302 pins: record every state the engine drives ----
  logic [5:0] pe_hist [0:255];
  int n_pe = 0;
  logic [5:0] pe_last = 6'h3F;
  always @(posedge clk) if (pe_t == 6'h00 && pe_o !== pe_last) begin
    pe_hist[n_pe] = pe_o; n_pe++; pe_last = pe_o;
  end

  // ---- vectors ----
  logic [63:0] v_table [0:4095];
  logic [31:0] v_spi [0:8191], v_result [0:4095], v_meta [0:5];
  int n_entries, n_results, n_avg, det_base, att_pins, n_spi;
  int expect_spi_total = 0;

  task automatic load_table(input int n);
    wr(TABLE_ADDR, 0);
    for (int i = 0; i < n; i++) begin
      wr(TABLE_W0, v_table[i][31:0]);
      wr(TABLE_W1, v_table[i][63:32]);
    end
    expect_reg(TABLE_ADDR, n, "TABLE_ADDR after upload");
  endtask

  task automatic entry(input int idx, input logic [31:0] w0, input logic [31:0] w1);
    wr(TABLE_ADDR, idx); wr(TABLE_W0, w0); wr(TABLE_W1, w1);
  endtask

  logic [31:0] d;
  int seen0;

  initial begin
    $readmemh("vectors/sweep_meta.hex", v_meta);
    n_entries = v_meta[0]; n_results = v_meta[1]; n_avg = v_meta[2];
    det_base = v_meta[3]; att_pins = v_meta[4]; n_spi = v_meta[5];
    $readmemh("vectors/sweep_table.hex", v_table, 0, n_entries - 1);
    $readmemh("vectors/sweep_spi.hex", v_spi, 0, n_spi - 1);
    $readmemh("vectors/sweep_result.hex", v_result, 0, n_results - 1);
    $readmemh("vectors/sweep_unlock.hex", unlock_vec, 0, n_results - 1);
    repeat (5) @(posedge clk);
    resetn = 1;
    repeat (5) @(posedge clk);

    // 1. identity, reset state: PS owns the pins, PE4302 not driven
    expect_reg(ID, 32'h53410001, "ID");
    expect_reg(VERSION, 32'h00010000, "VERSION");
    expect_reg(CAPS, {16'd100, 8'd12, 8'd12}, "CAPS");
    expect_reg(PE4302, 32'h0000013F, "PE4302 reset");
    if (pe_t !== 6'h3F || adf_le !== 1 || adf_clk !== 0) fail("pins after reset");

    // 2. PS path: pins follow EMIO
    emio_pe_o = 6'h2C; emio_pe_t = 6'h03; emio_dat = 1;
    repeat (3) @(posedge clk);
    if (pe_o !== 6'h2C || pe_t !== 6'h03 || adf_dat !== 1) fail("PS owner: pins do not follow EMIO");
    emio_pe_t = 6'h3F; emio_dat = 0;

    // 3. start without owning the pins is refused
    wr(N_ENTRIES, 4);
    wr(CTRL, C_START);
    wait_status(S_BUSY, 0, "refused start to end");
    expect_status(S_DONE | S_ERR_TABLE | S_OWNER, S_DONE | S_ERR_TABLE, "start refused without the pins");

    // 3b. taking the pins and start in one write: the pins are taken, the start is refused
    wr(N_ENTRIES, 4);
    wr(CTRL, C_OWNER | C_START);
    wait_status(S_BUSY, 0, "refused start to end");
    expect_status(S_DONE | S_ERR_TABLE | S_OWNER, S_DONE | S_ERR_TABLE | S_OWNER, "owner and start in one write");

    // 4. take the pins: PE4302 = manual (all in), no SPI activity
    wr(CTRL, C_OWNER);
    wait_status(S_OWNER, S_OWNER, "pin_owner_act");
    repeat (3) @(posedge clk);
    if (pe_t !== 6'h00 || pe_o !== 6'h3F) fail("engine owner: PE4302 not at the manual value");
    if (n_seen != 0) fail("SPI activity before any start");
    rd(PIN_STATE, d);
    if (d[5:0] !== 6'h3F || d[21:16] !== 6'h3F || d[29:24] !== 6'h00 || d[9] !== 1'b1) fail("PIN_STATE");

    // 5. N_ENTRIES = 0 is refused
    wr(N_ENTRIES, 0);
    wr(CTRL, C_OWNER | C_START);
    wait_status(S_BUSY, 0, "refused start to end");
    expect_status(S_DONE | S_ERR_TABLE, S_DONE | S_ERR_TABLE, "N_ENTRIES = 0 refused");

    // 6. the vector sweep: test generator, points 5 and 17 never lock
    wr(T_MIN, 20); wr(T_STABLE, 5); wr(T_TIMEOUT, 300); wr(T_SETTLE, 10); wr(T_ATT_GAP, 50);
    wr(DET_CFG, 1); wr(DET_TEST, det_base); wr(N_AVG, n_avg);
    load_table(n_entries);
    wr(N_ENTRIES, n_entries);
    use_unlock_vec = 1; r0_count = 0; n_pe = 0;
    wr(CTRL, C_OWNER | C_IRQ_EN | C_START);
    fork
      begin wait (irq); end
      begin #400ms; fail("no interrupt from the vector sweep"); end
    join_any
    disable fork;
    expect_status(S_BUSY | S_DONE | S_ERR_LOCK | S_ABORTED | S_ERR_TABLE, S_DONE | S_ERR_LOCK, "after the sweep");
    expect_reg(POINT_COUNT, n_results, "POINT_COUNT");
    expect_reg(ENTRY_INDEX, n_entries, "ENTRY_INDEX");
    expect_reg(SWEEP_COUNT, 1, "SWEEP_COUNT");
    expect_reg(FIRST_ERR, 5, "FIRST_ERR_INDEX");
    if (n_seen != n_spi) fail($sformatf("%0d SPI words on the pins, expected %0d", n_seen, n_spi));
    for (int i = 0; i < n_spi; i++)
      if (spi_seen[i] !== v_spi[i]) fail($sformatf("SPI word %0d: %08x, expected %08x", i, spi_seen[i], v_spi[i]));
    wr(RESULT_ADDR, 0);
    for (int i = 0; i < n_results; i++) begin
      rd(RESULT_DATA, d);
      if (d !== v_result[i]) fail($sformatf("result %0d: %08x, expected %08x", i, d, v_result[i]));
    end
    expect_reg(RESULT_ADDR, n_results, "RESULT_ADDR auto-increment");
    if (pe_o !== att_pins[5:0]) fail("PE4302 pins after the sweep");
    for (int i = 0; i < n_pe; i++)
      if (i < n_pe - 1 && pe_hist[i] !== 6'h3F) fail("unexpected intermediate PE4302 state");
    expect_spi_total = n_spi;
    // irq_ack
    wr(CTRL, C_OWNER | C_IRQ_EN | C_ACK);
    expect_status(S_DONE | S_ERR_LOCK, S_ERR_LOCK, "irq_ack clears done only");
    if (irq) fail("irq still high after irq_ack");

    // 7. same table with stop_on_err: ends at point 5, no result for it, not a completed sweep
    use_unlock_vec = 1; r0_count = 0; seen0 = n_seen;
    wr(CTRL, C_OWNER | C_STOP | C_START);
    wait_status(S_BUSY | S_DONE, S_DONE, "stop_on_err sweep to end");
    expect_status(S_ERR_LOCK | S_ABORTED | S_ERR_TABLE, S_ERR_LOCK, "stop_on_err");
    expect_reg(POINT_COUNT, 5, "POINT_COUNT with stop_on_err");
    expect_reg(FIRST_ERR, 5, "FIRST_ERR_INDEX with stop_on_err");
    expect_reg(SWEEP_COUNT, 1, "SWEEP_COUNT unchanged by a stopped sweep");
    for (int i = seen0; i < n_seen; i++)
      if (spi_seen[i] !== v_spi[i - seen0]) fail("stop_on_err run sent a different word");
    expect_spi_total = n_seen;
    use_unlock_vec = 0;

    // 8. manual attenuator change while idle: make-before-break from the table's last value
    n_pe = 0;
    wr(PE4302, 32'h100 | (~att_pins & 32'h3F));
    repeat (200) @(posedge clk);
    if (n_pe != 2 || pe_hist[0] !== 6'h3F || pe_hist[1] !== (~att_pins[5:0]))
      fail($sformatf("manual change: %0d states, %02x %02x", n_pe, pe_hist[0], pe_hist[1]));

    // 8b. writing the value the pins already have changes nothing
    n_pe = 0;
    wr(PE4302, 32'h100 | (~att_pins & 32'h3F));
    repeat (200) @(posedge clk);
    if (n_pe != 0) fail("PE4302 write of the present value moved the pins");

    // 9. PS-pushed samples (src 0), two points, skip_lock; a push outside SAMPLE is dropped
    wr(DET_CFG, 0); wr(N_AVG, 3);
    wr(DET_PUSH, 32'h0000FFFF);                              // dropped: not sampling
    entry(0, 32'hCAFE0001, 32'h00000D00);                    // spi_en | measure | skip_lock
    entry(1, 32'h00000000, 32'h00000C00);                    // measure | skip_lock, no SPI word
    wr(N_ENTRIES, 2);
    wr(CTRL, C_OWNER | C_START);
    wait_status(S_WAIT, S_WAIT, "wait_sample (point 0)");
    wr(DET_PUSH, 10); wr(DET_PUSH, 20);
    expect_status(S_WAIT | S_BUSY, S_WAIT | S_BUSY, "still sampling after 2 of 3");
    wr(DET_PUSH, 30);
    wait_status(S_WAIT, S_WAIT, "wait_sample (point 1)");
    expect_reg(POINT_COUNT, 1, "POINT_COUNT between points");
    // a pin owner request during a sweep waits: the engine keeps the pins until it is idle
    wr(CTRL, 0);
    repeat (5) @(posedge clk);
    expect_status(S_OWNER | S_BUSY, S_OWNER | S_BUSY, "pin owner must not change during a sweep");
    if (pe_t !== 6'h00) fail("PE4302 pins released during a sweep");
    wr(CTRL, C_OWNER);
    // table writes are ignored while busy
    rd(TABLE_ADDR, d);
    wr(TABLE_W1, 32'h00000100);
    expect_reg(TABLE_ADDR, d, "TABLE_ADDR unchanged by a write while busy");
    wr(DET_PUSH, 32'hFFFF); wr(DET_PUSH, 32'hFFFF); wr(DET_PUSH, 32'hFFFF);
    wait_status(S_BUSY | S_DONE, S_DONE, "pushed sweep to end");
    wr(RESULT_ADDR, 0);
    expect_reg(RESULT_DATA, 32'd60, "pushed result 0");
    expect_reg(RESULT_DATA, 32'h0002FFFD, "pushed result 1");
    expect_reg(SWEEP_COUNT, 2, "SWEEP_COUNT");
    expect_spi_total += 1;
    if (spi_seen[n_seen - 1] !== 32'hCAFE0001) fail("pushed sweep: SPI word");

    // 10. abort while waiting for samples
    wr(CTRL, C_OWNER | C_START);
    wait_status(S_WAIT, S_WAIT, "wait_sample before abort");
    wr(DET_PUSH, 5);
    wr(CTRL, C_OWNER | C_ABORT);
    wait_status(S_BUSY, 0, "abort");
    expect_status(S_DONE | S_ABORTED | S_ERR_LOCK | S_ERR_TABLE | S_WAIT, S_DONE | S_ABORTED, "after abort");
    expect_reg(POINT_COUNT, 0, "no result for the aborted point");
    expect_reg(SWEEP_COUNT, 2, "SWEEP_COUNT unchanged by abort");
    expect_spi_total += 1;

    // 11. soft reset in the middle of a sweep: idle, status clear, configuration kept
    wr(CTRL, C_OWNER | C_START);
    wait_status(S_WAIT, S_WAIT, "wait_sample before soft reset");
    wr(CTRL, C_OWNER | C_SRST);
    expect_status(32'hFFF, S_OWNER | (ld ? 32'h10 : 32'h0), "after soft reset");
    expect_reg(N_AVG, 3, "N_AVG kept over soft reset");
    expect_spi_total += 1;

    // 12. hand the pins back to the PS: no edge on LE / CLK, PE4302 follows EMIO again
    seen0 = n_seen; mon_en = 0;
    emio_pe_o = 6'h3F; emio_pe_t = 6'h00;
    wr(CTRL, 0);
    wait_status(S_OWNER, 0, "pins back to the PS");
    repeat (3) @(posedge clk);
    if (pe_o !== 6'h3F || pe_t !== 6'h00) fail("PS owner again: PE4302 pins");
    emio_le = 0; repeat (3) @(posedge clk);
    if (adf_le !== 0) fail("PS owner again: LE does not follow EMIO");
    emio_le = 1; repeat (3) @(posedge clk);

    // 13. the engine never sent a word that was not in a table
    if (seen0 != expect_spi_total)
      fail($sformatf("%0d SPI words from the engine, %0d were in the tables", seen0, expect_spi_total));

    $display("TB PASS  (%0d SPI words, %0d results checked)", seen0, n_results);
    $finish;
  end

  initial begin #2s; $display("TB FAIL: timeout"); $finish; end
endmodule
