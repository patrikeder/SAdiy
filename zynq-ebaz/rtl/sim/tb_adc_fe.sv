// Self-checking testbench for the ADC front end (rtl/src/adc_fe.sv, docs/rtl-spec.md section 8d): clock off and
// on, tie-off, the traffic generator (ramp, walking one, tone, constant), status registers, and the pin source with
// a behavioural AD9226 (outputs change 2 .. 7 ns after the clock edge, X in between).
`timescale 1ns / 1ps
module tb_adc_fe;
  logic clk = 0, resetn = 0;
  always #5 clk = ~clk;

  task automatic fail(input string why);
    $display("TB FAIL: %s (time %0t)", why, $time);
    $finish;
  endtask

  logic        enable = 0, twos = 0, clear = 0, tie_otr = 0;
  logic [1:0]  src = 0, tg_mode = 0;
  logic [7:0]  div = 8'd2, phase = 8'd0;
  logic [11:0] tie_code = 12'h800;
  logic [31:0] tg_inc = 32'h36C8B439;
  logic [11:0] adc_d = '0;
  logic        adc_otr = 0, adc_clk, valid, ovr, last_otr, otr_seen;
  logic signed [15:0] data;
  logic [11:0] last_code;
  logic [15:0] count;

  adc_fe dut (.clk, .resetn, .enable, .src, .twos, .tg_mode, .clear, .div, .phase, .tie_code, .tie_otr, .tg_inc,
              .adc_clk, .adc_d, .adc_otr, .valid, .data, .ovr, .last_code, .last_otr, .otr_seen, .count);

  // reference sine table: read once from the ROM of the IF path (its contents are checked bit for bit in tb_if)
  logic [10:0] ra = '0;
  logic signed [15:0] rsin, rcos;
  logic signed [15:0] tbl [0:2047];
  nco_rom u_ref (.clk, .addr_s(ra), .addr_c(11'd0), .sin(rsin), .cos(rcos));
  function automatic logic [11:0] rom_code(input logic [31:0] ph);
    logic signed [15:0] v;
    v = tbl[ph[31:21]];
    return {!v[15], v[14:4]};
  endfunction

  // ---- sample collection ----
  logic [11:0] codes [$];
  logic        otrs  [$];
  time         t_valid [$];
  always @(posedge clk) if (valid) begin
    if ($isunknown(data) || $isunknown(ovr)) fail("sample with X");
    codes.push_back(twos ? data[15:4] : {!data[15], data[14:4]});
    otrs.push_back(ovr);
    t_valid.push_back($time);
  end

  task automatic collect(input int n);
    codes.delete(); otrs.delete(); t_valid.delete();
    while (codes.size() < n) @(posedge clk);
  endtask

  task automatic start(input int d, input bit en);
    enable <= 0; repeat (6) @(posedge clk);
    div <= 8'(d); enable <= en; repeat (3) @(posedge clk);
  endtask

  // ---- pin model of the AD9226 (as in tb_dsp_adc) ----
  logic [12:0] pin_codes [$];
  int unsigned seed = 7;
  logic        model_on = 0;
  always @(posedge adc_clk) if (model_on) begin
    automatic logic [12:0] c = 13'($urandom(seed));
    #2 adc_d = 'x; adc_otr = 'x;
    #5 adc_d = c[11:0]; adc_otr = c[12];
    pin_codes.push_back(c);
  end

  initial begin
    for (int i = 0; i < 2048; i++) begin
      ra <= 11'(i); @(posedge clk); @(posedge clk); #1 tbl[i] = rsin;
    end
    repeat (4) @(posedge clk);
    resetn <= 1;
    repeat (4) @(posedge clk);

    // ---- clock off: the pin stays low, no samples
    repeat (60) @(posedge clk);
    if (adc_clk !== 1'b0 || codes.size() != 0 || count !== 16'd0) fail("clock or samples while disabled");

    // ---- tie-off: constant, one sample per div clocks, status
    for (int k = 0; k < 4; k++) begin
      automatic int d = (k == 0) ? 2 : (k == 1) ? 3 : (k == 2) ? 4 : 7;
      src <= 0; tie_code <= 12'h123; tie_otr <= 0; clear <= 1; @(posedge clk); clear <= 0;
      start(d, 1);
      collect(40);
      foreach (codes[i]) if (i > 0 && codes[i] !== 12'h123) fail($sformatf("tie-off code %03x (div %0d)", codes[i], d));
      for (int i = 3; i < 40; i++)
        if (t_valid[i] - t_valid[i-1] != d * 10) fail($sformatf("sample spacing %0t for div %0d", t_valid[i] - t_valid[i-1], d));
      if (last_code !== 12'h123 || last_otr !== 1'b0 || otr_seen !== 1'b0) fail("tie-off status");
      if (count < 40) fail("count does not count");
    end

    // ---- OTR sticky and clear
    tie_otr <= 1; collect(10);
    if (otr_seen !== 1'b1 || last_otr !== 1'b1) fail("otr_seen not set");
    tie_otr <= 0; collect(10);
    if (otr_seen !== 1'b1) fail("otr_seen not sticky");
    clear <= 1; @(posedge clk); clear <= 0; @(posedge clk);
    if (otr_seen !== 1'b0 || count > 16'd2) fail("clear");

    // ---- two's complement strap
    twos <= 1; tie_code <= 12'hF00; collect(10);
    for (int i = 1; i < 10; i++) if (codes[i] !== 12'hF00) fail("twos code");
    if (last_code !== 12'hF00) fail("twos last_code");
    twos <= 0;

    // ---- traffic generator: ramp
    for (int k = 0; k < 3; k++) begin
      automatic int d = (k == 0) ? 2 : (k == 1) ? 5 : 3;
      src <= 1; tg_mode <= 0; start(d, 1);
      collect(5000);
      for (int i = 6; i < 5000; i++)
        if (codes[i] !== 12'(codes[i-1] + 12'd1)) fail($sformatf("ramp: %03x after %03x at %0d (div %0d)", codes[i], codes[i-1], i, d));
      foreach (codes[i]) if (i > 5 && otrs[i] !== (codes[i] == 12'hFFF)) fail("ramp OTR only at 4095");
    end

    // ---- walking one
    src <= 1; tg_mode <= 1; start(2, 1); collect(60);
    for (int i = 6; i < 60; i++) begin
      if ($countones(codes[i]) != 1) fail("walking one: not a single bit");
      if (codes[i] !== ((codes[i-1] == 12'h800) ? 12'h001 : (codes[i-1] << 1))) fail($sformatf("walking one: %03x after %03x", codes[i], codes[i-1]));
    end

    // ---- constant generator mode
    tg_mode <= 3; tie_code <= 12'h5A5; start(2, 1); collect(20);
    for (int i = 6; i < 20; i++) if (codes[i] !== 12'h5A5) fail("constant generator mode");

    // ---- tone: matches the sine ROM, offset 0 .. 3 phase steps
    tg_mode <= 2; start(2, 1); collect(400);
    begin
      automatic int off = -4;
      for (int o = -3; o < 8 && off < -3; o++) begin
        automatic bit ok = 1;
        for (int i = 6; i < 40; i++) if (codes[i] !== rom_code(32'(i + o) * tg_inc)) ok = 0;
        if (ok) off = o;
      end
      if (off < -3) fail("tone does not follow the sine table");
      for (int i = 6; i < 400; i++) if (codes[i] !== rom_code(32'(i + off) * tg_inc)) fail($sformatf("tone sample %0d", i));
    end

    // ---- pins: behavioural AD9226, three clock divisors, every phase of the period
    for (int dd = 2; dd <= 4; dd++) begin
      for (int ph = 0; ph < dd; ph++) begin
        src <= (dd == 3) ? 2'd3 : 2'd2; model_on = 1; twos <= (ph == 1);      // src 3 is the pins as well
        phase <= 8'(ph);
        enable <= 0; repeat (6) @(posedge clk); pin_codes.delete();
        div <= 8'(dd); enable <= 1;
        codes.delete(); otrs.delete(); t_valid.delete();
        while (codes.size() < 60) @(posedge clk);
        // from sample 4 on every sample is the next conversion in order (the first ones predate the first conversion)
        begin
          automatic int j = -1;
          for (int k = 0; k < 6 && j < 0; k++)
            if (pin_codes.size() > k && codes[4] === (twos ? pin_codes[k][11:0] : pin_codes[k][11:0])) j = k;
          if (j < 0) fail($sformatf("pin source div %0d phase %0d: sample 4 (%03x) is no conversion", dd, ph, codes[4]));
          for (int i = 4; i < 60; i++) begin
            if (pin_codes.size() <= j + i - 4) fail("pin source: sample without a conversion");
            if (codes[i] !== pin_codes[j + i - 4][11:0] || otrs[i] !== pin_codes[j + i - 4][12])
              fail($sformatf("pin source div %0d phase %0d sample %0d: %03x/%b expected %03x/%b", dd, ph, i, codes[i], otrs[i],
                             pin_codes[j + i - 4][11:0], pin_codes[j + i - 4][12]));
          end
        end
        model_on = 0; twos <= 0;
      end
    end
    src <= 3; phase <= 8'd0; model_on = 1; start(2, 1); collect(20);
    foreach (codes[i]) if (i > 1 && $isunknown(codes[i])) fail("src 3 is not the pins");
    model_on = 0;

    $display("TB PASS: tb_adc_fe");
    $finish;
  end

  initial begin #50ms; fail("timeout"); end
endmodule
