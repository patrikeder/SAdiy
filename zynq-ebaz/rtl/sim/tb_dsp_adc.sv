// Standalone test of the two ADC adapters (rtl/dsp/adc_ad9226.sv, adc_spi_sar.sv) with behavioural ADCs:
// every conversion must arrive once, in order, converted to the sample stream format, and the pins must be
// taken away from the ADC's output transitions (the models drive X there).
`timescale 1ns / 1ps
module tb_dsp_adc;
  logic clk = 0, resetn = 0;
  always #5 clk = ~clk;

  task automatic fail(input string why);
    $display("TB FAIL: %s (time %0t)", why, $time);
    $finish;
  endtask

  // ------------------------------------------------------------ AD9226
  logic p_en = 0, p_twos = 0, adc_clk, p_valid, p_ovr;
  logic [7:0] p_div = 8'd4, p_phase = 8'd3;
  logic [11:0] adc_d = '0;
  logic adc_otr = 0;
  logic signed [15:0] p_data;
  adc_ad9226 u_par (.clk, .resetn, .enable(p_en), .div(p_div), .phase(p_phase), .twos(p_twos),
                    .adc_clk, .adc_d, .adc_otr, .valid(p_valid), .data(p_data), .ovr(p_ovr));

  logic [12:0] codes [$];                       // {otr, code} the model has put out
  int unsigned seed = 1;
  time t_rise = 0, clk_period = 0;
  always @(posedge adc_clk) begin
    automatic logic [12:0] c = 13'($urandom(seed));
    clk_period = $time - t_rise; t_rise = $time;
    #2 adc_d = 'x; adc_otr = 'x;                // t_OD: outputs change 2 .. 7 ns after the clock edge
    #5 adc_d = c[11:0]; adc_otr = c[12];
    codes.push_back(c);
  end
  int p_n = 0;
  logic signed [15:0] want;
  always @(posedge clk) if (resetn && p_valid) begin
    automatic logic [12:0] c;
    if ($isunknown(p_data) || $isunknown(p_ovr)) fail("AD9226: sampled during the output transition");
    if (p_n > 0) begin                          // the first sample may be from before the first conversion
      if (codes.size() == 0) fail("AD9226: sample without a conversion");
      // the sample is one of the last two codes: accept the oldest not yet used
      c = codes.pop_front();
      want = p_twos ? {c[11:0], 4'b0} : {~c[11], c[10:0], 4'b0};
      if (p_data !== want || p_ovr !== c[12])
        fail($sformatf("AD9226 sample %0d: %04x ovr %b, expected %04x ovr %b", p_n, p_data, p_ovr, want, c[12]));
    end else codes.delete();
    p_n++;
  end

  task automatic run_parallel(input int div, input int phase, input bit twos, input int samples);
    p_en <= 0; repeat (4) @(posedge clk);
    codes.delete(); p_n = 0;
    p_div <= 8'(div); p_phase <= 8'(phase); p_twos <= twos; p_en <= 1;
    while (p_n < samples) @(posedge clk);
    if (clk_period != div * 10) fail($sformatf("AD9226 clock period %0t for div %0d", clk_period, div));
    p_en <= 0;
  endtask

  // ------------------------------------------------------------ SPI SAR ADC
  logic s_en = 0, cnv, sck, sdo = 0, s_valid, s_ovr;
  logic [15:0] s_period = 16'd400, s_tconv = 16'd50;
  logic [7:0] s_div = 8'd3;
  logic signed [15:0] s_data;
  adc_spi_sar u_spi (.clk, .resetn, .enable(s_en), .period(s_period), .t_conv(s_tconv), .sck_div(s_div),
                     .cnv, .sck, .sdo, .valid(s_valid), .data(s_data), .ovr(s_ovr));

  logic [15:0] sar_sh, sar_codes [$];
  time t_cnv = 0, conv_time = 0, cnv_period = 0;
  int n_sck = 0;
  always @(posedge cnv) begin cnv_period = $time - t_cnv; t_cnv = $time; end
  always @(negedge cnv) if (resetn) begin
    automatic logic [15:0] c = 16'($urandom(seed));
    conv_time = $time - t_cnv;
    sar_codes.push_back(c); sar_sh = c; n_sck = 0;
    #3 sdo = c[15];                             // MSB after CNV falls
  end
  always @(posedge sck) n_sck++;
  always @(negedge sck) begin
    sar_sh = {sar_sh[14:0], 1'b0};
    #1 sdo = 'x;                                // changes after the falling edge
    #6 sdo = sar_sh[15];
  end
  int s_n = 0;
  always @(posedge clk) if (resetn && s_valid) begin
    automatic logic [15:0] c = sar_codes.pop_front();
    if (s_data !== {1'b0, c[15:1]}) fail($sformatf("SAR sample %0d: %04x, code %04x", s_n, s_data, c));
    if (n_sck != 16) fail($sformatf("SAR: %0d clocks in a frame, sample %0d, period %0d div %0d", n_sck, s_n, s_period, s_div));
    if (s_ovr !== 0) fail("SAR ovr");
    s_n++;
  end

  task automatic run_spi(input int period, input int tconv, input int div, input int samples);
    s_en <= 0; repeat (4) @(posedge clk);
    sar_codes.delete(); s_n = 0;
    s_period <= 16'(period); s_tconv <= 16'(tconv); s_div <= 8'(div); s_en <= 1;
    while (s_n < samples) @(posedge clk);
    if (conv_time != tconv * 10) fail($sformatf("CNV high %0t, expected %0d clocks", conv_time, tconv));
    s_en <= 0;
  endtask

  initial begin
    repeat (4) @(posedge clk); resetn <= 1; repeat (2) @(posedge clk);
    run_parallel(4, 3, 0, 200);       // 25 MSPS
    run_parallel(4, 3, 1, 50);        // two's complement
    run_parallel(2, 1, 0, 200);       // 50 MSPS
    run_parallel(10, 6, 0, 50);       // 10 MSPS
    run_spi(400, 50, 3, 40);          // 250 kSPS
    if (cnv_period != 4000) fail($sformatf("SAR sample period %0t, expected 4 us", cnv_period));
    run_spi(1000, 200, 5, 20);        // 100 kSPS
    if (cnv_period != 10000) fail($sformatf("SAR sample period %0t, expected 10 us", cnv_period));
    run_spi(10, 20, 3, 10);           // period too short: back to back, still correct
    $display("TB PASS");
    $finish;
  end
  initial begin #100ms; fail("global timeout"); end
endmodule
