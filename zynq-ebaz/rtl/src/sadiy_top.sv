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
  input  wire logic        emio_ce_o,       // EMIO GPIO 6
  input  wire logic        emio_ce_t,
  input  wire logic        emio_scl_o,      // PS I2C0
  input  wire logic        emio_scl_t,
  input  wire logic        emio_sda_o,
  input  wire logic        emio_sda_t,
  output      logic        emio_scl_i,
  output      logic        emio_sda_i,
  // pins
  output      logic        adf4351_clk,
  output      logic        adf4351_dat,
  output      logic        adf4351_le,
  input  wire logic        adf4351_ld,
  output      logic [5:0]  pe4302_v_o,
  output      logic [5:0]  pe4302_v_t,
  input  wire logic [5:0]  pe4302_v_i,
  output      logic        adf4351_ce_o,
  output      logic        adf4351_ce_t,
  input  wire logic        adf4351_ce_i,
  output      logic        i2c_scl_o,       // ADS1115 bus: PS I2C0 or the reader of the PL
  output      logic        i2c_scl_t,
  input  wire logic        i2c_scl_i,
  output      logic        i2c_sda_o,
  output      logic        i2c_sda_t,
  input  wire logic        i2c_sda_i,
  // sample stream of an ADC adapter (spec section 8b): 16 bit two's complement, full scale +/-32767
  input  wire logic        det_ext_valid,
  input  wire logic [15:0] det_ext_data,
  input  wire logic        det_ext_ovr
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
  logic [1:0]  ce_sync, scl_sync, sda_sync;
  // ADS1115 reader
  logic [15:0] adc_config, adc_last, adc_data;
  logic [6:0]  adc_addr;
  logic [11:0] adc_div;
  logic [19:0] adc_t_conv_us;
  logic        adc_err_nack, adc_busy, adc_valid, adc_scl_t, adc_sda_t, adc_run;
  logic [7:0]  adc_count;
  logic        adf_ce, i2c_pl;
  // sample stream, generator, IF path
  logic        det_mode, det_stream;
  logic [15:0] gen_div;
  logic [11:0] gen_len_m1, gen_addr;
  logic        gen_sync, gen_enable, gen_addr_wr, gen_data_wr, gen_valid;
  logic signed [15:0] gen_data, s_data;
  logic        s_valid, s_ovr;
  logic [31:0] if_nco, if_nco_step;
  logic [15:0] if_r;
  logic [5:0]  if_shift;
  logic [3:0]  if_skip;
  logic        if_clr, if_done, if_ovr, vid_done, det_run_d;
  logic [27:0] if_sum, vid_sum;
  logic        eng_clk, eng_dat, eng_le;
  logic [5:0]  eng_pe;

  always_ff @(posedge clk) begin
    ld_sync    <= {ld_sync[0], adf4351_ld};
    pe_in_meta <= pe4302_v_i;
    pe_in_sync <= pe_in_meta;
    ce_sync    <= {ce_sync[0], adf4351_ce_i};
    scl_sync   <= {scl_sync[0], i2c_scl_i};
    sda_sync   <= {sda_sync[0], i2c_sda_i};
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
    .pin_state_ce           (ce_sync[1]),
    .pin_state_scl          (scl_sync[1]),
    .pin_state_sda          (sda_sync[1]),
    .pin_state_i2c_pl       (i2c_pl),
    .pin_state_pe_out       (pe4302_v_o),
    .pin_state_pe_t         (pe4302_v_t),
    .det_cfg_src            (det_src),
    .det_cfg_mode           (det_mode),
    .det_cfg_stream         (det_stream),
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
    .caps_clk_mhz           (16'(CLK_PER_US)),
    .adc_cfg_config         (adc_config),
    .adc_cfg_addr           (adc_addr),
    .adc_i2c_div_div        (adc_div),
    .adc_t_conv_us_us       (adc_t_conv_us),
    .adc_stat_last          (adc_last),
    .adc_stat_err_nack      (adc_err_nack),
    .adc_stat_busy          (adc_busy),
    .adc_stat_count         (adc_count),
    .adf_pins_ce            (adf_ce),
    .gen_cfg_div            (gen_div),
    .gen_cfg_len_m1         (gen_len_m1),
    .gen_cfg_sync           (gen_sync),
    .gen_cfg_enable         (gen_enable),
    .gen_addr_wr            (gen_addr_wr),
    .gen_addr_rd            (),
    .gen_addr_rdata         ({20'd0, gen_addr}),
    .gen_data_wr            (gen_data_wr),
    .gen_data_rd            (),
    .gen_data_rdata         (32'd0),
    .if_nco_inc             (if_nco),
    .if_nco_step_step       (if_nco_step),
    .if_cic_r               (if_r),
    .if_cic_shift           (if_shift),
    .if_cic_skip            (if_skip)
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
    .det_ovr           (det_mode && if_ovr),
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

  // ---- sample stream (spec 8b): generator or ADC adapter port; video path or IF path (DET_CFG.mode) ----
  always_ff @(posedge clk) begin
    if (!resetn) begin
      det_run_d <= 1'b0;
      gen_addr  <= '0;
    end else begin
      det_run_d <= det_run;
      if (gen_addr_wr)      gen_addr <= reg_wdata[11:0];
      else if (gen_data_wr) gen_addr <= gen_addr + 12'd1;
    end
  end

  sample_gen #(.AW(12)) u_gen (
    .clk, .resetn,
    .enable   (gen_enable),
    .sync_clr (gen_sync && det_run && !det_run_d),      // first clock of SAMPLE
    .div      (gen_div),
    .len_m1   (gen_len_m1),
    .we       (gen_data_wr),
    .waddr    (gen_addr),
    .wdata    (reg_wdata[15:0]),
    .valid    (gen_valid),
    .data     (gen_data)
  );

  assign s_valid = det_stream ? gen_valid : det_ext_valid;
  assign s_data  = det_stream ? gen_data  : $signed(det_ext_data);
  assign s_ovr   = det_stream ? 1'b0      : det_ext_ovr;

  if_power u_if (
    .clk, .resetn,
    .run      (det_run && det_mode),
    .first    (point_count == 16'd0),
    .s_valid, .s_data, .s_ovr,
    .nco_base (if_nco),
    .nco_step (if_nco_step),
    .r        (if_r),
    .shift    (if_shift),
    .skip     (if_skip),
    .n_avg    (n_avg),
    .clr      (if_clr),
    .sum      (if_sum),
    .ovr      (if_ovr),
    .done     (if_done)
  );

  assign det_done = det_mode ? if_done : vid_done;
  assign det_sum  = det_mode ? if_sum  : vid_sum;

  det_sampler #(.CLK_PER_US(CLK_PER_US)) u_det (
    .clk, .resetn,
    .run          (det_run && !det_mode),
    .src          (det_src),
    .n_avg        (n_avg),
    .test_base    (det_test_base),
    .result_index (point_count[7:0]),
    .push_valid   (det_push_wr),
    .push_data    (reg_wdata[15:0]),
    .ext_valid    (s_valid && det_run_d),           // not in the first clock: a restarted generator starts at sample 0
    .ext_data     (s_data[15] ? 16'd0 : 16'(s_data)),
    .adc_valid    (adc_valid),
    .adc_data     (adc_data),
    .sum          (vid_sum),
    .done         (vid_done)
  );

  // ---- ADS1115 reader (DET_CFG.src = 3) ----
  // It runs only while the sampler wants samples; the I2C pins change hands only between samples.
  assign adc_run = det_run && !det_done && (det_src == 2'd3) && i2c_pl;

  always_ff @(posedge clk) begin
    if (!resetn)        i2c_pl <= 1'b0;
    else if (!adc_busy) i2c_pl <= st_owner && (det_src == 2'd3);
  end

  ads1115_reader #(.CLK_PER_US(CLK_PER_US)) u_adc (
    .clk, .resetn,
    .run       (adc_run),
    .addr      (adc_addr),
    .cfg       (adc_config),
    .div       (adc_div),
    .t_conv_us (adc_t_conv_us),
    .err_clear (ctrl_start || ctrl_soft_reset),
    .valid     (adc_valid),
    .data      (adc_data),
    .last_raw  (adc_last),
    .err_nack  (adc_err_nack),
    .count     (adc_count),
    .busy      (adc_busy),
    .scl_t     (adc_scl_t),
    .sda_t     (adc_sda_t),
    .sda_i     (i2c_sda_i)
  );

  pin_mux u_pins (
    .clk, .resetn,
    .owner        (st_owner),
    .emio_adf_clk, .emio_adf_dat, .emio_adf_le, .emio_pe_o, .emio_pe_t,
    .emio_ce_o, .emio_ce_t, .emio_scl_o, .emio_scl_t, .emio_sda_o, .emio_sda_t, .emio_scl_i, .emio_sda_i,
    .eng_adf_clk  (eng_clk),
    .eng_adf_dat  (eng_dat),
    .eng_adf_le   (eng_le),
    .eng_pe       (eng_pe),
    .eng_ce       (adf_ce),
    .i2c_pl       (i2c_pl),
    .eng_scl_t    (adc_scl_t),
    .eng_sda_t    (adc_sda_t),
    .adf4351_clk, .adf4351_dat, .adf4351_le, .pe4302_v_o, .pe4302_v_t,
    .adf4351_ce_o, .adf4351_ce_t, .i2c_scl_o, .i2c_scl_t, .i2c_sda_o, .i2c_sda_t, .i2c_scl_i, .i2c_sda_i
  );
endmodule
`default_nettype wire
