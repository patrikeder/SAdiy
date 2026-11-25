// Self-checking testbench for the sample generator and the IF path (NCO, mixer, CIC, power) through
// sadiy_top (docs/rtl-spec.md sections 8b, 8c). The expected result words come from the Python reference
// (sadiy_ebaz.ifpath.if_power_ref through the PL model, vectors/if<k>_*.hex) and must match bit for bit.
// Scenarios: three IF sweeps with a digital NCO sweep (sample every clock and every third clock, R = 8, 50, 4,
// saturation with the over-range bit); the video path fed by the generator (negative samples count as 0);
// the det_ext port as the stream with its over-range flag; a free-running generator still gives a result.
`timescale 1ns / 1ps
module tb_if;
  localparam logic [11:0] CTRL = 12'h008, STATUS = 12'h00C, N_ENTRIES = 12'h010, N_AVG = 12'h014,
    T_MIN = 12'h020, T_SETTLE = 12'h02C, DET_CFG = 12'h038, POINT_COUNT = 12'h048,
    TABLE_ADDR = 12'h060, TABLE_W0 = 12'h064, TABLE_W1 = 12'h068, RESULT_ADDR = 12'h070,
    RESULT_DATA = 12'h074, FE_CFG = 12'h0C0, FE_TIE = 12'h0C4, GEN_CFG = 12'h0A0, GEN_ADDR = 12'h0A4, GEN_DATA = 12'h0A8,
    IF_NCO = 12'h0B0, IF_NCO_STEP = 12'h0B4, IF_CIC = 12'h0B8;
  localparam logic [31:0] C_START = 32'h01, C_OWNER = 32'h10, S_BUSY = 32'h01, S_DONE = 32'h02;
  localparam logic [31:0] D_SRC2 = 32'h002, D_MODE_IF = 32'h010, D_STREAM_GEN = 32'h100;
  localparam logic [31:0] G_ENABLE = 32'h8000_0000, G_SYNC = 32'h4000_0000;

  logic clk = 0, resetn = 0;
  always #5 clk = ~clk;

  logic [11:0] awaddr = '0, araddr = '0;
  logic [31:0] wdata = '0, rdata;
  logic awvalid = 0, wvalid = 0, bready = 0, arvalid = 0, rready = 0;
  logic awready, wready, bvalid, arready, rvalid;
  logic [1:0] bresp, rresp;
  logic irq;
  logic ext_valid = 0, ext_ovr = 0;
  logic [15:0] ext_data = '0;

  sadiy_top dut (
    .clk, .resetn,
    .s_axil_awaddr(awaddr), .s_axil_awvalid(awvalid), .s_axil_awready(awready),
    .s_axil_wdata(wdata), .s_axil_wstrb(4'hF), .s_axil_wvalid(wvalid), .s_axil_wready(wready),
    .s_axil_bresp(bresp), .s_axil_bvalid(bvalid), .s_axil_bready(bready),
    .s_axil_araddr(araddr), .s_axil_arvalid(arvalid), .s_axil_arready(arready),
    .s_axil_rdata(rdata), .s_axil_rresp(rresp), .s_axil_rvalid(rvalid), .s_axil_rready(rready),
    .irq,
    .emio_adf_clk(1'b0), .emio_adf_dat(1'b0), .emio_adf_le(1'b1),
    .emio_ce_o(1'b0), .emio_ce_t(1'b1), .emio_scl_o(1'b0), .emio_scl_t(1'b1), .emio_sda_o(1'b0), .emio_sda_t(1'b1),
    .emio_scl_i(), .emio_sda_i(),
    .adf4351_clk(), .adf4351_dat(), .adf4351_le(), .adf4351_ld(1'b0),
    .adf4351_ce_o(), .adf4351_ce_t(), .adf4351_ce_i(1'b1),
    .i2c_scl_o(), .i2c_scl_t(), .i2c_scl_i(1'b1), .i2c_sda_o(), .i2c_sda_t(), .i2c_sda_i(1'b1),
    .det_ext_valid(ext_valid), .det_ext_data(ext_data), .det_ext_ovr(ext_ovr),
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

  task automatic wait_done(input string what);
    logic [31:0] d;
    for (int i = 0; i < 400000; i++) begin
      rd(STATUS, d);
      if ((d & (S_DONE | S_BUSY)) === S_DONE) return;
    end
    fail({"timeout waiting for ", what});
  endtask

  task automatic load_points(input int n);
    wr(TABLE_ADDR, 0);
    for (int i = 0; i < n; i++) begin wr(TABLE_W0, 0); wr(TABLE_W1, 32'hC00); end   // measure, skip_lock
    wr(N_ENTRIES, n);
  endtask

  logic [15:0] pat [0:4095];
  logic [31:0] meta [0:7], want [0:255];
  logic [31:0] d;

  task automatic if_scenario(input int k, input int div);
    int n, points;
    for (int i = 0; i < 4096; i++) pat[i] = 'x;
    $readmemh($sformatf("vectors/if%0d_pattern.hex", k), pat);
    $readmemh($sformatf("vectors/if%0d_meta.hex", k), meta);
    $readmemh($sformatf("vectors/if%0d_result.hex", k), want);
    n = meta[0]; points = meta[7];
    wr(GEN_CFG, 0);
    wr(GEN_ADDR, 0);
    for (int i = 0; i < n; i++) wr(GEN_DATA, {16'd0, pat[i]});
    rd(GEN_ADDR, d);
    if (d !== (n & 12'hFFF)) fail($sformatf("GEN_ADDR %0d after %0d samples", d, n));
    wr(GEN_CFG, G_ENABLE | G_SYNC | ((n - 1) << 16) | div);
    wr(DET_CFG, D_MODE_IF | D_STREAM_GEN);
    wr(IF_NCO, meta[5]);
    wr(IF_NCO_STEP, meta[6]);
    wr(IF_CIC, (meta[3] << 24) | (meta[2] << 16) | meta[1]);
    wr(N_AVG, meta[4]);
    load_points(points);
    wr(CTRL, C_OWNER | C_START);
    wait_done($sformatf("IF scenario %0d", k));
    rd(POINT_COUNT, d);
    if (d !== points) fail($sformatf("scenario %0d: %0d points", k, d));
    wr(RESULT_ADDR, 0);
    for (int i = 0; i < points; i++) begin
      rd(RESULT_DATA, d);
      if (d !== want[i]) fail($sformatf("scenario %0d point %0d: %08x, reference %08x", k, i, d, want[i]));
    end
    // the same sweep again must give the same words (sync restart, NCO base reloaded)
    wr(CTRL, C_OWNER | C_START);
    wait_done("repeat");
    wr(RESULT_ADDR, 0);
    for (int i = 0; i < points; i++) begin
      rd(RESULT_DATA, d);
      if (d !== want[i]) fail($sformatf("scenario %0d repeat, point %0d: %08x, reference %08x", k, i, d, want[i]));
    end
  endtask

  int unsigned vsum;

  initial begin
    repeat (5) @(posedge clk);
    resetn <= 1;
    repeat (5) @(posedge clk);
    wr(T_MIN, 2); wr(T_SETTLE, 2);
    wr(CTRL, C_OWNER);

    if_scenario(0, 1);        // one sample per clock
    if_scenario(1, 3);
    if_scenario(2, 0);        // saturates: over-range bit

    // ---- video path fed by the generator: sum of the first N_AVG samples, negative = 0 (pattern of scenario 2)
    wr(DET_CFG, D_SRC2 | D_STREAM_GEN);
    wr(GEN_CFG, G_ENABLE | G_SYNC | (63 << 16) | 7);
    wr(N_AVG, 40);
    load_points(2);
    wr(CTRL, C_OWNER | C_START);
    wait_done("video sweep");
    vsum = 0;
    for (int i = 0; i < 40; i++) if (!pat[i][15]) vsum += pat[i];
    wr(RESULT_ADDR, 0);
    for (int i = 0; i < 2; i++) begin
      rd(RESULT_DATA, d);
      if (d !== vsum) fail($sformatf("video point %0d: %08x, expected %08x", i, d, vsum));
    end

    // ---- det_ext port as the stream (an ADC adapter): constant samples and the over-range flag
    wr(DET_CFG, D_SRC2);
    ext_data <= 16'd1234; ext_valid <= 1;
    wr(N_AVG, 10);
    wr(CTRL, C_OWNER | C_START);
    wait_done("ext video sweep");
    wr(RESULT_ADDR, 0); rd(RESULT_DATA, d);
    if (d !== 32'd12340) fail($sformatf("ext stream sum %0d", d));
    ext_data <= 16'hF000;                                   // negative: counts as 0
    wr(CTRL, C_OWNER | C_START);
    wait_done("ext negative");
    wr(RESULT_ADDR, 0); rd(RESULT_DATA, d);
    if (d !== 32'd0) fail("negative ext samples must count as 0");
    wr(DET_CFG, D_MODE_IF);                                 // IF path on the port: DC input, NCO at 0 Hz
    ext_data <= 16'd16384; ext_ovr <= 1;
    wr(IF_NCO, 0); wr(IF_NCO_STEP, 0); wr(IF_CIC, (4 << 24) | (5 << 16) | 4);
    wr(N_AVG, 1); load_points(1);
    wr(CTRL, C_OWNER | C_START);
    wait_done("ext IF sweep");
    wr(RESULT_ADDR, 0); rd(RESULT_DATA, d);
    if (!d[30]) fail("over-range of the stream not in result bit 30");
    // DC 16384 * cos(0) = 16383 per sample, CIC gain 64, >> 5: I = 32766, Q = 0: power 32766^2 = 0x3FFE0004
    if ((d & 32'h0FFF_FFFF) !== ((32'd8 << 22) | (32'h3FFE0004 >> 8))) fail($sformatf("ext IF result %08x", d));
    // ---- ADC front end (map 1.3) as the stream: tie-off code = the constant of the det_ext test above
    wr(DET_CFG, D_MODE_IF);
    wr(FE_TIE, 32'h0000_0C00);                              // code 0xC00: (0xC00 - 0x800) << 4 = 16384
    wr(FE_CFG, 32'h0000_0201);                              // enable, tie-off source, div 2
    wr(IF_NCO, 0); wr(IF_NCO_STEP, 0); wr(IF_CIC, (4 << 24) | (5 << 16) | 4);
    wr(N_AVG, 1); load_points(1);
    wr(CTRL, C_OWNER | C_START);
    wait_done("FE tie-off IF sweep");
    wr(RESULT_ADDR, 0); rd(RESULT_DATA, d);
    if (d[30]) fail("FE tie-off: over-range without OTR");
    if ((d & 32'h0FFF_FFFF) !== ((32'd8 << 22) | (32'h3FFE0004 >> 8))) fail($sformatf("FE tie-off IF result %08x", d));
    wr(FE_TIE, 32'h0001_0C00);                              // OTR level high
    wr(CTRL, C_OWNER | C_START);
    wait_done("FE tie-off OTR");
    wr(RESULT_ADDR, 0); rd(RESULT_DATA, d);
    if (!d[30]) fail("FE OTR not in result bit 30");
    // traffic generator tone at the NCO frequency: the mixer gives DC of half the amplitude whatever the phase
    wr(FE_TIE, 32'h0000_0800);
    wr(FE_CFG, 32'h0000_0223);                              // enable, generator, tone, div 2
    wr(IF_NCO, 32'h36C8_B439); wr(IF_CIC, (4 << 24) | (16 << 16) | 64);
    wr(N_AVG, 1); load_points(1);
    wr(CTRL, C_OWNER | C_START);
    wait_done("FE tone IF sweep");
    wr(RESULT_ADDR, 0); rd(RESULT_DATA, d);
    // I = 32752 / 2 * 64^3 >> 16 = 65504 -> power 4.29e9 = 2^32: mantissa 22 bit, exponent about 10
    if (d[30] || d[27:22] < 6'd9 || d[27:22] > 6'd11) fail($sformatf("FE tone result %08x", d));
    wr(FE_CFG, 32'h0000_0200);                              // front end off again
    ext_valid <= 0; ext_ovr <= 0;

    // ---- free-running generator (no sync): a result still arrives and is plausible (not bit-exact)
    wr(DET_CFG, D_MODE_IF | D_STREAM_GEN);
    wr(GEN_CFG, G_ENABLE | (63 << 16) | 1);
    wr(IF_NCO, 32'h2000_0000); wr(IF_CIC, (4 << 24) | (8 << 16) | 8);      // tone at 8 / 64 fs
    wr(N_AVG, 4);
    wr(CTRL, C_OWNER | C_START);
    wait_done("free-running generator");
    wr(RESULT_ADDR, 0); rd(RESULT_DATA, d);
    if (d[27:22] < 6'd8) fail($sformatf("free-running result too small: %08x", d));

    $display("TB PASS");
    $finish;
  end

  initial begin #300ms; fail("global timeout"); end
endmodule
