// Standalone test of rtl/dsp/iq_power.sv against sadiy_ebaz.dspref.power_ref (vectors/dsp_pwr_*.hex):
// one sample per clock and with gaps, the user field stays with its sample.
`timescale 1ns / 1ps
module tb_dsp_power;
  logic clk = 0, resetn = 0;
  always #5 clk = ~clk;
  logic s_valid = 0, m_valid;
  logic signed [23:0] s_re = '0, s_im = '0;
  logic [12:0] s_user = '0, m_user;
  logic [27:0] m_pwr;

  iq_power dut (.*);

  task automatic fail(input string why);
    $display("TB FAIL: %s (time %0t)", why, $time);
    $finish;
  endtask

  logic [47:0] vin [0:255];
  logic [27:0] vout [0:255];
  logic [31:0] meta [0:0];
  int n_out = 0;
  always @(posedge clk) if (resetn && m_valid) begin
    if (m_user !== 13'(n_out)) fail($sformatf("user field %0d at output %0d", m_user, n_out));
    if (m_pwr !== vout[n_out]) fail($sformatf("sample %0d: %07x, reference %07x", n_out, m_pwr, vout[n_out]));
    n_out++;
  end

  initial begin
    $readmemh("vectors/dsp_pwr_in.hex", vin);
    $readmemh("vectors/dsp_pwr_out.hex", vout);
    $readmemh("vectors/dsp_pwr_meta.hex", meta);
    repeat (4) @(posedge clk); resetn <= 1; repeat (2) @(posedge clk);
    for (int i = 0; i < meta[0]; i++) begin
      s_valid <= 1; {s_re, s_im} <= vin[i]; s_user <= 13'(i);
      @(posedge clk);
      if (i % 11 == 5) begin s_valid <= 0; s_re <= 'x; repeat (3) @(posedge clk); end
    end
    s_valid <= 0;
    repeat (10) @(posedge clk);
    if (n_out != meta[0]) fail($sformatf("%0d outputs, expected %0d", n_out, meta[0]));
    $display("TB PASS");
    $finish;
  end
endmodule
