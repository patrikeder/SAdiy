// ADF4351 SPI writer: one 32-bit word, MSB first, mode 0, LE low during the word.
// Timing: docs/rtl-spec.md section 7. H = max(div, 2) clocks per half bit, a word takes 67 H.
// Transports the word unchanged; it never creates one. A word in progress always finishes
// (there is no way to cut it short, because a rising LE on a partial word would load garbage).
`default_nettype none
module adf4351_spi (
  input  wire logic        clk,
  input  wire logic        resetn,
  input  wire logic [7:0]  div,      // half bit period in clocks, sampled at start
  input  wire logic        start,    // one clock; ignored while busy
  input  wire logic [31:0] word,
  output      logic        busy,
  output      logic        sclk,
  output      logic        sdat,
  output      logic        le
);
  logic [7:0]  h, cnt;
  logic [6:0]  step;      // 0..66, one step = H clocks
  logic [30:0] sh;       // bits still to send after the one on sdat

  always_ff @(posedge clk) begin
    if (!resetn) begin
      busy <= 1'b0;
      sclk <= 1'b0;
      sdat <= 1'b0;
      le   <= 1'b1;
      h    <= 8'd2;
      cnt  <= '0;
      step <= '0;
      sh   <= '0;
    end else if (!busy) begin
      if (start) begin
        busy <= 1'b1;
        le   <= 1'b0;
        sdat <= word[31];
        sh   <= word[30:0];
        h    <= (div < 8'd2) ? 8'd2 : div;
        cnt  <= 8'd1;
        step <= '0;
      end
    end else if (cnt != h) begin
      cnt <= cnt + 8'd1;
    end else begin
      // end of step `step`
      cnt  <= 8'd1;
      step <= step + 7'd1;
      if (step < 7'd64) begin
        if (!step[0]) begin
          sclk <= 1'b1;                    // rising edge: the ADF4351 samples
        end else begin
          sclk <= 1'b0;                    // falling edge: next bit
          sh   <= {sh[29:0], 1'b0};
          sdat <= (step == 7'd63) ? 1'b0 : sh[30];
        end
      end else if (step == 7'd64) begin
        le <= 1'b1;                        // load
      end else if (step == 7'd66) begin
        busy <= 1'b0;
      end
    end
  end
endmodule
`default_nettype wire
