// 16-bit SPI SAR ADC with a CNV pin (AD7685 / ADS8860 class, 3-wire mode) -> sample stream
// (docs/rtl-spec.md section 8b). docs/dsp-modules.md. VERIFY the timing against the part that is fitted.
//   every `period` clocks: CNV high for `t_conv` clocks (conversion), CNV low, half an SCK period, then 16 SCK
//   pulses (high and low `sck_div` clocks each). SDO is taken in the last clock of every SCK high phase (the
//   ADC changes it after the falling edge), MSB first. data = code >> 1 (0 .. 32767), ovr = 0.
// sck_div >= 3 (SDO passes two synchroniser registers). If `period` is shorter than one cycle takes, the
// cycles follow each other without a gap.
`default_nettype none
module adc_spi_sar (
  input  wire logic               clk,
  input  wire logic               resetn,
  input  wire logic               enable,
  input  wire logic [15:0]        period,
  input  wire logic [15:0]        t_conv,
  input  wire logic [7:0]         sck_div,
  output      logic               cnv,
  output      logic               sck,
  input  wire logic               sdo,
  output      logic               valid,
  output      logic signed [15:0] data,
  output      logic               ovr
);
  typedef enum logic [1:0] {S_IDLE, S_CONV, S_GAP, S_READ} state_t;
  state_t      state;
  logic [15:0] pcnt, tcnt, sh;
  logic [7:0]  dcnt, d_eff;
  logic [4:0]  bits;
  logic [1:0]  sdo_s;
  logic        due;
  assign d_eff = (sck_div < 8'd3) ? 8'd3 : sck_div;
  assign ovr   = 1'b0;

  always_ff @(posedge clk) begin
    sdo_s <= {sdo_s[0], sdo};
    valid <= 1'b0;
    if (!resetn || !enable) begin
      state <= S_IDLE; cnv <= 1'b0; sck <= 1'b0; pcnt <= '0; due <= 1'b1;
    end else begin
      if (pcnt + 16'd1 >= period) begin pcnt <= '0; due <= 1'b1; end
      else pcnt <= pcnt + 16'd1;
      unique case (state)
        S_IDLE: if (due) begin
          due <= (pcnt + 16'd1 >= period);
          cnv <= 1'b1; tcnt <= '0; state <= S_CONV;
        end
        S_CONV: if (tcnt + 16'd1 >= t_conv) begin cnv <= 1'b0; dcnt <= '0; state <= S_GAP; end
                else tcnt <= tcnt + 16'd1;
        S_GAP: if (dcnt == d_eff - 8'd1) begin dcnt <= '0; bits <= '0; sck <= 1'b1; state <= S_READ; end
               else dcnt <= dcnt + 8'd1;
        default: begin                             // S_READ
          if (dcnt == d_eff - 8'd1) begin
            dcnt <= '0;
            if (sck) begin                         // end of a high phase: take the bit
              sck  <= 1'b0;
              sh   <= {sh[14:0], sdo_s[1]};
              bits <= bits + 5'd1;
            end else if (bits == 5'd16) begin      // end of the last low phase
              valid <= 1'b1;
              data  <= {1'b0, sh[15:1]};
              state <= S_IDLE;
            end else sck <= 1'b1;
          end else dcnt <= dcnt + 8'd1;
        end
      endcase
    end
  end
endmodule
`default_nettype wire
