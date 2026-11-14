// SAdiy PL sweep engine, top level. Specification: zynq-ebaz/docs/rtl-spec.md (section 3 = this
// port list). No pads and no vendor cells here; the board top is rtl/fpga/ebaz_sadiy_top.sv.
`default_nettype none
module sadiy_top #(
  parameter int TABLE_AW  = 12,          // table depth 2^TABLE_AW entries
  parameter int RESULT_AW = 12,          // result depth 2^RESULT_AW words
  parameter int CLK_HZ    = 100_000_000
) (
  input  wire logic        clk,
  input  wire logic        resetn,
  // AXI4-Lite slave
  input  wire logic [11:0] s_axil_awaddr,
  input  wire logic        s_axil_awvalid,
  output      logic        s_axil_awready,
  input  wire logic [31:0] s_axil_wdata,
  input  wire logic [3:0]  s_axil_wstrb,
  input  wire logic        s_axil_wvalid,
  output      logic        s_axil_wready,
  output      logic [1:0]  s_axil_bresp,
  output      logic        s_axil_bvalid,
  input  wire logic        s_axil_bready,
  input  wire logic [11:0] s_axil_araddr,
  input  wire logic        s_axil_arvalid,
  output      logic        s_axil_arready,
  output      logic [31:0] s_axil_rdata,
  output      logic [1:0]  s_axil_rresp,
  output      logic        s_axil_rvalid,
  input  wire logic        s_axil_rready,
  output      logic        irq,
  // PS side (EMIO)
  input  wire logic        emio_adf_clk,
  input  wire logic        emio_adf_dat,
  input  wire logic        emio_adf_le,
  input  wire logic [5:0]  emio_pe_o,
  input  wire logic [5:0]  emio_pe_t,
  // pins
  output      logic        adf4351_clk,
  output      logic        adf4351_dat,
  output      logic        adf4351_le,
  input  wire logic        adf4351_ld,
  output      logic [5:0]  pe4302_v_o,
  output      logic [5:0]  pe4302_v_t,
  input  wire logic [5:0]  pe4302_v_i,
  // detector sample stream of a PL ADC reader (S10)
  input  wire logic        det_ext_valid,
  input  wire logic [15:0] det_ext_data
);
  localparam int CLK_PER_US = CLK_HZ / 1_000_000;
  localparam int TBL_DW     = 44;        // {w1[11:0], w0[31:0]}; the other w1 bits are not stored

  // ---- registers ----
  logic [31:0] reg_wdata;
  logic        ctrl_start, ctrl_abort, ctrl_soft_reset, ctrl_irq_en, ctrl_pin_owner;
  logic        ctrl_stop_on_err, ctrl_irq_ack;
  logic        st_busy, st_done, st_err_lock, st_aborted, st_wait_sample, st_err_table, st_owner;
  logic [3:0]  st_state;
  logic [15:0] n_entries, t_att_gap;
  logic [11:0] n_avg;
  logic [7:0]  spi_div;
  logic [19:0] t_min_us, t_lock_stable_us, t_lock_timeout_us, t_settle_us;
  logic [5:0]  pe_manual;
  logic        pe_active_high;
  logic [1:0]  det_src;
  logic [15:0] det_test_base;
  logic [15:0] first_err_index, point_count, entry_index;
  logic [31:0] sweep_count;
  logic [31:0] table_w0;
  logic        det_push_wr, table_addr_wr, table_w1_wr, result_addr_wr, result_data_rd, pe4302_wr;
  logic [15:0] table_addr, result_addr;
  logic [31:0] result_rdata;

  // ---- pins, synchronised inputs ----
  logic [1:0]  ld_sync;
  logic [5:0]  pe_in_meta, pe_in_sync;
  logic        ld;
  logic        eng_clk, eng_dat, eng_le;
  logic [5:0]  eng_pe;

  always_ff @(posedge clk) begin
    ld_sync    <= {ld_sync[0], adf4351_ld};
    pe_in_meta <= pe4302_v_i;
    pe_in_sync <= pe_in_meta;
  end
  assign ld = ld_sync[1];

  /* verilator lint_off PINCONNECTEMPTY */
  axil_regs u_regs (
    .clk, .resetn,
    .s_axil_awaddr, .s_axil_awvalid, .s_axil_awready,
    .s_axil_wdata, .s_axil_wstrb, .s_axil_wvalid, .s_axil_wready,
    .s_axil_bresp, .s_axil_bvalid, .s_axil_bready,
    .s_axil_araddr, .s_axil_arvalid, .s_axil_arready,
    .s_axil_rdata, .s_axil_rresp, .s_axil_rvalid, .s_axil_rready,
    .reg_wdata              (reg_wdata),
    .ctrl_start             (ctrl_start),
    .ctrl_abort             (ctrl_abort),
    .ctrl_soft_reset        (ctrl_soft_reset),
    .ctrl_irq_en            (ctrl_irq_en),
    .ctrl_pin_owner         (ctrl_pin_owner),
    .ctrl_stop_on_err       (ctrl_stop_on_err),
    .ctrl_irq_ack           (ctrl_irq_ack),
    .status_busy            (st_busy),
    .status_done            (st_done),
    .status_err_lock        (st_err_lock),
    .status_aborted         (st_aborted),
    .status_ld_now          (ld),
    .status_wait_sample     (st_wait_sample),
    .status_err_table       (st_err_table),
    .status_pin_owner_act   (st_owner),
    .status_state           (st_state),
    .n_entries_n            (n_entries),
    .n_avg_n                (n_avg),
    .spi_div_div            (spi_div),
    .t_att_gap_cyc_cycles   (t_att_gap),
    .t_min_us_us            (t_min_us),
    .t_lock_stable_us_us    (t_lock_stable_us),
    .t_lock_timeout_us_us   (t_lock_timeout_us),
    .t_settle_us_us         (t_settle_us),
    .pe4302_manual          (pe_manual),
    .pe4302_active_high     (pe_active_high),
    .pe4302_wr              (pe4302_wr),
    .pin_state_pe_in        (pe_in_sync),
    .pin_state_ld           (ld),
    .pin_state_le           (adf4351_le),
    .pin_state_clk          (adf4351_clk),
    .pin_state_dat          (adf4351_dat),
    .pin_state_pe_out       (pe4302_v_o),
    .pin_state_pe_t         (pe4302_v_t),
    .det_cfg_src            (det_src),
    .det_test_base          (det_test_base),
    .det_push_wr            (det_push_wr),
    .det_push_rd            (),
    .det_push_rdata         (32'd0),
    .first_err_index_index  (first_err_index),
    .point_count_count      (point_count),
    .sweep_count_count      (sweep_count),
    .entry_index_index      (entry_index),
    .table_addr_wr          (table_addr_wr),
    .table_addr_rd          (),
    .table_addr_rdata       ({16'd0, table_addr}),
    .table_w0_word          (table_w0),
    .table_w1_wr            (table_w1_wr),
    .table_w1_rd            (),
    .table_w1_rdata         (32'd0),
    .result_addr_wr         (result_addr_wr),
    .result_addr_rd         (),
    .result_addr_rdata      ({16'd0, result_addr}),
    .result_data_wr         (),
    .result_data_rd         (result_data_rd),
    .result_data_rdata      (result_rdata),
    .caps_table_aw          (8'(TABLE_AW)),
    .caps_result_aw         (8'(RESULT_AW)),
    .caps_clk_mhz           (16'(CLK_PER_US))
  );
  /* verilator lint_on PINCONNECTEMPTY */

  assign irq = ctrl_irq_en && st_done;

  // ---- table and result memories, reached through address / data registers ----
  logic                 tbl_we;
  logic [TABLE_AW-1:0]  tbl_raddr;
  logic [TBL_DW-1:0]    tbl_rdata;
  logic                 res_we;
  logic [RESULT_AW-1:0] res_waddr;
  logic [31:0]          res_wdata;

  assign tbl_we = table_w1_wr && !st_busy;       // table writes are ignored while a sweep runs

  always_ff @(posedge clk) begin
    if (!resetn) begin
      table_addr  <= '0;
      result_addr <= '0;
    end else begin
      if (st_busy)             ;                 // table address and content are frozen during a sweep
      else if (table_addr_wr)  table_addr <= reg_wdata[15:0];
      else if (tbl_we)         table_addr <= table_addr + 16'd1;
      if (result_addr_wr)      result_addr <= reg_wdata[15:0];
      else if (result_data_rd) result_addr <= result_addr + 16'd1;
    end
  end

  sdp_ram #(.AW(TABLE_AW), .DW(TBL_DW)) u_table (
    .clk,
    .we    (tbl_we),
    .waddr (table_addr[TABLE_AW-1:0]),
    .wdata ({reg_wdata[11:0], table_w0}),
    .raddr (tbl_raddr),
    .rdata (tbl_rdata)
  );

  sdp_ram #(.AW(RESULT_AW), .DW(32)) u_result (
    .clk,
    .we    (res_we),
    .waddr (res_waddr),
    .wdata (res_wdata),
    .raddr (result_addr[RESULT_AW-1:0]),
    .rdata (result_rdata)
  );

  // ---- sequencer and its helpers ----
  logic        spi_start, spi_busy;
  logic [31:0] spi_word;
  logic        mbb_load, mbb_set, mbb_busy;
  logic [5:0]  mbb_value;
  logic        det_run, det_done;
  logic [27:0] det_sum;

  sweep_seq #(.TABLE_AW(TABLE_AW), .RESULT_AW(RESULT_AW), .CLK_PER_US(CLK_PER_US)) u_seq (
    .clk, .resetn,
    .start             (ctrl_start),
    .abort             (ctrl_abort),
    .soft_reset        (ctrl_soft_reset),
    .irq_ack           (ctrl_irq_ack),
    .stop_on_err       (ctrl_stop_on_err),
    .pin_owner_req     (ctrl_pin_owner),
    .n_entries         (n_entries),
    .t_min_us          (t_min_us),
    .t_lock_stable_us  (t_lock_stable_us),
    .t_lock_timeout_us (t_lock_timeout_us),
    .t_settle_us       (t_settle_us),
    .pe_manual         (pe_manual),
    .pe_manual_wr      (pe4302_wr),
    .pe_cur            (eng_pe),
    .busy              (st_busy),
    .done              (st_done),
    .err_lock          (st_err_lock),
    .aborted           (st_aborted),
    .err_table         (st_err_table),
    .wait_sample       (st_wait_sample),
    .pin_owner_act     (st_owner),
    .state_o           (st_state),
    .first_err_index   (first_err_index),
    .point_count       (point_count),
    .sweep_count       (sweep_count),
    .entry_index       (entry_index),
    .tbl_raddr         (tbl_raddr),
    .tbl_rdata         (tbl_rdata),
    .res_we            (res_we),
    .res_waddr         (res_waddr),
    .res_wdata         (res_wdata),
    .spi_start         (spi_start),
    .spi_word          (spi_word),
    .spi_busy          (spi_busy),
    .mbb_load          (mbb_load),
    .mbb_set           (mbb_set),
    .mbb_value         (mbb_value),
    .mbb_busy          (mbb_busy),
    .det_run           (det_run),
    .det_done          (det_done),
    .det_sum           (det_sum),
    .ld                (ld)
  );

  adf4351_spi u_spi (
    .clk, .resetn,
    .div   (spi_div),
    .start (spi_start),
    .word  (spi_word),
    .busy  (spi_busy),
    .sclk  (eng_clk),
    .sdat  (eng_dat),
    .le    (eng_le)
  );

  pe4302_mbb u_mbb (
    .clk, .resetn,
    .gap         (t_att_gap),
    .active_high (pe_active_high),
    .load        (mbb_load),
    .set         (mbb_set),
    .value       (mbb_value),
    .pins        (eng_pe),
    .busy        (mbb_busy)
  );

  det_sampler #(.CLK_PER_US(CLK_PER_US)) u_det (
    .clk, .resetn,
    .run          (det_run),
    .src          (det_src),
    .n_avg        (n_avg),
    .test_base    (det_test_base),
    .result_index (point_count[7:0]),
    .push_valid   (det_push_wr),
    .push_data    (reg_wdata[15:0]),
    .ext_valid    (det_ext_valid),
    .ext_data     (det_ext_data),
    .sum          (det_sum),
    .done         (det_done)
  );

  pin_mux u_pins (
    .clk, .resetn,
    .owner        (st_owner),
    .emio_adf_clk, .emio_adf_dat, .emio_adf_le, .emio_pe_o, .emio_pe_t,
    .eng_adf_clk  (eng_clk),
    .eng_adf_dat  (eng_dat),
    .eng_adf_le   (eng_le),
    .eng_pe       (eng_pe),
    .adf4351_clk, .adf4351_dat, .adf4351_le, .pe4302_v_o, .pe4302_v_t
  );
endmodule
`default_nettype wire
