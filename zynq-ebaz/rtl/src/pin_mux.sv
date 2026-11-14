// Pin owner: PS (EMIO) or engine. docs/rtl-spec.md section 9. The only place that drives the pins.
// The I2C pins have their own select (`i2c_pl`): PS I2C0 or the ADS1115 reader. While the reader owns them
// the PS controller sees an idle bus (both lines high).
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
  input  wire logic       emio_ce_o,
  input  wire logic       emio_ce_t,
  input  wire logic       emio_scl_o,
  input  wire logic       emio_scl_t,
  input  wire logic       emio_sda_o,
  input  wire logic       emio_sda_t,
  output      logic       emio_scl_i,
  output      logic       emio_sda_i,
  // engine side
  input  wire logic       eng_adf_clk,
  input  wire logic       eng_adf_dat,
  input  wire logic       eng_adf_le,
  input  wire logic [5:0] eng_pe,
  input  wire logic       eng_ce,
  input  wire logic       i2c_pl,         // 1 = the ADS1115 reader owns the I2C pins
  input  wire logic       eng_scl_t,
  input  wire logic       eng_sda_t,
  // pins
  output      logic       adf4351_clk,
  output      logic       adf4351_dat,
  output      logic       adf4351_le,
  output      logic [5:0] pe4302_v_o,
  output      logic [5:0] pe4302_v_t,
  output      logic       adf4351_ce_o,
  output      logic       adf4351_ce_t,
  output      logic       i2c_scl_o,
  output      logic       i2c_scl_t,
  output      logic       i2c_sda_o,
  output      logic       i2c_sda_t,
  input  wire logic       i2c_scl_i,
  input  wire logic       i2c_sda_i
);
  assign emio_scl_i = i2c_pl ? 1'b1 : i2c_scl_i;
  assign emio_sda_i = i2c_pl ? 1'b1 : i2c_sda_i;

  always_ff @(posedge clk) begin
    if (!resetn) begin
      i2c_scl_o <= 1'b0; i2c_scl_t <= 1'b1;
      i2c_sda_o <= 1'b0; i2c_sda_t <= 1'b1;
    end else if (i2c_pl) begin
      i2c_scl_o <= 1'b0; i2c_scl_t <= eng_scl_t;
      i2c_sda_o <= 1'b0; i2c_sda_t <= eng_sda_t;
    end else begin
      i2c_scl_o <= emio_scl_o; i2c_scl_t <= emio_scl_t;
      i2c_sda_o <= emio_sda_o; i2c_sda_t <= emio_sda_t;
    end
  end

  always_ff @(posedge clk) begin
    if (!resetn) begin
      adf4351_clk <= 1'b0;
      adf4351_dat <= 1'b0;
      adf4351_le  <= 1'b1;
      pe4302_v_o  <= 6'h3F;
      pe4302_v_t  <= 6'h3F;      // not driven: the adapter's pull-ups give 31.5 dB
      adf4351_ce_o <= 1'b1;
      adf4351_ce_t <= 1'b1;      // not driven: the CE jumper / pull decides
    end else if (owner) begin
      adf4351_clk <= eng_adf_clk;
      adf4351_dat <= eng_adf_dat;
      adf4351_le  <= eng_adf_le;
      pe4302_v_o  <= eng_pe;
      pe4302_v_t  <= 6'h00;
      adf4351_ce_o <= eng_ce;
      adf4351_ce_t <= 1'b0;
    end else begin
      adf4351_clk <= emio_adf_clk;
      adf4351_dat <= emio_adf_dat;
      adf4351_le  <= emio_adf_le;
      pe4302_v_o  <= emio_pe_o;
      pe4302_v_t  <= emio_pe_t;
      adf4351_ce_o <= emio_ce_o;
      adf4351_ce_t <= emio_ce_t;
    end
  end
endmodule
`default_nettype wire
