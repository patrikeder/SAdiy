// Standalone test of rtl/dsp/fft_r2.sv against the Python reference (vectors/dsp_fft<k>_*.hex from
// sadiy_ebaz.dspref.fft_ref), bit for bit: frame sizes 64, 1024, 4096 and 16, with and without the Hann
// window, input with gaps in s_valid, two frames in a row, bin order, m_last, s_ready and busy.
`timescale 1ns / 1ps
module tb_dsp_fft;
  logic clk = 0, resetn = 0;
  always #5 clk = ~clk;

  logic [3:0] logn = 4'd6;
  logic hann = 0, s_valid = 0, s_ready, m_valid, m_last, busy;
  logic signed [23:0] s_re = '0, s_im = '0, m_re, m_im;
  logic [11:0] m_index;

  fft_r2 dut (.*);

  task automatic fail(input string why);
    $display("TB FAIL: %s (time %0t)", why, $time);
    $finish;
  endtask

  logic [47:0] vin [0:4095], vout [0:4095];
  logic [31:0] meta [0:1];
  int n, n_out, frame_k;
  bit gaps;

  // every bin is checked as it leaves
  always @(posedge clk) if (resetn && m_valid) begin
    if (m_index !== 12'(n_out)) fail($sformatf("frame %0d: bin index %0d, expected %0d", frame_k, m_index, n_out));
    if ({m_re, m_im} !== vout[n_out])
      fail($sformatf("frame %0d bin %0d: %06x %06x, reference %012x", frame_k, n_out, m_re, m_im, vout[n_out]));
    if (m_last !== (n_out == n - 1)) fail($sformatf("frame %0d: m_last wrong at bin %0d", frame_k, n_out));
    n_out++;
  end

  task automatic frame(input int k, input bit with_gaps);
    frame_k = k; gaps = with_gaps;
    $readmemh($sformatf("vectors/dsp_fft%0d_in.hex", k), vin);
    $readmemh($sformatf("vectors/dsp_fft%0d_out.hex", k), vout);
    $readmemh($sformatf("vectors/dsp_fft%0d_meta.hex", k), meta);
    n = 1 << meta[0]; n_out = 0;
    for (int i = 0; i < n; i++) begin
      if (gaps && (i % 7 == 3)) begin s_valid <= 0; repeat (2) @(posedge clk); end
      logn <= meta[0][3:0]; hann <= meta[1][0];
      s_valid <= 1; {s_re, s_im} <= vin[i];
      do @(posedge clk); while (!s_ready);
      if (i == 0) begin logn <= 4'd2; hann <= ~meta[1][0]; end     // only the first sample's setting counts
    end
    s_valid <= 0;
    @(posedge clk);
    if (s_ready !== 0 || busy !== 1) fail("s_ready / busy while the frame is computed");
    while (n_out < n) @(posedge clk);
    repeat (2) @(posedge clk);
    if (s_ready !== 1 || busy !== 0) fail("not ready after the frame");
    if (n_out != n) fail("too many bins");
  endtask

  initial begin
    repeat (4) @(posedge clk); resetn <= 1; repeat (2) @(posedge clk);
    frame(0, 0);
    frame(0, 1);            // the same again, with gaps: the memory content of the last frame must not matter
    frame(1, 0);
    frame(3, 1);
    frame(2, 0);
    frame(3, 0);
    $display("TB PASS");
    $finish;
  end
  initial begin #50ms; fail("global timeout"); end
endmodule
