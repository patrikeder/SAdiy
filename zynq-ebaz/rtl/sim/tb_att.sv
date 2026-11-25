// Self-checking testbench for the PCF8574 attenuator path, the I2C pin mux and the CE pin, through sadiy_top
// (docs/rtl-spec.md section 9, register map 2.0). A behavioural PCF8574 (I2C slave, write only) answers on the
// pads and logs every port byte with its time.
// Scenarios: PS I2C0 passes through while the PS owns the bus; taking the pins hands the bus to the engine and
// sends PE4302.manual as one byte; a decrease of the attenuation is sent make-before-break (make byte, then the
// final byte, in one transaction, make held one byte); an increase is one byte; port mapping V1..V3 -> P0..P2,
// V4..V6 -> P4..P6, P3 / P7 from ATT_I2C; active-low modules (make = old AND new); SCL at 100 kHz and with
// another divider; sweep entries switch the attenuator before their SPI word; a wrong address (NACK) sets
// ATT_STAT.err_nack, start clears it; PE4302 writes while the PS owns the pins send nothing; the PS gets the
// bus back with the pins; CE follows ADF_PINS.ce.
`timescale 1ns / 1ps
module tb_att;
  localparam logic [11:0] CTRL = 12'h008, STATUS = 12'h00C, N_ENTRIES = 12'h010, N_AVG = 12'h014,
    T_MIN = 12'h020, T_SETTLE = 12'h02C, PE4302 = 12'h030, PIN_STATE = 12'h034,
    DET_CFG = 12'h038, POINT_COUNT = 12'h048, TABLE_ADDR = 12'h060, TABLE_W0 = 12'h064, TABLE_W1 = 12'h068,
    ATT_I2C = 12'h080, ATT_I2C_DIV = 12'h084, ATT_STAT = 12'h088, ADF_PINS = 12'h090;
  localparam logic [31:0] C_START = 32'h01, C_OWNER = 32'h10;
  localparam logic [31:0] S_BUSY = 32'h01, S_DONE = 32'h02;
  localparam logic [31:0] W1_SPI = 32'h100, W1_ATT = 32'h200, W1_MEASURE = 32'h400, W1_SKIP_LOCK = 32'h800;

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
  logic adf_le;
  logic slave_sda = 1;                              // 1 = the PCF8574 releases SDA
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
    .emio_adf_clk(1'b0), .emio_adf_dat(1'b0), .emio_adf_le(1'b1),
    .emio_ce_o, .emio_ce_t, .emio_scl_o, .emio_scl_t, .emio_sda_o, .emio_sda_t, .emio_scl_i, .emio_sda_i,
    .adf4351_clk(), .adf4351_dat(), .adf4351_le(adf_le), .adf4351_ld(1'b0),
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

  task automatic wait_att_idle();
    logic [31:0] d;
    int n;
    repeat (4) @(posedge clk);                      // the write strobe has reached the driver
    n = 0;
    d = 32'h0002_0000;
    while (d[17] && n < 100000) begin
      rd(ATT_STAT, d);
      n++;
    end
    if (d[17]) fail("attenuator stays busy");
  endtask

  // ---------------------------------------------------------------- behavioural PCF8574 (write only)
  localparam logic [6:0] SLAVE_ADDR = 7'h27;
  logic [7:0]  ssh;
  logic [7:0]  port = 8'hFF;                        // power-up: all ports high
  int   sbit = 0, s_bytei = 0;
  bit   s_active = 0;
  int   n_start = 0, n_stop = 0, n_port = 0;
  logic [7:0] port_log [0:63];
  time  port_t [0:63];
  time  t_scl_rise = 0, scl_period = 0;
  bit   bus_on = 0;                                 // between any START and STOP (whoever is addressed)
  int   n_scl = 0, last_scl = 0;                    // SCL pulses of the transaction in progress / the last one

  always @(negedge sda_pad) if (scl_pad && resetn) begin        // START
    s_active = 1; sbit = 0; s_bytei = 0; n_start++;
    bus_on = 1; n_scl = 0;
  end
  always @(posedge sda_pad) if (scl_pad && resetn) begin        // STOP
    if (s_active || s_bytei > 0) n_stop++;
    s_active = 0; slave_sda = 1;
    if (bus_on) last_scl = n_scl;
    bus_on = 0;
  end
  always @(posedge scl_pad) if (bus_on) n_scl++;
  always @(posedge scl_pad) begin
    if (s_active) begin
      if (sbit < 8) ssh = {ssh[6:0], sda_pad};
      if (sbit >= 1 && sbit <= 7) scl_period = $time - t_scl_rise;
      t_scl_rise = $time;
      sbit++;
    end
  end
  always @(negedge scl_pad) if (s_active) begin
    if (sbit == 8) begin                                        // ack slot begins
      if (s_bytei == 0) begin
        if (ssh[7:1] != SLAVE_ADDR || ssh[0]) begin s_active = 0; slave_sda = 1; end   // not us: no ACK
        else slave_sda = 0;
      end else begin
        slave_sda = 0;
        port = ssh;                                             // the PCF8574 takes the byte at its ACK
        port_log[n_port] = ssh; port_t[n_port] = $time; n_port++;
      end
    end else if (sbit == 9) begin                               // ack slot ends
      sbit = 0; s_bytei++; slave_sda = 1;
    end
  end

  // ---------------------------------------------------------------- helpers
  function automatic logic [7:0] pbyte(input logic [5:0] v, input logic p3, input logic p7);
    return {p7, v[5], v[4], v[3], p3, v[2], v[1], v[0]};
  endfunction

  task automatic expect_ports(input int first, input int n, input logic [7:0] b0, input logic [7:0] b1, input string what);
    if (n_port != first + n) fail($sformatf("%s: %0d port bytes, expected %0d", what, n_port - first, n));
    if (port_log[first] !== b0) fail($sformatf("%s: byte 0 = %02x, expected %02x", what, port_log[first], b0));
    if (n == 2 && port_log[first + 1] !== b1) fail($sformatf("%s: byte 1 = %02x, expected %02x", what, port_log[first + 1], b1));
  endtask

  int p0, s0;
  time t_le;

  initial begin
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
    expect_reg(ATT_I2C, 32'hFFFF_FFFF, 32'h0000_0327, "ATT_I2C reset: 0x27, p3 1, p7 1");
    expect_reg(ATT_I2C_DIV, 32'hFFFF_FFFF, 250, "ATT_I2C_DIV reset 250 (100 kHz)");
    expect_reg(ATT_STAT, 32'h00FF_FFFF, 32'h0000_FF3F, "ATT_STAT reset: levels 0x3F, byte 0xFF");
    n_start = 0; n_stop = 0;                                    // the PS's test levels above were no transactions
    wr(PE4302, 32'h100);                                        // stored only: the PS owns the pins
    #300us;
    if (n_start != 0 || n_port != 0) fail("PE4302 write sent something while the PS owns the pins");

    // ---- 2. engine takes the pins: bus and CE to the engine, PE4302.manual (0) as one byte
    wr(CTRL, C_OWNER);
    expect_reg(PIN_STATE, 32'hF000, 32'hF000, "PIN_STATE: ce 1, i2c_pl 1");
    if (ce_t !== 0 || ce_o !== 1) fail("engine does not drive CE high");
    wr(ADF_PINS, 0); repeat (3) @(posedge clk);
    if (ce_o !== 0) fail("ADF_PINS.ce = 0 not on the pin");
    wr(ADF_PINS, 1);
    emio_sda_t <= 0; repeat (3) @(posedge clk);                 // the PS must not reach the bus now
    if (emio_sda_i !== 1) fail("PS sees the bus although the engine owns it");
    emio_sda_t <= 1;
    wait_att_idle();
    expect_ports(0, 1, pbyte(6'h00, 1, 1), 8'h00, "take the pins");
    if (n_start != 1 || n_stop != 1) fail($sformatf("take: %0d starts, %0d stops", n_start, n_stop));
    if (scl_period != 10000ns) fail($sformatf("SCL period %0t, expected 10 us", scl_period));
    expect_reg(ATT_STAT, 32'hFF03_FFFF, {8'd1, 8'h00, pbyte(6'h00, 1, 1), 8'h00}, "ATT_STAT after the take");

    // ---- 3. increase (0x00 -> 0x09: V1, V4): one byte; mapping V1 -> P0, V4 -> P4
    p0 = n_port; s0 = n_start;
    wr(PE4302, 32'h109); wait_att_idle();
    expect_ports(p0, 1, 8'b1001_1001, 8'h00, "increase to V1 + V4");
    if (n_start != s0 + 1) fail("increase: not one transaction");

    // ---- 4. decrease (0x09 -> 0x24: V3, V6): make 0x2D, then 0x24, one transaction, make held one byte
    p0 = n_port; s0 = n_start;
    wr(PE4302, 32'h124); wait_att_idle();
    expect_ports(p0, 2, 8'b1101_1101, 8'b1100_1100, "decrease make-before-break");
    if (last_scl != 28) fail($sformatf("make-before-break transaction: %0d SCL rises, expected 3 x 9 + the STOP", last_scl));
    if (n_start != s0 + 1) fail("make and final not in one transaction");
    if (port_t[p0 + 1] - port_t[p0] < 85us) fail($sformatf("make state held %0t, expected one byte (90 us)", port_t[p0 + 1] - port_t[p0]));
    expect_reg(ATT_STAT, 32'h0000_FF3F, {16'h0, 8'b1100_1100, 8'h24}, "ATT_STAT levels / byte after the decrease");

    // ---- 5. all stages out, then all in, with P3 / P7 low: each port bit and the fixed bits
    wr(ATT_I2C, 32'h0000_0027);                                 // p3 0, p7 0
    p0 = n_port;
    wr(PE4302, 32'h100); wait_att_idle();
    expect_ports(p0, 2, pbyte(6'h24, 0, 0), pbyte(6'h00, 0, 0), "all out with p3 / p7 = 0");
    p0 = n_port;
    wr(PE4302, 32'h13F); wait_att_idle();
    expect_ports(p0, 1, 8'b0111_0111, 8'h00, "all in: P0..P2, P4..P6 high, P3 / P7 low");
    wr(ATT_I2C, 32'h0000_0327);
    p0 = n_port;
    wr(PE4302, 32'h13F); wait_att_idle();
    if (n_port != p0) fail("rewriting the same value sent a transaction");

    // ---- 6. active low module: make = old AND new
    wr(PE4302, 32'h03F);                                        // active_high 0, same levels: nothing sent
    p0 = n_port;
    wr(PE4302, 32'h001);                                        // fewer high levels = more attenuation: one byte
    wait_att_idle();
    expect_ports(p0, 1, pbyte(6'h01, 1, 1), 8'h00, "active low: switching stages in");
    p0 = n_port;
    wr(PE4302, 32'h006);                                        // make = 0x01 & 0x06 = 0
    wait_att_idle();
    expect_ports(p0, 2, pbyte(6'h00, 1, 1), pbyte(6'h06, 1, 1), "active low: make = old AND new");
    wr(PE4302, 32'h13F); wait_att_idle();

    // ---- 7. sweep: the attenuator finishes before the entry's SPI word
    wr(DET_CFG, 1);                                             // test generator: no detector needed
    wr(T_MIN, 5); wr(T_SETTLE, 5); wr(N_AVG, 1);
    wr(TABLE_ADDR, 0);
    wr(TABLE_W0, 32'h0000_0005); wr(TABLE_W1, W1_ATT | W1_SPI | W1_MEASURE | W1_SKIP_LOCK | 32'h00);   // 31.5 -> 0 dB
    wr(TABLE_W0, 32'h0000_0005); wr(TABLE_W1, W1_ATT | W1_SPI | W1_MEASURE | W1_SKIP_LOCK | 32'h10);   // 8 dB
    wr(N_ENTRIES, 2);
    p0 = n_port;
    t_le = 0;
    fork
      begin @(negedge adf_le); t_le = $time; end
      begin
        wr(CTRL, C_OWNER | C_START);
        wait_status(S_DONE | S_BUSY, S_DONE, "sweep");
      end
    join
    expect_reg(POINT_COUNT, 32'hFFFF, 2, "POINT_COUNT");
    if (n_port != p0 + 3) fail($sformatf("sweep: %0d port bytes, expected 3", n_port - p0));
    if (port_log[p0] !== pbyte(6'h3F, 1, 1) || port_log[p0 + 1] !== pbyte(6'h00, 1, 1)
        || port_log[p0 + 2] !== pbyte(6'h10, 1, 1)) fail("sweep: wrong port bytes");
    if (t_le == 0 || t_le < port_t[p0 + 1]) fail("the first SPI word started before the attenuator was set");
    expect_reg(ATT_STAT, 32'h0000_003F, 32'h10, "levels after the sweep");

    // ---- 8. wrong address: NACK, err_nack sticky, the bus idle, start clears it
    wr(ATT_I2C, 32'h0000_0326);
    p0 = n_port;
    wr(PE4302, 32'h101); wait_att_idle();
    if (n_port != p0) fail("a byte reached the PCF8574 at the wrong address");
    if (last_scl != 10) fail($sformatf("NACK of the address: %0d SCL rises, expected 9 + the STOP", last_scl));
    expect_reg(ATT_STAT, 32'h0001_0000, 32'h0001_0000, "err_nack after a NACK");
    if (scl_pad !== 1 || sda_pad !== 1) fail("bus not idle after a NACK");
    wr(ATT_I2C, 32'h0000_0327);
    wr(TABLE_ADDR, 0); wr(TABLE_W0, 0); wr(TABLE_W1, W1_MEASURE | W1_SKIP_LOCK); wr(N_ENTRIES, 1);
    wr(CTRL, C_OWNER | C_START);
    wait_status(S_DONE | S_BUSY, S_DONE, "sweep after the NACK");
    expect_reg(ATT_STAT, 32'h0001_0000, 0, "err_nack cleared by start");

    // ---- 9. faster bus (the divider)
    wr(ATT_I2C_DIV, 25);
    wr(PE4302, 32'h13F); wait_att_idle();
    if (scl_period != 1000ns) fail($sformatf("SCL period %0t at div 25, expected 1 us", scl_period));
    if (port !== pbyte(6'h3F, 1, 1)) fail("port not at all-in");
    wr(ATT_I2C_DIV, 250);

    // ---- 10. pins back to the PS: bus and CE released
    wr(CTRL, 0);
    expect_reg(PIN_STATE, 32'h8000, 0, "i2c_pl = 0 after the hand-back");
    emio_sda_t <= 0; repeat (3) @(posedge clk);
    if (sda_pad !== 0) fail("PS SDA does not reach the pad after the hand-back");
    emio_sda_t <= 1;
    repeat (3) @(posedge clk);
    if (ce_t !== 1) fail("CE still driven after the pins went back to the PS");
    p0 = n_port;
    wr(PE4302, 32'h100); #300us;
    if (n_port != p0) fail("PE4302 write sent something after the hand-back");

    $display("TB PASS");
    $finish;
  end

  initial begin #400ms; fail("global timeout"); end
endmodule
