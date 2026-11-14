// Detector sample source select and accumulator. docs/rtl-spec.md section 8.
// While `run` is high it sums n_avg samples (0 counts as 1) of the selected source, then raises
// `done` and holds `sum` until `run` goes low. Samples outside `run` are dropped.
`default_nettype none
module det_sampler #(
  parameter int CLK_PER_US = 100
) (
  input  wire logic        clk,
  input  wire logic        resetn,
  input  wire logic        run,
  input  wire logic [1:0]  src,           // 0 PS push, 1 test generator, 2 external stream, 3 none
  input  wire logic [11:0] n_avg,
  input  wire logic [15:0] test_base,
  input  wire logic [7:0]  result_index,  // low 8 bits of the result index (test generator)
  input  wire logic        push_valid,
  input  wire logic [15:0] push_data,
  input  wire logic        ext_valid,
  input  wire logic [15:0] ext_data,
  output      logic [27:0] sum,
  output      logic        done
);
  localparam int USW = $clog2(CLK_PER_US);
  logic [USW:0]  us_div;
  logic          us_tick;
  logic [11:0]   n_eff, cnt;
  logic          s_valid;
  logic [15:0]   s_data;

  assign n_eff   = (n_avg == 12'd0) ? 12'd1 : n_avg;
  assign us_tick = (us_div == (USW+1)'(CLK_PER_US - 1));

  always_comb begin
    unique case (src)
      2'd0:    begin s_valid = push_valid; s_data = push_data; end
      2'd1:    begin s_valid = us_tick;    s_data = test_base + {8'd0, result_index}; end
      2'd2:    begin s_valid = ext_valid;  s_data = ext_data; end
      default: begin s_valid = 1'b0;       s_data = '0; end
    endcase
  end

  always_ff @(posedge clk) begin
    if (!resetn || !run) begin
      us_div <= '0;
      cnt    <= '0;
      sum    <= '0;
      done   <= 1'b0;
    end else begin
      us_div <= us_tick ? '0 : us_div + 1'b1;
      if (s_valid && !done) begin
        sum <= sum + {12'd0, s_data};
        cnt <= cnt + 12'd1;
        if (cnt + 12'd1 == n_eff) done <= 1'b1;
      end
    end
  end
endmodule
`default_nettype wire
