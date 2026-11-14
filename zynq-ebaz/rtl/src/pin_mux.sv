// Pin owner: PS (EMIO) or engine. docs/rtl-spec.md section 9. The only place that drives the pins.
// `owner` must change only while both sides idle (LE high, CLK low); sweep_seq guarantees the
// engine side. Outputs are registered.
`default_nettype none
module pin_mux (
  input  wire logic       clk,
  input  wire logic       resetn,
  input  wire logic       owner,          // 0 = PS, 1 = engine
  // PS side
  input  wire logic       emio_adf_clk,
  input  wire logic       emio_adf_dat,
  input  wire logic       emio_adf_le,
  input  wire logic [5:0] emio_pe_o,
  input  wire logic [5:0] emio_pe_t,
  // engine side
  input  wire logic       eng_adf_clk,
  input  wire logic       eng_adf_dat,
  input  wire logic       eng_adf_le,
  input  wire logic [5:0] eng_pe,
  // pins
  output      logic       adf4351_clk,
  output      logic       adf4351_dat,
  output      logic       adf4351_le,
  output      logic [5:0] pe4302_v_o,
  output      logic [5:0] pe4302_v_t
);
  always_ff @(posedge clk) begin
    if (!resetn) begin
      adf4351_clk <= 1'b0;
      adf4351_dat <= 1'b0;
      adf4351_le  <= 1'b1;
      pe4302_v_o  <= 6'h3F;
      pe4302_v_t  <= 6'h3F;      // not driven: the adapter's pull-ups give 31.5 dB
    end else if (owner) begin
      adf4351_clk <= eng_adf_clk;
      adf4351_dat <= eng_adf_dat;
      adf4351_le  <= eng_adf_le;
      pe4302_v_o  <= eng_pe;
      pe4302_v_t  <= 6'h00;
    end else begin
      adf4351_clk <= emio_adf_clk;
      adf4351_dat <= emio_adf_dat;
      adf4351_le  <= emio_adf_le;
      pe4302_v_o  <= emio_pe_o;
      pe4302_v_t  <= emio_pe_t;
    end
  end
endmodule
`default_nettype wire
