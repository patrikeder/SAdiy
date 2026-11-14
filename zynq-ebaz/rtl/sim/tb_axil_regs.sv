// Self-checking testbench for the generated axil_regs (rtl/regmap/axil_regs.sv).
// Prints "TB PASS" once on success, "TB FAIL: <reason>" and stops on the first error.
// Timing convention of the checks: every signal is read at a rising clock edge (value of the clock
// that ends there); the testbench drives with non-blocking assignments, so there are no races.
// No `timescale on purpose: axil_regs.sv and rtl/src/*.sv have none (xelab rejects a mix); the default
// unit of xsim is 1 ns, so the #5 below gives a 100 MHz clock.

module tb_axil_regs;

  // ---------------------------------------------------------------- signals
  logic clk = 1'b0;
  logic resetn = 1'b0;

  logic [11:0] s_axil_awaddr = '0;
  logic        s_axil_awvalid = 1'b0;
  logic        s_axil_awready;
  logic [31:0] s_axil_wdata = '0;
  logic [3:0]  s_axil_wstrb = 4'hF;
  logic        s_axil_wvalid = 1'b0;
  logic        s_axil_wready;
  logic [1:0]  s_axil_bresp;
  logic        s_axil_bvalid;
  logic        s_axil_bready = 1'b0;
  logic [11:0] s_axil_araddr = '0;
  logic        s_axil_arvalid = 1'b0;
  logic        s_axil_arready;
  logic [31:0] s_axil_rdata;
  logic [1:0]  s_axil_rresp;
  logic        s_axil_rvalid;
  logic        s_axil_rready = 1'b0;

  logic [31:0] reg_wdata;
  logic ctrl_start;
  logic ctrl_abort;
  logic ctrl_soft_reset;
  logic ctrl_irq_en;
  logic ctrl_pin_owner;
  logic ctrl_stop_on_err;
  logic ctrl_irq_ack;
  logic status_busy = 1'b0;
  logic status_done = 1'b0;
  logic status_err_lock = 1'b0;
  logic status_aborted = 1'b0;
  logic status_ld_now = 1'b0;
  logic status_wait_sample = 1'b0;
  logic status_err_table = 1'b0;
  logic status_pin_owner_act = 1'b0;
  logic [3:0] status_state = '0;
  logic [15:0] n_entries_n;
  logic [11:0] n_avg_n;
  logic [7:0] spi_div_div;
  logic [15:0] t_att_gap_cyc_cycles;
  logic [19:0] t_min_us_us;
  logic [19:0] t_lock_stable_us_us;
  logic [19:0] t_lock_timeout_us_us;
  logic [19:0] t_settle_us_us;
  logic [5:0] pe4302_manual;
  logic pe4302_active_high;
  logic pe4302_wr;
  // wr_strobe register: count the strobes, and check the new value is there in the strobe clock
  int pe4302_wr_count = 0;
  logic [5:0] pe4302_manual_at_wr;
  always @(posedge clk) if (pe4302_wr) begin pe4302_wr_count++; pe4302_manual_at_wr = pe4302_manual; end
  logic [5:0] pin_state_pe_in = '0;
  logic pin_state_ld = 1'b0;
  logic pin_state_le = 1'b0;
  logic pin_state_clk = 1'b0;
  logic pin_state_dat = 1'b0;
  logic [5:0] pin_state_pe_out = '0;
  logic [5:0] pin_state_pe_t = '0;
  logic [1:0] det_cfg_src;
  logic [15:0] det_test_base;
  logic det_push_wr;
  logic det_push_rd;
  logic [31:0] det_push_rdata = 32'h0000_0000;
  logic [15:0] first_err_index_index = '0;
  logic [15:0] point_count_count = '0;
  logic [31:0] sweep_count_count = '0;
  logic [15:0] entry_index_index = '0;
  logic table_addr_wr;
  logic table_addr_rd;
  logic [31:0] table_addr_rdata = 32'h0000_0123;
  logic [31:0] table_w0_word;
  logic table_w1_wr;
  logic table_w1_rd;
  logic [31:0] table_w1_rdata = 32'h0000_0000;
  logic result_addr_wr;
  logic result_addr_rd;
  logic [31:0] result_addr_rdata = 32'h0000_0456;
  logic result_data_wr;
  logic result_data_rd;
  logic [31:0] result_data_rdata = 32'h1234_5678;   // changes every clock, see below
  logic [7:0] caps_table_aw = 8'd10;
  logic [7:0] caps_result_aw = 8'd12;
  logic [15:0] caps_clk_mhz = 16'd100;

  axil_regs dut (.*);

  // ---------------------------------------------------------------- clock, failure, timeout
  always #5 clk = ~clk;

  logic failed = 1'b0;
  task automatic fail(input string why);
    if (!failed) begin
      failed = 1'b1;
      $display("TB FAIL: %s", why);
      $finish;
    end
  endtask

  initial begin
    #2_000_000;
    fail("timeout");
  end

  // result_data_rdata changes every clock: a returned value must be the one of the foo_rd clock
  always @(posedge clk) result_data_rdata <= result_data_rdata * 32'd1664525 + 32'd1013904223;

  // ---------------------------------------------------------------- monitor
  localparam int NP = 14;
  logic [NP-1:0] pulses;
  assign pulses = {ctrl_start, ctrl_abort, ctrl_soft_reset, ctrl_irq_ack,
                   det_push_wr, table_addr_wr, table_w1_wr, result_addr_wr, result_data_wr,
                   det_push_rd, table_addr_rd, table_w1_rd, result_addr_rd, result_data_rd};
  // indexes (bit position in pulses)
  localparam int P_START = 13, P_ABORT = 12, P_SRST = 11, P_IACK = 10,
                 P_DET_WR = 9, P_TADDR_WR = 8, P_TW1_WR = 7, P_RADDR_WR = 6, P_RDATA_WR = 5,
                 P_DET_RD = 4, P_TADDR_RD = 3, P_TW1_RD = 2, P_RADDR_RD = 1, P_RDATA_RD = 0;

  int          pcnt [NP];
  int          ptotal;
  logic [NP-1:0] pprev = '0;
  logic [31:0] snap_wdata;          // reg_wdata in the clock of the last table_w1_wr
  logic [31:0] snap_rdata;          // result_data_rdata in the clock of the last result_data_rd
  logic        snap_start_irq_en, snap_start_pin_owner, snap_start_stop_on_err;
  logic [31:0] snap_start_wdata;

  task automatic clear_counts();
    for (int i = 0; i < NP; i++) pcnt[i] = 0;
    ptotal = 0;
  endtask
  initial clear_counts();

  always @(posedge clk) begin
    for (int i = 0; i < NP; i++) begin
      if (pulses[i]) begin
        pcnt[i]++;
        ptotal++;
        if (pprev[i]) fail($sformatf("pulse %0d wider than one clock", i));
      end
    end
    pprev <= pulses;
    // write-side pulses appear together with the first bvalid clock; read strobes with arready
    if (|pulses[NP-1:5] && !s_axil_bvalid) fail("write pulse / strobe without bvalid in the same clock");
    if (|pulses[4:0] && !s_axil_arready) fail("read strobe without arready in the same clock");
    if (table_w1_wr) snap_wdata <= reg_wdata;
    if (result_data_rd) snap_rdata <= result_data_rdata;
    if (ctrl_start) begin
      snap_start_irq_en <= ctrl_irq_en;
      snap_start_pin_owner <= ctrl_pin_owner;
      snap_start_stop_on_err <= ctrl_stop_on_err;
      snap_start_wdata <= reg_wdata;
    end
    // handshake protocol invariants
    if (s_axil_awready !== s_axil_wready) fail("awready != wready");
    if (s_axil_awready && !(s_axil_awvalid && s_axil_wvalid)) fail("awready without both valids");
    if (s_axil_awready && s_axil_bvalid) fail("awready while a write response is pending");
    if (s_axil_arready && s_axil_rvalid) fail("arready while a read response is pending");
    if (s_axil_bresp !== 2'b00 || s_axil_rresp !== 2'b00) fail("response not OKAY");
  end

  // ---------------------------------------------------------------- bus tasks
  task automatic wait_clks(input int n);
    repeat (n) @(posedge clk);
  endtask

  // AW and W with independent delays (in clocks) before valid is raised; returns after both are accepted
  task automatic axi_write_nob(input logic [11:0] addr, input logic [31:0] data,
                               input int aw_dly, input int w_dly);
    fork
      begin
        wait_clks(aw_dly);
        s_axil_awaddr <= addr;
        s_axil_awvalid <= 1'b1;
        for (int t = 0; ; t++) begin
          @(posedge clk);
          if (s_axil_awready) break;
          if (t > 50) fail("timeout waiting for awready");
        end
        s_axil_awvalid <= 1'b0;
      end
      begin
        wait_clks(w_dly);
        s_axil_wdata <= data;
        s_axil_wvalid <= 1'b1;
        for (int t = 0; ; t++) begin
          @(posedge clk);
          if (s_axil_wready) break;
          if (t > 50) fail("timeout waiting for wready");
        end
        s_axil_wvalid <= 1'b0;
      end
    join
  endtask

  // write response: bvalid must be held for b_dly clocks while bready is low, then accepted
  task automatic axi_b(input int b_dly);
    for (int t = 0; !s_axil_bvalid; t++) begin
      @(posedge clk);
      if (t > 50) fail("timeout waiting for bvalid");
    end
    repeat (b_dly) begin
      @(posedge clk);
      if (!s_axil_bvalid) fail("bvalid dropped before bready");
    end
    s_axil_bready <= 1'b1;
    @(posedge clk);
    if (!s_axil_bvalid) fail("bvalid missing when bready is high");
    s_axil_bready <= 1'b0;
  endtask

  task automatic axi_write(input logic [11:0] addr, input logic [31:0] data,
                           input int aw_dly = 0, input int w_dly = 0, input int b_dly = 0);
    axi_write_nob(addr, data, aw_dly, w_dly);
    axi_b(b_dly);
  endtask

  task automatic axi_read(input logic [11:0] addr, output logic [31:0] data,
                          input int ar_dly = 0, input int r_dly = 0);
    logic [31:0] first;
    wait_clks(ar_dly);
    s_axil_araddr <= addr;
    s_axil_arvalid <= 1'b1;
    for (int t = 0; ; t++) begin
      @(posedge clk);
      if (s_axil_arready) break;
      if (t > 50) fail("timeout waiting for arready");
    end
    s_axil_arvalid <= 1'b0;
    for (int t = 0; !s_axil_rvalid; t++) begin
      @(posedge clk);
      if (t > 50) fail("timeout waiting for rvalid");
    end
    first = s_axil_rdata;
    repeat (r_dly) begin
      @(posedge clk);
      if (!s_axil_rvalid) fail("rvalid dropped before rready");
      if (s_axil_rdata !== first) fail("rdata changed while rvalid waits for rready");
    end
    s_axil_rready <= 1'b1;
    @(posedge clk);
    if (!s_axil_rvalid) fail("rvalid missing when rready is high");
    data = s_axil_rdata;
    s_axil_rready <= 1'b0;
  endtask

  // ---------------------------------------------------------------- checks
  task automatic expect_eq(input logic [31:0] got, input logic [31:0] exp, input string what);
    if (got !== exp) fail($sformatf("%s: got 0x%08h, expected 0x%08h", what, got, exp));
  endtask

  task automatic rd_expect(input logic [11:0] addr, input logic [31:0] exp, input string what);
    logic [31:0] d;
    axi_read(addr, d);
    expect_eq(d, exp, what);
  endtask

  // let the monitor see everything of the previous operation, then compare
  task automatic expect_pulses(input int idx, input int n, input int total, input string what);
    wait_clks(2);
    #1;
    if (idx >= 0 && pcnt[idx] != n)
      fail($sformatf("%s: pulse %0d seen %0d times, expected %0d", what, idx, pcnt[idx], n));
    if (ptotal != total)
      fail($sformatf("%s: %0d pulses in total, expected %0d", what, ptotal, total));
    clear_counts();
  endtask

  // register addresses (byte offsets, as in regmap.toml)
  localparam logic [11:0] A_ID = 12'h000, A_VERSION = 12'h004, A_CTRL = 12'h008, A_STATUS = 12'h00C,
                          A_N_ENTRIES = 12'h010, A_N_AVG = 12'h014, A_SPI_DIV = 12'h018,
                          A_T_ATT_GAP = 12'h01C, A_T_MIN = 12'h020, A_T_STABLE = 12'h024,
                          A_T_TIMEOUT = 12'h028, A_T_SETTLE = 12'h02C, A_PE4302 = 12'h030,
                          A_PIN_STATE = 12'h034, A_DET_CFG = 12'h038, A_DET_TEST = 12'h03C,
                          A_DET_PUSH = 12'h040, A_FIRST_ERR = 12'h044, A_POINT_COUNT = 12'h048,
                          A_SWEEP_COUNT = 12'h04C, A_ENTRY_INDEX = 12'h050, A_TABLE_ADDR = 12'h060,
                          A_TABLE_W0 = 12'h064, A_TABLE_W1 = 12'h068, A_RESULT_ADDR = 12'h070,
                          A_RESULT_DATA = 12'h074, A_CAPS = 12'h078;

  // ---------------------------------------------------------------- test sequence
  logic [31:0] d, d2;

  initial begin
    // reset
    wait_clks(4);
    resetn <= 1'b1;
    wait_clks(3);

    // ---- reset values, through the ports and through the bus
    expect_eq(spi_div_div, 5, "port spi_div_div reset");
    expect_eq(pe4302_manual, 6'h3F, "port pe4302_manual reset");
    expect_eq(pe4302_active_high, 1, "port pe4302_active_high reset");
    expect_eq(n_avg_n, 1, "port n_avg_n reset");
    rd_expect(A_SPI_DIV, 32'd5, "SPI_DIV reset");
    rd_expect(A_PE4302, 32'h0000_013F, "PE4302 reset");
    rd_expect(A_N_AVG, 32'd1, "N_AVG reset");
    rd_expect(A_N_ENTRIES, 32'd0, "N_ENTRIES reset");
    rd_expect(A_T_ATT_GAP, 32'd100, "T_ATT_GAP_CYC reset");
    rd_expect(A_T_MIN, 32'd200, "T_MIN_US reset");
    rd_expect(A_T_STABLE, 32'd50, "T_LOCK_STABLE_US reset");
    rd_expect(A_T_TIMEOUT, 32'd10000, "T_LOCK_TIMEOUT_US reset");
    rd_expect(A_T_SETTLE, 32'd500, "T_SETTLE_US reset");
    rd_expect(A_CTRL, 32'd0, "CTRL reset");
    rd_expect(A_DET_CFG, 32'd0, "DET_CFG reset");
    rd_expect(A_TABLE_W0, 32'd0, "TABLE_W0 reset");

    // ---- constants
    rd_expect(A_ID, 32'h5341_0001, "ID");
    rd_expect(A_VERSION, 32'h0001_0000, "VERSION");
    axi_write(A_ID, 32'h0, 0, 0, 0);
    axi_write(A_VERSION, 32'hFFFF_FFFF, 0, 0, 0);
    rd_expect(A_ID, 32'h5341_0001, "ID after write");
    rd_expect(A_VERSION, 32'h0001_0000, "VERSION after write");

    // ---- rw fields: read back, unused bits read 0
    axi_write(A_SPI_DIV, 32'hFFFF_FFFF);
    rd_expect(A_SPI_DIV, 32'h0000_00FF, "SPI_DIV all ones");
    expect_eq(spi_div_div, 8'hFF, "port spi_div_div");
    axi_write(A_SPI_DIV, 32'h0000_0007);
    rd_expect(A_SPI_DIV, 32'h7, "SPI_DIV 7");
    axi_write(A_N_AVG, 32'hFFFF_FFFF);
    rd_expect(A_N_AVG, 32'h0000_0FFF, "N_AVG all ones");
    expect_eq(n_avg_n, 12'hFFF, "port n_avg_n");
    axi_write(A_PE4302, 32'hFFFF_FFFF);
    rd_expect(A_PE4302, 32'h0000_013F, "PE4302 all ones");
    axi_write(A_PE4302, 32'h0000_0000);
    rd_expect(A_PE4302, 32'h0, "PE4302 zero");
    expect_eq(pe4302_manual, 0, "port pe4302_manual");
    expect_eq(pe4302_active_high, 0, "port pe4302_active_high");
    axi_write(A_PE4302, 32'h0000_0155);
    rd_expect(A_PE4302, 32'h0000_0115, "PE4302 0x155 (bit 6 and 7 unused)");
    expect_eq(pe4302_manual, 6'h15, "port pe4302_manual 0x15");
    expect_eq(pe4302_wr_count, 3, "pe4302_wr: one strobe per write");
    expect_eq(pe4302_manual_at_wr, 6'h15, "pe4302_manual already new in the pe4302_wr clock");
    axi_write(A_T_MIN, 32'hFFFF_FFFF);
    rd_expect(A_T_MIN, 32'h000F_FFFF, "T_MIN_US all ones");
    axi_write(A_N_ENTRIES, 32'hABCD_1234);
    rd_expect(A_N_ENTRIES, 32'h0000_1234, "N_ENTRIES");
    axi_write(A_DET_CFG, 32'hFFFF_FFFF);
    rd_expect(A_DET_CFG, 32'h3, "DET_CFG");
    axi_write(A_DET_TEST, 32'h1234_ABCD);
    rd_expect(A_DET_TEST, 32'h0000_ABCD, "DET_TEST");
    axi_write(A_TABLE_W0, 32'hDEAD_BEEF);
    rd_expect(A_TABLE_W0, 32'hDEAD_BEEF, "TABLE_W0");
    expect_eq(table_w0_word, 32'hDEAD_BEEF, "port table_w0_word");
    // other registers untouched by all this
    rd_expect(A_T_STABLE, 32'd50, "T_LOCK_STABLE_US unchanged");
    rd_expect(A_T_SETTLE, 32'd500, "T_SETTLE_US unchanged");
    expect_pulses(-1, 0, 0, "rw writes");

    // address decode ignores the two LSBs
    axi_write(12'h01A, 32'h0000_0042);
    rd_expect(A_SPI_DIV, 32'h42, "SPI_DIV written through 0x01A");
    rd_expect(12'h019, 32'h42, "SPI_DIV read through 0x019");

    // ---- ro fields follow the inputs; writes are ignored
    status_busy <= 1; status_done <= 0; status_err_lock <= 1; status_aborted <= 0; status_ld_now <= 1;
    status_wait_sample <= 0; status_err_table <= 1; status_pin_owner_act <= 0; status_state <= 4'hA;
    rd_expect(A_STATUS, 32'h0000_0A55, "STATUS pattern 1");
    status_busy <= 0; status_done <= 1; status_err_lock <= 0; status_aborted <= 1; status_ld_now <= 0;
    status_wait_sample <= 1; status_err_table <= 0; status_pin_owner_act <= 1; status_state <= 4'h5;
    rd_expect(A_STATUS, 32'h0000_05AA, "STATUS pattern 2");
    status_busy <= 1; status_done <= 1; status_err_lock <= 1; status_aborted <= 1; status_ld_now <= 1;
    status_wait_sample <= 1; status_err_table <= 1; status_pin_owner_act <= 1; status_state <= 4'hF;
    axi_write(A_STATUS, 32'h0);
    rd_expect(A_STATUS, 32'h0000_0FFF, "STATUS all ones (write ignored)");
    status_state <= 4'h0;
    point_count_count <= 16'h1234;
    rd_expect(A_POINT_COUNT, 32'h0000_1234, "POINT_COUNT");
    axi_write(A_POINT_COUNT, 32'hFFFF_FFFF);
    rd_expect(A_POINT_COUNT, 32'h0000_1234, "POINT_COUNT after write");
    sweep_count_count <= 32'hCAFE_F00D;
    rd_expect(A_SWEEP_COUNT, 32'hCAFE_F00D, "SWEEP_COUNT");
    first_err_index_index <= 16'h0042;
    rd_expect(A_FIRST_ERR, 32'h42, "FIRST_ERR_INDEX");
    entry_index_index <= 16'h0777;
    rd_expect(A_ENTRY_INDEX, 32'h777, "ENTRY_INDEX");
    pin_state_pe_in <= 6'h2A; pin_state_ld <= 1; pin_state_le <= 0; pin_state_clk <= 1; pin_state_dat <= 0;
    pin_state_pe_out <= 6'h15; pin_state_pe_t <= 6'h3F;
    rd_expect(A_PIN_STATE, 32'h3F15_052A, "PIN_STATE");
    rd_expect(A_CAPS, 32'h0064_0C0A, "CAPS");
    expect_pulses(-1, 0, 0, "ro registers");

    // ---- CTRL: w1p pulses one clock wide, rw bits stored, pulse bits read 0
    axi_write(A_CTRL, 32'h0000_0001);                       // start only
    expect_pulses(P_START, 1, 1, "CTRL start");
    expect_eq(snap_start_wdata, 32'h1, "reg_wdata in the start clock");
    rd_expect(A_CTRL, 32'h0, "CTRL after start");
    axi_write(A_CTRL, 32'h0000_0002);
    expect_pulses(P_ABORT, 1, 1, "CTRL abort");
    axi_write(A_CTRL, 32'h0000_0004);
    expect_pulses(P_SRST, 1, 1, "CTRL soft_reset");
    axi_write(A_CTRL, 32'h0000_0040);
    expect_pulses(P_IACK, 1, 1, "CTRL irq_ack");
    axi_write(A_CTRL, 32'h0000_0038);                       // only rw bits
    expect_pulses(-1, 0, 0, "CTRL rw bits only");
    rd_expect(A_CTRL, 32'h0000_0038, "CTRL rw bits");
    expect_eq({29'd0, ctrl_stop_on_err, ctrl_pin_owner, ctrl_irq_en}, 32'h7, "CTRL ports");
    axi_write(A_CTRL, 32'h0000_007F);                       // everything at once
    expect_pulses(P_START, 1, 4, "CTRL all bits");
    expect_eq(snap_start_wdata, 32'h7F, "reg_wdata, all bits");
    // storage and pulse are visible in the same clock
    expect_eq({29'd0, snap_start_stop_on_err, snap_start_pin_owner, snap_start_irq_en}, 32'h7,
              "rw bits already stored in the clock of the start pulse");
    rd_expect(A_CTRL, 32'h0000_0038, "CTRL all bits read back, pulse bits read 0");
    axi_write(A_CTRL, 32'h0000_0001);                       // rw bits cleared by a full-word write
    expect_pulses(P_START, 1, 1, "CTRL start again");
    rd_expect(A_CTRL, 32'h0, "CTRL rw bits cleared");
    expect_eq({29'd0, ctrl_stop_on_err, ctrl_pin_owner, ctrl_irq_en}, 32'h0, "CTRL ports cleared");
    // a back-to-back repeat of the same pulse gives two separate pulses
    axi_write(A_CTRL, 32'h0000_0001);
    axi_write(A_CTRL, 32'h0000_0001);
    expect_pulses(P_START, 2, 2, "two start writes");

    // ---- ext registers: strobes, no storage
    clear_counts();
    axi_write(A_TABLE_W1, 32'hCAFE_1234);
    expect_pulses(P_TW1_WR, 1, 1, "TABLE_W1 write");
    expect_eq(snap_wdata, 32'hCAFE_1234, "reg_wdata in the table_w1_wr clock");
    table_w1_rdata <= 32'h0000_0000;
    rd_expect(A_TABLE_W1, 32'h0, "TABLE_W1 reads the ext value (0)");
    expect_pulses(P_TW1_RD, 1, 1, "TABLE_W1 read");
    table_w1_rdata <= 32'h0000_0F0F;
    rd_expect(A_TABLE_W1, 32'h0000_0F0F, "TABLE_W1 reads table_w1_rdata");
    expect_pulses(P_TW1_RD, 1, 1, "TABLE_W1 read 2");
    axi_write(A_TABLE_ADDR, 32'h0000_0010);
    expect_pulses(P_TADDR_WR, 1, 1, "TABLE_ADDR write");
    rd_expect(A_TABLE_ADDR, 32'h0000_0123, "TABLE_ADDR reads table_addr_rdata (no storage)");
    expect_pulses(P_TADDR_RD, 1, 1, "TABLE_ADDR read");
    axi_write(A_RESULT_ADDR, 32'h0000_0005);
    expect_pulses(P_RADDR_WR, 1, 1, "RESULT_ADDR write");
    rd_expect(A_RESULT_ADDR, 32'h0000_0456, "RESULT_ADDR read");
    expect_pulses(P_RADDR_RD, 1, 1, "RESULT_ADDR read strobe");
    axi_write(A_DET_PUSH, 32'h0000_ABCD);
    expect_pulses(P_DET_WR, 1, 1, "DET_PUSH write");
    rd_expect(A_DET_PUSH, 32'h0, "DET_PUSH reads det_push_rdata");
    expect_pulses(P_DET_RD, 1, 1, "DET_PUSH read");
    axi_write(A_RESULT_DATA, 32'h1);
    expect_pulses(P_RDATA_WR, 1, 1, "RESULT_DATA write");
    // RESULT_DATA: the returned word is the one present on result_data_rdata in the foo_rd clock
    for (int k = 0; k < 4; k++) begin
      axi_read(A_RESULT_DATA, d, k, k);                     // different AR delays and back-pressure
      wait_clks(1); #1;
      expect_eq(d, snap_rdata, "RESULT_DATA returned data vs value in the result_data_rd clock");
      if (pcnt[P_RDATA_RD] != 1) fail("result_data_rd not exactly one pulse");
      if (ptotal != 1) fail("unexpected extra strobes at RESULT_DATA read");
      clear_counts();
    end
    // a plain register read gives no read strobe, an ext register write no read strobe
    rd_expect(A_SPI_DIV, 32'h42, "SPI_DIV");
    expect_pulses(-1, 0, 0, "rw read has no strobes");

    // ---- unknown addresses
    rd_expect(12'h0F0, 32'h0, "unknown 0x0F0");
    rd_expect(12'h07C, 32'h0, "unknown 0x07C");
    rd_expect(12'h054, 32'h0, "gap 0x054");
    rd_expect(12'hFFC, 32'h0, "unknown 0xFFC");
    axi_write(12'h0F0, 32'hFFFF_FFFF);
    axi_write(12'hFFC, 32'hFFFF_FFFF);
    axi_write(12'h07C, 32'hFFFF_FFFF);
    expect_pulses(-1, 0, 0, "writes to unknown addresses");
    rd_expect(12'h0F0, 32'h0, "unknown 0x0F0 after write");
    rd_expect(A_SPI_DIV, 32'h42, "SPI_DIV unchanged by unknown writes");
    rd_expect(A_N_AVG, 32'hFFF, "N_AVG unchanged by unknown writes");

    // ---- AW and W arrive at different times
    axi_write(A_T_SETTLE, 32'h0000_1111, 0, 5);               // AW first, W five clocks later
    rd_expect(A_T_SETTLE, 32'h1111, "AW before W");
    axi_write(A_T_SETTLE, 32'h0000_2222, 5, 0);               // W first
    rd_expect(A_T_SETTLE, 32'h2222, "W before AW");
    axi_write(A_T_SETTLE, 32'h0000_3333, 3, 7);
    rd_expect(A_T_SETTLE, 32'h3333, "AW then W");
    axi_write(A_T_SETTLE, 32'h0000_4444, 7, 3);
    rd_expect(A_T_SETTLE, 32'h4444, "W then AW");
    axi_write(A_CTRL, 32'h0000_0001, 0, 6);                   // pulse register with skewed channels
    expect_pulses(P_START, 1, 1, "skewed CTRL start");

    // ---- back-pressure on bready and rready
    axi_write(A_T_MIN, 32'h0000_0AAA, 0, 0, 6);
    rd_expect(A_T_MIN, 32'h0AAA, "write with late bready");
    axi_read(A_T_MIN, d, 0, 8);
    expect_eq(d, 32'h0AAA, "read with late rready");
    axi_read(A_ID, d, 2, 3);
    expect_eq(d, 32'h5341_0001, "ID read with late rready");

    // ---- back-to-back transfers
    axi_write(A_N_ENTRIES, 32'h11);
    axi_write(A_N_AVG, 32'h22);
    axi_write(A_SPI_DIV, 32'h33);
    rd_expect(A_N_ENTRIES, 32'h11, "b2b write 1");
    rd_expect(A_N_AVG, 32'h22, "b2b write 2");
    rd_expect(A_SPI_DIV, 32'h33, "b2b write 3");
    // second write offered while the first response is still pending
    axi_write_nob(A_T_MIN, 32'h0000_0AAB, 0, 0);
    fork
      axi_b(4);                                             // response held for 4 clocks
      axi_write_nob(A_T_MIN, 32'h0000_0BBB, 0, 0);          // valids high while bvalid is pending
    join
    axi_b(0);
    rd_expect(A_T_MIN, 32'h0BBB, "write offered during pending response");
    // overlapped write and read on the two channels
    fork
      axi_write(A_T_SETTLE, 32'h0000_0777, 0, 0, 2);
      axi_read(A_N_AVG, d2, 0, 2);
    join
    expect_eq(d2, 32'h22, "read during write");
    rd_expect(A_T_SETTLE, 32'h0777, "write during read");
    // reads back to back with no gap
    axi_read(A_N_ENTRIES, d);
    axi_read(A_N_AVG, d2);
    expect_eq(d, 32'h11, "back-to-back read 1");
    expect_eq(d2, 32'h22, "back-to-back read 2");

    // ---- synchronous reset restores the reset values
    resetn <= 1'b0;
    wait_clks(2);
    resetn <= 1'b1;
    wait_clks(2);
    rd_expect(A_SPI_DIV, 32'd5, "SPI_DIV after reset");
    rd_expect(A_PE4302, 32'h13F, "PE4302 after reset");
    rd_expect(A_N_AVG, 32'd1, "N_AVG after reset");
    rd_expect(A_CTRL, 32'd0, "CTRL after reset");
    rd_expect(A_TABLE_W0, 32'd0, "TABLE_W0 after reset");
    rd_expect(A_ID, 32'h5341_0001, "ID after reset");

    wait_clks(3);
    if (!failed) begin
      $display("TB PASS");
      $finish;
    end
  end

endmodule
