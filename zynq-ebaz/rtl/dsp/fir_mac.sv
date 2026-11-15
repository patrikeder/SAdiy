// Complex FIR filter with decimation, one multiply-accumulate per tap and clock (RBW shaping after the CIC).
// Interface and arithmetic: docs/dsp-modules.md; bit-exact reference: sadiy_ebaz.dspref.fir_ref.
//
//   y[m] = sat18((sum_{t < ntaps} coef[t] * x[n - t]) >> shift)   at n = decim - 1, 2 decim - 1, ...
//
// Samples before the first one after `clr` (or reset) count as 0. Coefficients are written by the user
// (coef_we / coef_addr / coef_data) while no output is being computed. One output takes ntaps + 4 clocks,
// during which s_ready is low: the input rate must leave that time (it follows a decimating CIC).
`default_nettype none
module fir_mac #(
  parameter int AW = 6,                 // up to 2^AW taps
  parameter int DW = 18,
  parameter int CW = 18
) (
  input  wire logic                 clk,
  input  wire logic                 resetn,
  input  wire logic                 clr,          // forget the history
  input  wire logic [AW:0]          ntaps,        // 1 .. 2^AW
  input  wire logic [7:0]           decim,        // 1 .. 255 (0 = 1)
  input  wire logic [4:0]           shift,
  input  wire logic                 coef_we,
  input  wire logic [AW-1:0]        coef_addr,
  input  wire logic signed [CW-1:0] coef_data,
  input  wire logic                 s_valid,
  output      logic                 s_ready,
  input  wire logic signed [DW-1:0] s_re,
  input  wire logic signed [DW-1:0] s_im,
  output      logic                 m_valid,
  output      logic signed [DW-1:0] m_re,
  output      logic signed [DW-1:0] m_im,
  output      logic                 m_sat         // with m_valid: an output was clipped
);
  localparam int ACCW = DW + CW + AW;

  logic signed [CW-1:0] coef [0:(1<<AW)-1];
  logic [2*DW-1:0]      hist [0:(1<<AW)-1];
  logic signed [CW-1:0] c_q;
  logic [2*DW-1:0]      x_q;
  logic signed [DW-1:0] x_re, x_im;
  assign {x_re, x_im} = x_q;

  logic [AW-1:0] wptr, t, last;
  logic [AW:0]   have, n_use;                     // samples in the history (saturates at ntaps)
  logic [7:0]    dcnt, d_eff;
  logic          run, rd_v, mul_v, acc_v, fin;
  logic signed [DW+CW-1:0] p_re, p_im;
  logic signed [ACCW-1:0]  acc_re, acc_im, sh_re, sh_im;

  assign d_eff   = (decim == 8'd0) ? 8'd1 : decim;
  assign s_ready = !run;
  assign sh_re   = acc_re >>> shift;
  assign sh_im   = acc_im >>> shift;

  function automatic logic fits(input logic signed [ACCW-1:0] v);
    return (v[ACCW-1:DW-1] == '0) || (v[ACCW-1:DW-1] == '1);
  endfunction
  function automatic logic signed [DW-1:0] clip(input logic signed [ACCW-1:0] v);
    return fits(v) ? v[DW-1:0] : (v[ACCW-1] ? {1'b1, {(DW-1){1'b0}}} : {1'b0, {(DW-1){1'b1}}});
  endfunction

  always_ff @(posedge clk) begin
    if (coef_we) coef[coef_addr] <= coef_data;
    if (s_valid && s_ready) hist[wptr] <= {s_re, s_im};
    c_q <= coef[t];
    x_q <= hist[last - t];
  end

  always_ff @(posedge clk) begin
    m_valid <= 1'b0;
    if (!resetn || clr) begin
      wptr <= '0; have <= '0; dcnt <= '0; run <= 1'b0; t <= '0;
      rd_v <= 1'b0; mul_v <= 1'b0; acc_v <= 1'b0; fin <= 1'b0;
    end else if (!run) begin
      rd_v <= 1'b0; mul_v <= 1'b0; acc_v <= 1'b0; fin <= 1'b0;
      if (s_valid) begin
        last <= wptr;
        wptr <= wptr + 1'b1;
        if (have < ntaps) have <= have + 1'b1;
        if (dcnt == d_eff - 8'd1) begin
          dcnt   <= '0;
          run    <= 1'b1;
          t      <= '0;
          n_use  <= (have < ntaps) ? have + 1'b1 : ntaps;
          acc_re <= '0; acc_im <= '0;
        end else dcnt <= dcnt + 8'd1;
      end
    end else begin
      // t: address out -> rd_v: operands there -> mul_v: products there -> accumulate
      rd_v  <= !fin;
      if (!fin) begin
        if ({1'b0, t} == n_use - 1'b1) fin <= 1'b1;
        else t <= t + 1'b1;
      end
      mul_v <= rd_v;
      p_re  <= x_re * c_q;
      p_im  <= x_im * c_q;
      acc_v <= mul_v;
      if (mul_v) begin
        acc_re <= acc_re + ACCW'(p_re);
        acc_im <= acc_im + ACCW'(p_im);
      end
      if (fin && !rd_v && !mul_v && acc_v) begin      // the last product is in
        m_valid <= 1'b1;
        m_re    <= clip(sh_re);
        m_im    <= clip(sh_im);
        m_sat   <= !fits(sh_re) || !fits(sh_im);
        run     <= 1'b0;
      end
    end
  end
endmodule
`default_nettype wire
