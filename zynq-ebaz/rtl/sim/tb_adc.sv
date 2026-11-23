// Self-checking testbench for the ADS1115 reader, the I2C pin mux and the CE pin, through sadiy_top
// (docs/rtl-spec.md sections 8a and 9). A behavioural ADS1115 (I2C slave) answers on the pads.
// Scenarios: PS I2C0 passes through while the PS owns the bus; the reader takes the bus with the pins
// and DET_CFG.src = 3; a sweep whose results are the sums of the conversions (a negative code counts
// as 0); conversion wait and SCL period; no conversion outside SAMPLE; missing ADC (NACK) ends the
// sweep with sample 0 and err_nack; abort during the conversion wait; CE follows ADF_PINS.ce.
`timescale 1ns / 1ps
module tb_adc;
  localparam logic [11:0] CTRL = 12'h008, STATUS = 12'h00C, N_ENTRIES = 12'h010, N_AVG = 12'h014,
    T_MIN = 12'h020, T_SETTLE = 12'h02C, PIN_STATE = 12'h034, DET_CFG = 12'h038, POINT_COUNT = 12'h048,
    TABLE_ADDR = 12'h060, TABLE_W0 = 12'h064, TABLE_W1 = 12'h068, RESULT_ADDR = 12'h070,
    RESULT_DATA = 12'h074, ADC_CFG = 12'h080, ADC_I2C_DIV = 12'h084, ADC_T_CONV = 12'h088,
    ADC_STAT = 12'h08C, ADF_PINS = 12'h090;
  localparam logic [31:0] C_START = 32'h01, C_ABORT = 32'h02, C_OWNER = 32'h10;
  localparam logic [31:0] S_BUSY = 32'h01, S_DONE = 32'h02, S_ABORTED = 32'h08, S_WAIT = 32'h20;
  localparam logic [31:0] W1_MEASURE = 32'h400, W1_SKIP_LOCK = 32'h800;

  logic clk = 0, resetn = 0;
  always #5 clk = ~clk;

  logic [11:0] awaddr = '0, araddr = '0;
  logic [31:0] wdata = '0, rdata;
  logic awvalid = 0, wvalid = 0, bready = 0, arvalid = 0, rready = 0;
  logic awready, wready, bvalid, arready, rvalid;
  logic [1:0] bresp, rresp;
  logic irq;
  logic emio_ce_o = 0, emio_ce_t = 1;
  logic emio_scl_o = 0, emio_scl_t = 1, emio_sda_o = 0, emio_sda_t = 1;
  logic emio_scl_i, emio_sda_i;
  logic ce_o, ce_t, scl_o, scl_t, sda_o, sda_t;
  logic slave_sda = 1;                              // 1 = the ADS1115 releases SDA
  wire  scl_pad = scl_t | scl_o;                    // pulled up
  wire  sda_pad = (sda_t | sda_o) & slave_sda;
  wire  ce_pad  = ce_t ? 1'b1 : ce_o;               // CE jumper = high

  sadiy_top dut (
    .clk, .resetn,
    .s_axil_awaddr(awaddr), .s_axil_awvalid(awvalid), .s_axil_awready(awready),
    .s_axil_wdata(wdata), .s_axil_wstrb(4'hF), .s_axil_wvalid(wvalid), .s_axil_wready(wready),
    .s_axil_bresp(bresp), .s_axil_bvalid(bvalid), .s_axil_bready(bready),
    .s_axil_araddr(araddr), .s_axil_arvalid(arvalid), .s_axil_arready(arready),
    .s_axil_rdata(rdata), .s_axil_rresp(rresp), .s_axil_rvalid(rvalid), .s_axil_rready(rready),
    .irq,
    .emio_adf_clk(1'b0), .emio_adf_dat(1'b0), .emio_adf_le(1'b1), .emio_pe_o(6'h00), .emio_pe_t(6'h3F),
    .emio_ce_o, .emio_ce_t, .emio_scl_o, .emio_scl_t, .emio_sda_o, .emio_sda_t, .emio_scl_i, .emio_sda_i,
    .adf4351_clk(), .adf4351_dat(), .adf4351_le(), .adf4351_ld(1'b0),
    .pe4302_v_o(), .pe4302_v_t(), .pe4302_v_i(6'h3F),
    .adf4351_ce_o(ce_o), .adf4351_ce_t(ce_t), .adf4351_ce_i(ce_pad),
    .i2c_scl_o(scl_o), .i2c_scl_t(scl_t), .i2c_scl_i(scl_pad),
    .i2c_sda_o(sda_o), .i2c_sda_t(sda_t), .i2c_sda_i(sda_pad),
    .det_ext_valid(1'b0), .det_ext_data(16'd0), .det_ext_ovr(1'b0),
    .adc_clk(), .adc_d(12'h800), .adc_otr(1'b0)
  );

  task automatic fail(input string why);
    $display("TB FAIL: %s (time %0t)", why, $time);
    $finish;
  endtask

  task automatic wr(input logic [11:0] a, input logic [31:0] d);
    @(posedge clk); awaddr <= a; wdata <= d; awvalid <= 1; wvalid <= 1; bready <= 1;
    fork
      begin do @(posedge clk); while (!awready); awvalid <= 0; end
      begin do @(posedge clk); while (!wready);  wvalid  <= 0; end
    join
    while (!bvalid) @(posedge clk);
    @(posedge clk); bready <= 0;
  endtask

  task automatic rd(input logic [11:0] a, output logic [31:0] d);
    @(posedge clk); araddr <= a; arvalid <= 1; rready <= 1;
    do @(posedge clk); while (!arready);
    arvalid <= 0;
    while (!rvalid) @(posedge clk);
    d = rdata;
    @(posedge clk); rready <= 0;
  endtask

  task automatic expect_reg(input logic [11:0] a, input logic [31:0] mask, input logic [31:0] want, input string what);
    logic [31:0] d;
    rd(a, d);
    if ((d & mask) !== want) fail($sformatf("%s: read %08x, masked %08x, expected %08x", what, d, d & mask, want));
  endtask

  task automatic wait_status(input logic [31:0] mask, input logic [31:0] want, input string what);
    logic [31:0] d;
    for (int i = 0; i < 400000; i++) begin
      rd(STATUS, d);
      if ((d & mask) === want) return;
    end
    fail({"timeout waiting for ", what});
  endtask

  // ---------------------------------------------------------------- behavioural ADS1115
  localparam logic [6:0] SLAVE_ADDR = 7'h48;
  logic [7:0]  ssh;
  logic [15:0] txsh, s_cfg = 16'h8583;              // config register (reset value of the chip)
  logic [7:0]  s_ptr = 8'h00;
  int   sbit = 0, s_bytei = 0;
  bit   s_active = 0, s_read = 0, master_ack = 0;
  int   n_start = 0, n_stop = 0, n_cfg_writes = 0, n_conv_reads = 0;
  time  t_cfg = 0, min_wait = 64'hFFFF_FFFF;        // shortest config write -> conversion read
  logic signed [15:0] conv [0:15];
  time  t_scl_rise = 0, scl_period = 0;

  always @(negedge sda_pad) if (scl_pad && resetn) begin        // START
    s_active = 1; sbit = 0; s_bytei = 0; s_read = 0; n_start++;
  end
  always @(posedge sda_pad) if (scl_pad && resetn) begin        // STOP
    if (s_active) n_stop++;
    s_active = 0; slave_sda = 1;
  end
  always @(posedge scl_pad) begin
    if (s_active) begin
      if (sbit < 8) ssh = {ssh[6:0], sda_pad};
      else master_ack = !sda_pad;
      if (sbit >= 1 && sbit <= 7) scl_period = $time - t_scl_rise;
      t_scl_rise = $time;
      sbit++;
    end
  end
  always @(negedge scl_pad) if (s_active) begin
    if (sbit == 8) begin                                        // ack slot begins
      if (s_bytei == 0) begin
        if (ssh[7:1] != SLAVE_ADDR) begin s_active = 0; slave_sda = 1; end   // not us: no ACK
        else begin s_read = ssh[0]; slave_sda = 0; end
      end else if (!s_read) begin
        slave_sda = 0;
        if (s_bytei == 1) s_ptr = ssh;
        else if (s_ptr == 8'h01) begin
          s_cfg = {s_cfg[7:0], ssh};
          if (s_bytei == 3) begin n_cfg_writes++; t_cfg = $time; end       // conversion starts
        end
      end else slave_sda = 1;                                   // the master acknowledges
    end else if (sbit == 9) begin                               // ack slot ends
      sbit = 0; s_bytei++;
      if (s_read) begin
        if (s_bytei == 1) begin
          if (s_ptr == 8'h00) begin
            txsh = conv[n_conv_reads % 16];
            if ($time - t_cfg < min_wait) min_wait = $time - t_cfg;
            n_conv_reads++;
          end else txsh = s_cfg;
          slave_sda = txsh[15]; txsh = txsh << 1;
        end else if (master_ack) begin slave_sda = txsh[15]; txsh = txsh << 1; end
        else slave_sda = 1;                                     // NACK: release, a STOP follows
      end else slave_sda = 1;
    end else if (s_read && s_bytei > 0) begin
      slave_sda = txsh[15]; txsh = txsh << 1;
    end
  end

  // ---------------------------------------------------------------- helpers
  task automatic load_points(input int n);
    wr(TABLE_ADDR, 0);
    for (int i = 0; i < n; i++) begin wr(TABLE_W0, 0); wr(TABLE_W1, W1_MEASURE | W1_SKIP_LOCK); end
    wr(N_ENTRIES, n);
  endtask

  logic [31:0] d;
  int unsigned want;

  initial begin
    for (int i = 0; i < 16; i++) conv[i] = 16'sd1000 + 16'(i * 111);
    conv[3] = -16'sd25;                                         // below GND: counts as 0
    repeat (5) @(posedge clk);
    resetn <= 1;
    repeat (5) @(posedge clk);

    // ---- 1. PS owns the bus: I2C0 passes through, CE follows the PS line
    if (scl_pad !== 1 || sda_pad !== 1) fail("bus not idle after reset");
    emio_scl_t <= 0; repeat (3) @(posedge clk);
    if (scl_pad !== 0 || emio_scl_i !== 0) fail("PS SCL does not reach the pad");
    emio_scl_t <= 1; emio_sda_t <= 0; repeat (3) @(posedge clk);
    if (sda_pad !== 0 || emio_sda_i !== 0 || scl_pad !== 1) fail("PS SDA does not reach the pad");
    emio_sda_t <= 1; repeat (3) @(posedge clk);
    if (ce_t !== 1) fail("CE driven although the PS line is an input");
    emio_ce_t <= 0; emio_ce_o <= 0; repeat (3) @(posedge clk);
    if (ce_t !== 0 || ce_o !== 0) fail("PS CE does not reach the pad");
    expect_reg(PIN_STATE, 32'hF000, 32'h6000, "PIN_STATE: ce 0, scl 1, sda 1, i2c_pl 0");
    emio_ce_t <= 1;
    n_start = 0; n_stop = 0;

    // ---- 2. engine takes the pins with src = 3: the reader owns the bus, CE = ADF_PINS.ce
    wr(DET_CFG, 3);
    wr(CTRL, C_OWNER);
    expect_reg(PIN_STATE, 32'hF000, 32'hF000, "PIN_STATE: ce 1, i2c_pl 1");
    if (ce_t !== 0 || ce_o !== 1) fail("engine does not drive CE high");
    wr(ADF_PINS, 0); repeat (3) @(posedge clk);
    if (ce_o !== 0) fail("ADF_PINS.ce = 0 not on the pin");
    wr(ADF_PINS, 1);
    emio_sda_t <= 0; repeat (3) @(posedge clk);                 // the PS must not reach the bus now
    if (sda_pad !== 1 || emio_sda_i !== 1) fail("PS drives the bus although the reader owns it");
    emio_sda_t <= 1;

    // ---- 3. sweep: 3 points x N_AVG 2 = 6 conversions
    wr(T_MIN, 5); wr(T_SETTLE, 5);
    wr(ADC_T_CONV, 300);
    wr(N_AVG, 2);
    load_points(3);
    wr(CTRL, C_OWNER | C_START);
    wait_status(S_DONE | S_BUSY, S_DONE, "ADC sweep");
    expect_reg(POINT_COUNT, 32'hFFFF, 3, "POINT_COUNT");
    wr(RESULT_ADDR, 0);
    for (int i = 0; i < 3; i++) begin
      want = 0;
      for (int k = 0; k < 2; k++) want += (conv[2*i + k] < 0) ? 0 : int'(conv[2*i + k]);
      rd(RESULT_DATA, d);
      if (d !== want) fail($sformatf("result %0d: %08x, expected %08x", i, d, want));
    end
    if (n_cfg_writes != 6 || n_conv_reads != 6) fail($sformatf("%0d config writes, %0d reads, expected 6 / 6", n_cfg_writes, n_conv_reads));
    if (s_cfg !== 16'hC3E3) fail($sformatf("config word on the bus %04x", s_cfg));
    if (n_start != 18 || n_stop != 18) fail($sformatf("%0d starts, %0d stops, expected 18 / 18", n_start, n_stop));
    if (min_wait < 300us) fail($sformatf("conversion read %0t after the config write, must wait 300 us", min_wait));
    if (scl_period != 2800ns) fail($sformatf("SCL period %0t, expected 2.8 us", scl_period));
    expect_reg(ADC_STAT, 32'hFF03_FFFF, {8'd6, 8'h00, 16'(conv[5])}, "ADC_STAT after the sweep");
    #3ms;
    if (n_cfg_writes != 6) fail("a conversion was started outside SAMPLE");
    if (scl_pad !== 1 || sda_pad !== 1) fail("bus not idle after the sweep");

    // ---- 4. faster bus
    wr(ADC_I2C_DIV, 25);
    wr(N_AVG, 1); load_points(1);
    wr(CTRL, C_OWNER | C_START);
    wait_status(S_DONE | S_BUSY, S_DONE, "sweep at 1 MHz");
    if (scl_period != 1000ns) fail($sformatf("SCL period %0t, expected 1 us", scl_period));
    wr(RESULT_ADDR, 0); rd(RESULT_DATA, d);
    if (d !== 32'(conv[6])) fail("result at 1 MHz");
    wr(ADC_I2C_DIV, 70);

    // ---- 5. no ADC at this address: the sweep still ends, sample 0, err_nack
    wr(ADC_CFG, 32'h0049_C3E3);
    wr(N_AVG, 2); load_points(1);
    wr(CTRL, C_OWNER | C_START);
    wait_status(S_DONE | S_BUSY, S_DONE, "sweep without an ADC");
    wr(RESULT_ADDR, 0); rd(RESULT_DATA, d);
    if (d !== 0) fail("NACK sample is not 0");
    expect_reg(ADC_STAT, 32'h0001_0000, 32'h0001_0000, "err_nack");
    if (scl_pad !== 1 || sda_pad !== 1) fail("bus not idle after a NACK");
    wr(ADC_CFG, 32'h0048_C3E3);
    wr(CTRL, C_OWNER | C_START);
    wait_status(S_DONE | S_BUSY, S_DONE, "sweep after the NACK");
    expect_reg(ADC_STAT, 32'h0001_0000, 0, "err_nack cleared by start");
    wr(RESULT_ADDR, 0); rd(RESULT_DATA, d);
    if (d !== 32'(conv[7]) + 32'(conv[8])) fail("result after the NACK");

    // ---- 6. abort during the conversion wait
    wr(ADC_T_CONV, 50000);
    wr(CTRL, C_OWNER | C_START);
    wait_status(S_WAIT, S_WAIT, "SAMPLE");
    #400us;                                                     // config write done, waiting
    wr(CTRL, C_OWNER | C_ABORT);
    wait_status(S_DONE | S_BUSY | S_ABORTED, S_DONE | S_ABORTED, "abort");
    #10us;
    expect_reg(ADC_STAT, 32'h0002_0000, 0, "reader idle after abort");
    if (scl_pad !== 1 || sda_pad !== 1 || s_active) fail("bus not idle after abort");
    expect_reg(POINT_COUNT, 32'hFFFF, 0, "no result after abort");
    wr(ADC_T_CONV, 300);

    // ---- 7. src back to PS push: the PS has the bus again
    wr(DET_CFG, 0);
    expect_reg(PIN_STATE, 32'h8000, 0, "i2c_pl = 0 with src 0");
    emio_sda_t <= 0; repeat (3) @(posedge clk);
    if (sda_pad !== 0) fail("PS SDA does not reach the pad after the hand-back");
    emio_sda_t <= 1;
    wr(CTRL, 0);
    repeat (3) @(posedge clk);
    if (ce_t !== 1) fail("CE still driven after the pins went back to the PS");

    $display("TB PASS");
    $finish;
  end

  initial begin #400ms; fail("global timeout"); end
endmodule
