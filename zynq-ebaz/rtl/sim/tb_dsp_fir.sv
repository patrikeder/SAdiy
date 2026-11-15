// Standalone test of rtl/dsp/fir_mac.sv against sadiy_ebaz.dspref.fir_ref (vectors/dsp_fir<k>_*.hex),
// bit for bit: 33-tap Gaussian with decimation 4, 5 extreme taps with saturation, clr restarts the history.
`timescale 1ns / 1ps
module tb_dsp_fir;
  logic clk = 0, resetn = 0;
  always #5 clk = ~clk;

  logic clr = 0, coef_we = 0, s_valid = 0, s_ready, m_valid, m_sat;
  logic [6:0] ntaps = 7'd1;
  logic [7:0] decim = 8'd1;
  logic [4:0] shift = 5'd0;
  logic [5:0] coef_addr = '0;
  logic signed [17:0] coef_data = '0, s_re = '0, s_im = '0, m_re, m_im;

  fir_mac dut (.*);

  task automatic fail(input string why);
    $display("TB FAIL: %s (time %0t)", why, $time);
    $finish;
  endtask

  logic [17:0] vcoef [0:63];
  logic [35:0] vin [0:1023], vout [0:1023];
  logic [31:0] meta [0:4];
  int n_out, case_k, n_sat;

  always @(posedge clk) if (resetn && m_valid) begin
    if ({m_re, m_im} !== vout[n_out])
      fail($sformatf("case %0d output %0d: %05x %05x, reference %09x", case_k, n_out, m_re, m_im, vout[n_out]));
    if (m_sat) n_sat++;
    n_out++;
  end

  task automatic run_case(input int k);
    case_k = k;
    $readmemh($sformatf("vectors/dsp_fir%0d_coef.hex", k), vcoef);
    $readmemh($sformatf("vectors/dsp_fir%0d_in.hex", k), vin);
    $readmemh($sformatf("vectors/dsp_fir%0d_out.hex", k), vout);
    $readmemh($sformatf("vectors/dsp_fir%0d_meta.hex", k), meta);
    for (int i = 0; i < meta[0]; i++) begin
      @(posedge clk); coef_we <= 1; coef_addr <= 6'(i); coef_data <= vcoef[i];
    end
    @(posedge clk); coef_we <= 0;
    ntaps <= meta[0][6:0]; decim <= meta[1][7:0]; shift <= meta[2][4:0];
    clr <= 1; @(posedge clk); clr <= 0; n_out = 0; n_sat = 0;
    for (int i = 0; i < meta[3]; i++) begin
      s_valid <= 1; {s_re, s_im} <= vin[i];
      do @(posedge clk); while (!s_ready);
      if (i % 5 == 0) begin s_valid <= 0; @(posedge clk); end
    end
    s_valid <= 0;
    repeat (100) @(posedge clk);
    if (n_out != meta[4]) fail($sformatf("case %0d: %0d outputs, expected %0d", k, n_out, meta[4]));
  endtask

  initial begin
    repeat (4) @(posedge clk); resetn <= 1; repeat (2) @(posedge clk);
    run_case(0);
    if (n_sat != 0) fail("Gaussian case must not saturate");
    run_case(1);
    if (n_sat == 0) fail("extreme case must saturate");
    run_case(0);            // again after clr: the old history must be gone
    $display("TB PASS");
    $finish;
  end
  initial begin #50ms; fail("global timeout"); end
endmodule
