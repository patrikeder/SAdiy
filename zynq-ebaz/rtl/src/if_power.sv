// IF power detector (fast path): sample stream -> NCO and complex mixer -> 3-stage CIC decimator by R ->
// shift and saturation to 18 bit -> I^2 + Q^2 -> sum over n_avg outputs -> {exp[5:0], mant[21:0]}.
// docs/rtl-spec.md section 8c; sw/sadiy_ebaz/ifpath.py (if_power_ref) is the same arithmetic in Python and
// the testbench compares them bit for bit.
//
// A measurement runs while `run` is high. Its first clock gives `clr`: NCO phase 0, filter cleared, and the
// NCO increment of this point: `nco_base` for the first point of a sweep (`first`), the previous increment plus
// `nco_step` otherwise (a digital sweep inside the IF window; step 0 = fixed IF). The first `skip` filter
// outputs are dropped (settling: at least 3), the next n_avg are summed, then `done` with `sum` and `ovr`
// (stream over-range or saturation after the shift) until `run` goes low.
// Fully pipelined: one sample per clock is accepted, R may be 1.
`default_nettype none
module if_power (
  input  wire logic               clk,
  input  wire logic               resetn,
  input  wire logic               run,
  input  wire logic               first,
  input  wire logic               s_valid,
  input  wire logic signed [15:0] s_data,
  input  wire logic               s_ovr,
  input  wire logic [31:0]        nco_base,
  input  wire logic [31:0]        nco_step,
  input  wire logic [15:0]        r,
  input  wire logic [5:0]         shift,
  input  wire logic [3:0]         skip,
  input  wire logic [11:0]        n_avg,
  output      logic               clr,
  output      logic [27:0]        sum,
  output      logic               ovr,
  output      logic               done
);
  logic        run_d, active, stop;
  logic [31:0] inc, ph;
  logic [15:0] r_eff, cnt;
  logic [12:0] n_out, out_i, dec_n;
  logic [11:0] n_eff;

  assign clr    = run && !run_d;
  assign active = run && run_d;
  assign r_eff  = (r == 16'd0) ? 16'd1 : r;
  assign n_eff  = (n_avg == 12'd0) ? 12'd1 : n_avg;
  assign n_out  = {1'b0, n_eff} + {9'd0, skip};           // filter outputs this measurement needs

  // ---- NCO and mixer ----
  logic               a_v, b_v, acc_in;
  logic signed [15:0] x0, sin, cos;
  logic signed [31:0] pi, pq;
  assign acc_in = active && s_valid && !stop;

  nco_rom u_rom (.clk, .addr_s(ph[31:21]), .addr_c(ph[31:21] + 11'd512), .sin, .cos);

  // ---- CIC ----
  logic signed [63:0] i1, i2, i3, q1, q2, q3;
  logic signed [63:0] di1, di2, di3, dq1, dq2, dq3, ci1, ci2, ci3, cq1, cq2, cq3, shi, shq;
  logic               dec, v1, v2, v3, v4, v5, v6, v7;
  logic signed [17:0] yi, yq;
  logic               sat_i, sat_q, sat;
  logic [35:0]        sqi, sqq;
  logic [36:0]        p;
  logic [49:0]        acc;
  logic [5:0]         exp;
  logic               norm;

  function automatic logic fits18(input logic signed [63:0] v);
    return (v[63:17] == '0) || (v[63:17] == '1);
  endfunction

  always_ff @(posedge clk) begin
    if (!resetn) begin
      run_d <= 1'b0; inc <= '0;
    end else begin
      run_d <= run;
      if (clr) inc <= first ? nco_base : inc + nco_step;
    end
  end

  always_ff @(posedge clk) begin
    if (!resetn || !active) begin
      ph <= '0; cnt <= '0; dec_n <= '0; out_i <= '0; stop <= 1'b0;
      a_v <= 1'b0; b_v <= 1'b0; dec <= 1'b0;
      v1 <= 1'b0; v2 <= 1'b0; v3 <= 1'b0; v4 <= 1'b0; v5 <= 1'b0; v6 <= 1'b0; v7 <= 1'b0;
      i1 <= '0; i2 <= '0; i3 <= '0; q1 <= '0; q2 <= '0; q3 <= '0;
      di1 <= '0; di2 <= '0; di3 <= '0; dq1 <= '0; dq2 <= '0; dq3 <= '0;
      acc <= '0; exp <= '0; norm <= 1'b0; done <= 1'b0; sat <= 1'b0; ovr <= 1'b0;
    end else begin
      // sample in, table address from the phase of this sample
      a_v <= acc_in;
      if (acc_in) begin
        x0 <= s_data;
        ph <= ph + inc;
        if (s_ovr) sat <= 1'b1;
      end
      // products (the table answers one clock after the address)
      b_v <= a_v;
      pi  <= x0 * cos;
      pq  <= x0 * sin;
      // integrators: every stage adds the previous stage's old value
      dec <= 1'b0;
      if (b_v) begin
        i1 <= i1 + 64'(pi >>> 15);  i2 <= i2 + i1;  i3 <= i3 + i2;
        q1 <= q1 + 64'(pq >>> 15);  q2 <= q2 + q1;  q3 <= q3 + q2;
        if (cnt == r_eff - 16'd1) begin
          cnt <= '0;
          if (!stop) begin
            dec   <= 1'b1;
            dec_n <= dec_n + 13'd1;
            if (dec_n + 13'd1 == n_out) stop <= 1'b1;      // enough outputs: no more samples
          end
        end else cnt <= cnt + 16'd1;
      end
      // combs, one per stage
      v1 <= dec;
      if (dec) begin ci1 <= i3 - di1; di1 <= i3; cq1 <= q3 - dq1; dq1 <= q3; end
      v2 <= v1;
      if (v1)  begin ci2 <= ci1 - di2; di2 <= ci1; cq2 <= cq1 - dq2; dq2 <= cq1; end
      v3 <= v2;
      if (v2)  begin ci3 <= ci2 - di3; di3 <= ci2; cq3 <= cq2 - dq3; dq3 <= cq2; end
      // shift, saturate to 18 bit
      v4 <= v3;
      shi <= ci3 >>> shift;
      shq <= cq3 >>> shift;
      v5 <= v4;
      yi    <= fits18(shi) ? shi[17:0] : (shi[63] ? 18'sh20000 : 18'sh1FFFF);
      yq    <= fits18(shq) ? shq[17:0] : (shq[63] ? 18'sh20000 : 18'sh1FFFF);
      sat_i <= !fits18(shi);
      sat_q <= !fits18(shq);
      // power
      v6 <= v5;
      sqi <= 36'(yi * yi);
      sqq <= 36'(yq * yq);
      if (v5 && (sat_i || sat_q)) sat <= 1'b1;
      v7 <= v6;
      p  <= {1'b0, sqi} + {1'b0, sqq};
      // sum, after the settling outputs
      if (v7) begin
        out_i <= out_i + 13'd1;
        if (out_i >= {9'd0, skip}) acc <= acc + {13'd0, p};
        if (out_i + 13'd1 == n_out) norm <= 1'b1;
      end
      // mantissa and exponent
      if (norm && !done) begin
        if (acc[49:22] != '0) begin acc <= acc >> 1; exp <= exp + 6'd1; end
        else begin done <= 1'b1; ovr <= sat; end
      end
    end
  end
  assign sum = {exp, acc[21:0]};
endmodule
`default_nettype wire
