// Power of a complex sample as mantissa and exponent: re^2 + im^2 = mant << exp (truncated),
// word = {exp[5:0], mant[21:0]}, the format of the result memory (docs/rtl-spec.md section 8c).
// Reference: sadiy_ebaz.dspref.power_ref. Pipelined, one sample per clock, latency 4 clocks;
// `s_user` travels with the sample (bin index, last flag, ...).
`default_nettype none
module iq_power #(
  parameter int DW = 24,
  parameter int UW = 13
) (
  input  wire logic                 clk,
  input  wire logic                 resetn,
  input  wire logic                 s_valid,
  input  wire logic signed [DW-1:0] s_re,
  input  wire logic signed [DW-1:0] s_im,
  input  wire logic [UW-1:0]        s_user,
  output      logic                 m_valid,
  output      logic [27:0]          m_pwr,
  output      logic [UW-1:0]        m_user
);
  localparam int PW = 2 * DW;
  logic [PW-1:0] sq_r, sq_i, sum, sum_q;
  logic [5:0]    exp;
  logic          v1, v2, v3;
  logic [UW-1:0] u1, u2, u3;

  function automatic logic [5:0] exp_of(input logic [PW-1:0] v);
    exp_of = 6'd0;
    for (int i = 22; i < PW; i++) if (v[i]) exp_of = 6'(i - 21);
  endfunction

  always_ff @(posedge clk) begin
    if (!resetn) begin
      v1 <= 1'b0; v2 <= 1'b0; v3 <= 1'b0; m_valid <= 1'b0;
    end else begin
      v1 <= s_valid; v2 <= v1; v3 <= v2; m_valid <= v3;
    end
    sq_r   <= PW'(s_re * s_re);
    sq_i   <= PW'(s_im * s_im);
    u1     <= s_user;
    sum    <= sq_r + sq_i;
    u2     <= u1;
    exp    <= exp_of(sum);
    sum_q  <= sum;
    u3     <= u2;
    m_pwr  <= {exp, 22'(sum_q >> exp)};
    m_user <= u3;
  end
endmodule
`default_nettype wire
