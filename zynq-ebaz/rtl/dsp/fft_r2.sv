// Radix-2 FFT, in place, one butterfly, frame size 2^logn chosen at run time (logn = 2 .. 12).
// Interface and arithmetic: docs/dsp-modules.md; bit-exact reference: sadiy_ebaz.dspref.fft_ref.
//
//   X[k] = (1 / N) * sum x[n] * exp(-j 2 pi k n / N)        every stage halves, so nothing overflows as
//                                                            long as |re|, |im| of the input <= 2^22
//   hann = 1: Hann window, applied to the result: (2 X[k] - X[k-1] - X[k+1]) >> 2
//
// A frame: N samples in (s_valid / s_ready), then (N / 2) * logn butterflies of 4 clocks, then N bins out
// (m_valid for N clocks in a row, no back pressure, m_last with the last one). `logn` and `hann` are taken
// with the first sample of a frame. s_ready is low while a frame is computed and sent.
`default_nettype none
module fft_r2 #(
  parameter int LOGN_MAX = 12,          // the twiddle table (fft_twiddle_rom) is made for 12
  parameter int DW       = 24
) (
  input  wire logic                 clk,
  input  wire logic                 resetn,
  input  wire logic [3:0]           logn,
  input  wire logic                 hann,
  input  wire logic                 s_valid,
  output      logic                 s_ready,
  input  wire logic signed [DW-1:0] s_re,
  input  wire logic signed [DW-1:0] s_im,
  output      logic                 m_valid,
  output      logic                 m_last,
  output      logic [LOGN_MAX-1:0]  m_index,
  output      logic signed [DW-1:0] m_re,
  output      logic signed [DW-1:0] m_im,
  output      logic                 busy
);
  localparam int TW = 18;
  typedef enum logic [2:0] {S_LOAD, S_B0, S_B1, S_B2, S_B3, S_OUT} state_t;
  state_t state;

  logic [3:0]          logn_q, stage;
  logic                hann_q;
  logic [LOGN_MAX:0]   n;                       // frame size
  logic [LOGN_MAX-1:0] cnt;                     // sample / butterfly counter
  logic [LOGN_MAX+2:0] oc;                      // clock counter of the output phase

  function automatic logic [LOGN_MAX-1:0] bitrev(input logic [LOGN_MAX-1:0] v);
    for (int i = 0; i < LOGN_MAX; i++) bitrev[i] = v[LOGN_MAX-1-i];
  endfunction

  // ---- memory ----
  logic                we_a, we_b;
  logic [LOGN_MAX-1:0] addr_a, addr_b;
  logic [2*DW-1:0]     din_a, din_b, dout_a, dout_b;
  tdp_ram #(.AW(LOGN_MAX), .DW(2*DW)) u_ram (.clk, .we_a, .addr_a, .din_a, .dout_a, .we_b, .addr_b, .din_b, .dout_b);

  logic signed [DW-1:0] ar, ai, br, bi;
  assign {ar, ai} = dout_a;
  assign {br, bi} = dout_b;

  // ---- butterfly addressing ----
  logic [LOGN_MAX-1:0] half_mask, j, bf_a, bf_b;
  logic [LOGN_MAX-2:0] tw_addr;
  logic [LOGN_MAX-1:0] tw_wide;
  logic signed [TW-1:0] wr, wi;
  always_comb begin
    half_mask = LOGN_MAX'((1 << (stage - 4'd1)) - 1);
    j         = cnt & half_mask;
    bf_a      = LOGN_MAX'(((cnt >> (stage - 4'd1)) << stage)) | j;
    bf_b      = bf_a | LOGN_MAX'(1 << (stage - 4'd1));
    tw_wide   = LOGN_MAX'(j << (4'(LOGN_MAX) - stage));
    tw_addr   = tw_wide[LOGN_MAX-2:0];
  end
  fft_twiddle_rom u_tw (.clk, .addr(tw_addr), .wr, .wi);

  // ---- butterfly datapath ----
  logic signed [DW+TW-1:0] p_rr, p_ii, p_ri, p_ir;
  logic signed [DW+TW:0]   sum_r, sum_i;
  logic signed [DW-1:0]    tr, ti;
  logic signed [DW:0]      a_p_r, a_m_r, a_p_i, a_m_i;
  assign sum_r = p_rr - p_ii;
  assign sum_i = p_ri + p_ir;
  assign a_p_r = ar + tr;  assign a_m_r = ar - tr;
  assign a_p_i = ai + ti;  assign a_m_i = ai - ti;

  // ---- output phase: three bins in a row for the window ----
  logic signed [DW-1:0] prv_r, prv_i, cur_r, cur_i, nxt_r, nxt_i;
  logic signed [DW+1:0] h_r, h_i;
  logic [LOGN_MAX-1:0]  oaddr;                  // N-1, 0, 1, ..., N-1, 0: a counter, set when the phase starts
  assign h_r   = (DW+2)'(cur_r) + (DW+2)'(cur_r) - (DW+2)'(prv_r) - (DW+2)'(nxt_r);
  assign h_i   = (DW+2)'(cur_i) + (DW+2)'(cur_i) - (DW+2)'(prv_i) - (DW+2)'(nxt_i);

  always_comb begin
    we_a = 1'b0; we_b = 1'b0;
    addr_a = bf_a; addr_b = bf_b;
    din_a = {a_p_r[DW:1], a_p_i[DW:1]};
    din_b = {a_m_r[DW:1], a_m_i[DW:1]};
    unique case (state)
      S_LOAD: begin
        addr_a = bitrev(cnt) >> (4'(LOGN_MAX) - ((cnt == '0) ? logn : logn_q));
        din_a  = {s_re, s_im};
        we_a   = s_valid;
      end
      S_B3: begin we_a = 1'b1; we_b = 1'b1; end
      S_OUT: addr_a = oaddr;
      default: ;
    endcase
  end

  assign s_ready = (state == S_LOAD);
  assign busy    = (state != S_LOAD) || (cnt != '0);

  always_ff @(posedge clk) begin
    m_valid <= 1'b0;
    m_last  <= 1'b0;
    if (!resetn) begin
      state <= S_LOAD; cnt <= '0; stage <= 4'd1; oc <= '0; logn_q <= 4'd2; hann_q <= 1'b0; n <= '0;
    end else begin
      unique case (state)
        S_LOAD: if (s_valid) begin
          if (cnt == '0) begin
            logn_q <= logn; hann_q <= hann; n <= (LOGN_MAX+1)'(1) << logn;
            cnt <= cnt + 1'b1;
          end else if ({1'b0, cnt} == n - 1'b1) begin
            cnt <= '0; stage <= 4'd1; state <= S_B0;
          end else cnt <= cnt + 1'b1;
        end
        S_B0: state <= S_B1;                      // addresses out
        S_B1: begin                               // operands and twiddle are there: multiply
          p_rr <= br * wr; p_ii <= bi * wi; p_ri <= br * wi; p_ir <= bi * wr;
          state <= S_B2;
        end
        S_B2: begin
          tr <= DW'(sum_r >>> (TW - 1));
          ti <= DW'(sum_i >>> (TW - 1));
          state <= S_B3;
        end
        S_B3: begin                               // both results written
          if ({1'b0, cnt} == (n >> 1) - 1'b1) begin
            cnt <= '0;
            if (stage == logn_q) begin oc <= '0; oaddr <= LOGN_MAX'(n - 1'b1); state <= S_OUT; end
            else begin stage <= stage + 4'd1; state <= S_B0; end
          end else begin cnt <= cnt + 1'b1; state <= S_B0; end
        end
        S_OUT: begin
          oc <= oc + 1'b1;
          oaddr <= ({1'b0, oaddr} == n - 1'b1) ? '0 : oaddr + 1'b1;
          {nxt_r, nxt_i} <= dout_a;
          cur_r <= nxt_r; cur_i <= nxt_i;
          prv_r <= cur_r; prv_i <= cur_i;
          if (oc >= (LOGN_MAX+3)'(4)) begin
            m_valid <= 1'b1;
            m_index <= LOGN_MAX'(oc - (LOGN_MAX+3)'(4));
            m_re    <= hann_q ? DW'(h_r >>> 2) : cur_r;
            m_im    <= hann_q ? DW'(h_i >>> 2) : cur_i;
            if (oc == (LOGN_MAX+3)'(n) + (LOGN_MAX+3)'(3)) begin m_last <= 1'b1; state <= S_LOAD; end
          end
        end
        default: state <= S_LOAD;
      endcase
    end
  end
endmodule
`default_nettype wire
