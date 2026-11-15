// AD9226 (12 bit parallel) -> sample stream (docs/rtl-spec.md section 8b). docs/dsp-modules.md.
// The module makes the ADC clock from clk: one period = `div` clocks (>= 2), high for the first half.
// The data pins are registered twice; the value registered in clock `phase` of the period (0 = the clock in
// which adc_clk rises) becomes the sample. Choose `phase` so that this is away from the ADC's output
// transition (t_OD after the rising clock edge, plus the board delay): for div = 4, phase 3 is the usual start.
//   data = (code - 2048) << 4 for offset binary, code << 4 sign-extended for two's complement; ovr = OTR.
// In the board top put adc_clk and the first data register into the I/O cells.
`default_nettype none
module adc_ad9226 (
  input  wire logic               clk,
  input  wire logic               resetn,
  input  wire logic               enable,
  input  wire logic [7:0]         div,
  input  wire logic [7:0]         phase,
  input  wire logic               twos,        // 1 = the ADC is strapped for two's complement
  output      logic               adc_clk,
  input  wire logic [11:0]        adc_d,
  input  wire logic               adc_otr,
  output      logic               valid,
  output      logic signed [15:0] data,
  output      logic               ovr
);
  logic [7:0]  cnt, d_eff;
  logic [12:0] p1, p2;
  assign d_eff = (div < 8'd2) ? 8'd2 : div;

  always_ff @(posedge clk) begin
    p1 <= {adc_otr, adc_d};
    p2 <= p1;
    valid <= 1'b0;
    if (!resetn || !enable) begin
      cnt <= '0; adc_clk <= 1'b0;
    end else begin
      cnt     <= (cnt == d_eff - 8'd1) ? 8'd0 : cnt + 8'd1;
      adc_clk <= (cnt == d_eff - 8'd1) || (cnt + 8'd1 < (d_eff >> 1));
      if (cnt == phase) begin
        valid <= 1'b1;
        data  <= {twos ? p2[11] : !p2[11], p2[10:0], 4'b0000};
        ovr   <= p2[12];
      end
    end
  end
endmodule
`default_nettype wire
