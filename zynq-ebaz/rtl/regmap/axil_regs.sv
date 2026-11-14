// generated from regmap.toml by gen_regs.py, do not edit
// Source: rtl/regmap/regmap.toml. Specification: docs/rtl-spec.md, section 4.
//
// AXI4-Lite slave with a register file. WSTRB is ignored, responses are always OKAY, unknown
// addresses read 0 and ignore writes, the two address LSBs are ignored. All AXI outputs come from
// registers (no combinational path from an AXI input to an AXI output).
//
// Write: when awvalid and wvalid are both seen (and no response is pending) the address and data are
// latched and awready = wready is high for exactly one clock (the accept clock, T0). At the end of T0
// the storage, the w1p pulses, the ext *_wr strobes and bvalid are all updated; so in T1 the new
// storage value, the pulse / strobe and bvalid are visible together, and reg_wdata holds the write
// data in T1 (and in T0). bvalid stays until bready.
// Read: when arvalid is seen (and no response is pending) the address is latched and arready is high
// for one clock (T0). In T0 the ext *_rd strobe is high, *_rdata is sampled, together with all other
// register values, into the read data register at the end of T0; rvalid is high in T1 until rready.
// The ext *_rd strobe is derived from state registers only (not from AXI inputs).

/* verilator lint_off UNUSEDSIGNAL */
module axil_regs (
  input  logic clk,
  input  logic resetn,

  input  logic [11:0] s_axil_awaddr,
  input  logic s_axil_awvalid,
  output logic s_axil_awready,
  input  logic [31:0] s_axil_wdata,
  input  logic [3:0] s_axil_wstrb,
  input  logic s_axil_wvalid,
  output logic s_axil_wready,
  output logic [1:0] s_axil_bresp,
  output logic s_axil_bvalid,
  input  logic s_axil_bready,
  input  logic [11:0] s_axil_araddr,
  input  logic s_axil_arvalid,
  output logic s_axil_arready,
  output logic [31:0] s_axil_rdata,
  output logic [1:0] s_axil_rresp,
  output logic s_axil_rvalid,
  input  logic s_axil_rready,

  output logic [31:0] reg_wdata,

  // ID @ 0x000

  // VERSION @ 0x004

  // CTRL @ 0x008
  output logic ctrl_start,
  output logic ctrl_abort,
  output logic ctrl_soft_reset,
  output logic ctrl_irq_en,
  output logic ctrl_pin_owner,
  output logic ctrl_stop_on_err,
  output logic ctrl_irq_ack,

  // STATUS @ 0x00C
  input  logic status_busy,
  input  logic status_done,
  input  logic status_err_lock,
  input  logic status_aborted,
  input  logic status_ld_now,
  input  logic status_wait_sample,
  input  logic status_err_table,
  input  logic status_pin_owner_act,
  input  logic [3:0] status_state,

  // N_ENTRIES @ 0x010
  output logic [15:0] n_entries_n,

  // N_AVG @ 0x014
  output logic [11:0] n_avg_n,

  // SPI_DIV @ 0x018
  output logic [7:0] spi_div_div,

  // T_ATT_GAP_CYC @ 0x01C
  output logic [15:0] t_att_gap_cyc_cycles,

  // T_MIN_US @ 0x020
  output logic [19:0] t_min_us_us,

  // T_LOCK_STABLE_US @ 0x024
  output logic [19:0] t_lock_stable_us_us,

  // T_LOCK_TIMEOUT_US @ 0x028
  output logic [19:0] t_lock_timeout_us_us,

  // T_SETTLE_US @ 0x02C
  output logic [19:0] t_settle_us_us,

  // PE4302 @ 0x030
  output logic [5:0] pe4302_manual,
  output logic pe4302_active_high,
  output logic pe4302_wr,

  // PIN_STATE @ 0x034
  input  logic [5:0] pin_state_pe_in,
  input  logic pin_state_ld,
  input  logic pin_state_le,
  input  logic pin_state_clk,
  input  logic pin_state_dat,
  input  logic [5:0] pin_state_pe_out,
  input  logic [5:0] pin_state_pe_t,

  // DET_CFG @ 0x038
  output logic [1:0] det_cfg_src,

  // DET_TEST @ 0x03C
  output logic [15:0] det_test_base,

  // DET_PUSH @ 0x040 (ext)
  output logic det_push_wr,
  output logic det_push_rd,
  input  logic [31:0] det_push_rdata,

  // FIRST_ERR_INDEX @ 0x044
  input  logic [15:0] first_err_index_index,

  // POINT_COUNT @ 0x048
  input  logic [15:0] point_count_count,

  // SWEEP_COUNT @ 0x04C
  input  logic [31:0] sweep_count_count,

  // ENTRY_INDEX @ 0x050
  input  logic [15:0] entry_index_index,

  // TABLE_ADDR @ 0x060 (ext)
  output logic table_addr_wr,
  output logic table_addr_rd,
  input  logic [31:0] table_addr_rdata,

  // TABLE_W0 @ 0x064
  output logic [31:0] table_w0_word,

  // TABLE_W1 @ 0x068 (ext)
  output logic table_w1_wr,
  output logic table_w1_rd,
  input  logic [31:0] table_w1_rdata,

  // RESULT_ADDR @ 0x070 (ext)
  output logic result_addr_wr,
  output logic result_addr_rd,
  input  logic [31:0] result_addr_rdata,

  // RESULT_DATA @ 0x074 (ext)
  output logic result_data_wr,
  output logic result_data_rd,
  input  logic [31:0] result_data_rdata,

  // CAPS @ 0x078
  input  logic [7:0] caps_table_aw,
  input  logic [7:0] caps_result_aw,
  input  logic [15:0] caps_clk_mhz
);

  // ---- write channel
  logic wr_phase;                 // T0: awready = wready = 1
  logic bvalid_q;
  logic [11:0] waddr_q;
  logic [31:0] wdata_q;

  assign s_axil_awready = wr_phase;
  assign s_axil_wready  = wr_phase;
  assign s_axil_bresp   = 2'b00;
  assign s_axil_bvalid  = bvalid_q;
  assign reg_wdata      = wdata_q;

  always_ff @(posedge clk) begin
    if (!resetn) begin
      wr_phase <= 1'b0;
      bvalid_q <= 1'b0;
      waddr_q  <= 12'd0;
      wdata_q  <= 32'd0;
    end else if (wr_phase) begin
      wr_phase <= 1'b0;
      bvalid_q <= 1'b1;
    end else if (bvalid_q) begin
      if (s_axil_bready) bvalid_q <= 1'b0;
    end else if (s_axil_awvalid && s_axil_wvalid) begin
      wr_phase <= 1'b1;
      waddr_q  <= s_axil_awaddr;
      wdata_q  <= s_axil_wdata;
    end
  end

  // ---- register storage, w1p pulses and ext write strobes (all updated at the end of T0)
  always_ff @(posedge clk) begin
    ctrl_start <= 1'b0;
    ctrl_abort <= 1'b0;
    ctrl_soft_reset <= 1'b0;
    ctrl_irq_ack <= 1'b0;
    pe4302_wr <= 1'b0;
    det_push_wr <= 1'b0;
    table_addr_wr <= 1'b0;
    table_w1_wr <= 1'b0;
    result_addr_wr <= 1'b0;
    result_data_wr <= 1'b0;
    if (!resetn) begin
      ctrl_irq_en <= 1'h0;
      ctrl_pin_owner <= 1'h0;
      ctrl_stop_on_err <= 1'h0;
      n_entries_n <= 16'h0;
      n_avg_n <= 12'h1;
      spi_div_div <= 8'h5;
      t_att_gap_cyc_cycles <= 16'h64;
      t_min_us_us <= 20'hC8;
      t_lock_stable_us_us <= 20'h32;
      t_lock_timeout_us_us <= 20'h2710;
      t_settle_us_us <= 20'h1F4;
      pe4302_manual <= 6'h3F;
      pe4302_active_high <= 1'h1;
      det_cfg_src <= 2'h0;
      det_test_base <= 16'h0;
      table_w0_word <= 32'h0;
    end else if (wr_phase) begin
      case (waddr_q[11:2])
        10'h002: begin  // CTRL
          ctrl_start <= wdata_q[0];
          ctrl_abort <= wdata_q[1];
          ctrl_soft_reset <= wdata_q[2];
          ctrl_irq_en <= wdata_q[3];
          ctrl_pin_owner <= wdata_q[4];
          ctrl_stop_on_err <= wdata_q[5];
          ctrl_irq_ack <= wdata_q[6];
        end
        10'h004: begin  // N_ENTRIES
          n_entries_n <= wdata_q[15:0];
        end
        10'h005: begin  // N_AVG
          n_avg_n <= wdata_q[11:0];
        end
        10'h006: begin  // SPI_DIV
          spi_div_div <= wdata_q[7:0];
        end
        10'h007: begin  // T_ATT_GAP_CYC
          t_att_gap_cyc_cycles <= wdata_q[15:0];
        end
        10'h008: begin  // T_MIN_US
          t_min_us_us <= wdata_q[19:0];
        end
        10'h009: begin  // T_LOCK_STABLE_US
          t_lock_stable_us_us <= wdata_q[19:0];
        end
        10'h00A: begin  // T_LOCK_TIMEOUT_US
          t_lock_timeout_us_us <= wdata_q[19:0];
        end
        10'h00B: begin  // T_SETTLE_US
          t_settle_us_us <= wdata_q[19:0];
        end
        10'h00C: begin  // PE4302
          pe4302_manual <= wdata_q[5:0];
          pe4302_active_high <= wdata_q[8];
          pe4302_wr <= 1'b1;
        end
        10'h00E: begin  // DET_CFG
          det_cfg_src <= wdata_q[1:0];
        end
        10'h00F: begin  // DET_TEST
          det_test_base <= wdata_q[15:0];
        end
        10'h010: begin  // DET_PUSH
          det_push_wr <= 1'b1;
        end
        10'h018: begin  // TABLE_ADDR
          table_addr_wr <= 1'b1;
        end
        10'h019: begin  // TABLE_W0
          table_w0_word <= wdata_q[31:0];
        end
        10'h01A: begin  // TABLE_W1
          table_w1_wr <= 1'b1;
        end
        10'h01C: begin  // RESULT_ADDR
          result_addr_wr <= 1'b1;
        end
        10'h01D: begin  // RESULT_DATA
          result_data_wr <= 1'b1;
        end
        default: ;
      endcase
    end
  end

  // ---- read channel
  logic rd_phase;                 // T0: arready = 1, ext *_rd strobes
  logic rvalid_q;
  logic [11:0] raddr_q;
  logic [31:0] rdata_q;
  logic [31:0] rd_mux;

  assign s_axil_arready = rd_phase;
  assign s_axil_rdata   = rdata_q;
  assign s_axil_rresp   = 2'b00;
  assign s_axil_rvalid  = rvalid_q;

  assign det_push_rd = rd_phase && (raddr_q[11:2] == 10'h010);
  assign table_addr_rd = rd_phase && (raddr_q[11:2] == 10'h018);
  assign table_w1_rd = rd_phase && (raddr_q[11:2] == 10'h01A);
  assign result_addr_rd = rd_phase && (raddr_q[11:2] == 10'h01C);
  assign result_data_rd = rd_phase && (raddr_q[11:2] == 10'h01D);

  always_comb begin
    rd_mux = 32'd0;
    case (raddr_q[11:2])
      10'h000: begin  // ID
        rd_mux[31:0] = 32'h53410001;
      end
      10'h001: begin  // VERSION
        rd_mux[31:0] = 32'h10000;
      end
      10'h002: begin  // CTRL
        rd_mux[3] = ctrl_irq_en;
        rd_mux[4] = ctrl_pin_owner;
        rd_mux[5] = ctrl_stop_on_err;
      end
      10'h003: begin  // STATUS
        rd_mux[0] = status_busy;
        rd_mux[1] = status_done;
        rd_mux[2] = status_err_lock;
        rd_mux[3] = status_aborted;
        rd_mux[4] = status_ld_now;
        rd_mux[5] = status_wait_sample;
        rd_mux[6] = status_err_table;
        rd_mux[7] = status_pin_owner_act;
        rd_mux[11:8] = status_state;
      end
      10'h004: begin  // N_ENTRIES
        rd_mux[15:0] = n_entries_n;
      end
      10'h005: begin  // N_AVG
        rd_mux[11:0] = n_avg_n;
      end
      10'h006: begin  // SPI_DIV
        rd_mux[7:0] = spi_div_div;
      end
      10'h007: begin  // T_ATT_GAP_CYC
        rd_mux[15:0] = t_att_gap_cyc_cycles;
      end
      10'h008: begin  // T_MIN_US
        rd_mux[19:0] = t_min_us_us;
      end
      10'h009: begin  // T_LOCK_STABLE_US
        rd_mux[19:0] = t_lock_stable_us_us;
      end
      10'h00A: begin  // T_LOCK_TIMEOUT_US
        rd_mux[19:0] = t_lock_timeout_us_us;
      end
      10'h00B: begin  // T_SETTLE_US
        rd_mux[19:0] = t_settle_us_us;
      end
      10'h00C: begin  // PE4302
        rd_mux[5:0] = pe4302_manual;
        rd_mux[8] = pe4302_active_high;
      end
      10'h00D: begin  // PIN_STATE
        rd_mux[5:0] = pin_state_pe_in;
        rd_mux[8] = pin_state_ld;
        rd_mux[9] = pin_state_le;
        rd_mux[10] = pin_state_clk;
        rd_mux[11] = pin_state_dat;
        rd_mux[21:16] = pin_state_pe_out;
        rd_mux[29:24] = pin_state_pe_t;
      end
      10'h00E: begin  // DET_CFG
        rd_mux[1:0] = det_cfg_src;
      end
      10'h00F: begin  // DET_TEST
        rd_mux[15:0] = det_test_base;
      end
      10'h010: begin  // DET_PUSH
        rd_mux = det_push_rdata;
      end
      10'h011: begin  // FIRST_ERR_INDEX
        rd_mux[15:0] = first_err_index_index;
      end
      10'h012: begin  // POINT_COUNT
        rd_mux[15:0] = point_count_count;
      end
      10'h013: begin  // SWEEP_COUNT
        rd_mux[31:0] = sweep_count_count;
      end
      10'h014: begin  // ENTRY_INDEX
        rd_mux[15:0] = entry_index_index;
      end
      10'h018: begin  // TABLE_ADDR
        rd_mux = table_addr_rdata;
      end
      10'h019: begin  // TABLE_W0
        rd_mux[31:0] = table_w0_word;
      end
      10'h01A: begin  // TABLE_W1
        rd_mux = table_w1_rdata;
      end
      10'h01C: begin  // RESULT_ADDR
        rd_mux = result_addr_rdata;
      end
      10'h01D: begin  // RESULT_DATA
        rd_mux = result_data_rdata;
      end
      10'h01E: begin  // CAPS
        rd_mux[7:0] = caps_table_aw;
        rd_mux[15:8] = caps_result_aw;
        rd_mux[31:16] = caps_clk_mhz;
      end
      default: ;
    endcase
  end

  always_ff @(posedge clk) begin
    if (!resetn) begin
      rd_phase <= 1'b0;
      rvalid_q <= 1'b0;
      raddr_q  <= 12'd0;
      rdata_q  <= 32'd0;
    end else if (rd_phase) begin
      rd_phase <= 1'b0;
      rvalid_q <= 1'b1;
      rdata_q  <= rd_mux;
    end else if (rvalid_q) begin
      if (s_axil_rready) rvalid_q <= 1'b0;
    end else if (s_axil_arvalid) begin
      rd_phase <= 1'b1;
      raddr_q  <= s_axil_araddr;
    end
  end

endmodule
/* verilator lint_on UNUSEDSIGNAL */
