// ADC front end for the AD9226 module: clock, capture, and a source for the data lines that needs no pins.
// docs/rtl-spec.md section 8d, docs/adc-module.md. The converter itself is dsp/adc_ad9226.sv (clock from clk,
// two input registers, conversion to the sample stream of section 8b); this wrapper decides what that capture
// sees on the data lines:
//   src 0  tie-off: constant code (tie_code) and OTR (tie_otr). No pins, no module: the stream is a constant.
//   src 1  traffic generator: one code per ADC clock, made here, delivered as if the module had produced it
//          (changes a few clocks after the rising edge of adc_clk, like an ADC output). tg_mode: ramp, walking
//          one, tone (NCO of the IF path, the same sine ROM), constant. Exercises the clock, the capture
//          phase, the conversion, the stream path, the IF path and the result memory at the real sample rate.
//   src 2  the adc_d / adc_otr pins (src 3 = 2).
// Status for the bring-up script: last raw code, sticky OTR, sample counter.
`default_nettype none
module adc_fe (
  input  wire logic               clk,
  input  wire logic               resetn,
  input  wire logic               enable,
  input  wire logic [1:0]         src,
  input  wire logic               twos,
  input  wire logic [1:0]         tg_mode,
  input  wire logic               clear,
  input  wire logic [7:0]         div,
  input  wire logic [7:0]         phase,
  input  wire logic [11:0]        tie_code,
  input  wire logic               tie_otr,
  input  wire logic [31:0]        tg_inc,
  // pins of the AD9226 module
  output      logic               adc_clk,
  input  wire logic [11:0]        adc_d,
  input  wire logic               adc_otr,
  // sample stream (section 8b)
  output      logic               valid,
  output      logic signed [15:0] data,
  output      logic               ovr,
  // status
  output      logic [11:0]        last_code,
  output      logic               last_otr,
  output      logic               otr_seen,
  output      logic [15:0]        count
);
  // ---- traffic generator: advances on the rising edge of adc_clk, shows the new code two clocks later ----
  logic               clk_q, rise, rise_d, upd;
  logic [11:0]        tg_ramp;
  logic [3:0]         tg_pos;
  logic [31:0]        tg_ph;
  logic signed [15:0] sin, cos_unused;
  logic [11:0]        tg_d, tg_code;
  logic               tg_otr_d, tg_otr;

  assign rise = adc_clk && !clk_q;

  nco_rom u_rom (.clk, .addr_s(tg_ph[31:21]), .addr_c(tg_ph[31:21] + 11'd512), .sin, .cos(cos_unused));

  always_comb begin
    unique case (tg_mode)
      2'd0:    begin tg_code = tg_ramp;                tg_otr = (tg_ramp == 12'hFFF); end
      2'd1:    begin tg_code = 12'd1 << tg_pos;        tg_otr = 1'b0; end
      2'd2:    begin tg_code = {!sin[15], sin[14:4]};  tg_otr = 1'b0; end      // offset binary of the sine
      default: begin tg_code = tie_code;               tg_otr = tie_otr; end
    endcase
  end

  always_ff @(posedge clk) begin
    clk_q  <= adc_clk;
    rise_d <= rise;
    upd    <= rise_d;                        // the ROM answers one clock after the phase moved
    if (!resetn || !enable) begin
      tg_ramp <= '0; tg_pos <= '0; tg_ph <= '0; tg_d <= '0; tg_otr_d <= 1'b0;
    end else begin
      if (rise) begin
        tg_ramp <= tg_ramp + 12'd1;
        tg_pos  <= (tg_pos == 4'd11) ? 4'd0 : tg_pos + 4'd1;
        tg_ph   <= tg_ph + tg_inc;
      end
      if (upd) begin
        tg_d     <= tg_code;
        tg_otr_d <= tg_otr;
      end
    end
  end

  // ---- data lines seen by the capture ----
  logic [11:0] d_sel;
  logic        otr_sel;
  always_comb begin
    unique case (src)
      2'd0:    begin d_sel = tie_code; otr_sel = tie_otr; end
      2'd1:    begin d_sel = tg_d;     otr_sel = tg_otr_d; end
      default: begin d_sel = adc_d;    otr_sel = adc_otr; end
    endcase
  end

  adc_ad9226 u_adc (
    .clk, .resetn, .enable, .div, .phase, .twos,
    .adc_clk, .adc_d(d_sel), .adc_otr(otr_sel),
    .valid, .data, .ovr
  );

  // ---- status ----
  always_ff @(posedge clk) begin
    if (!resetn || clear) begin
      count <= '0; otr_seen <= 1'b0;
    end else if (valid) begin
      count <= count + 16'd1;
      if (ovr) otr_seen <= 1'b1;
    end
    if (!resetn) begin
      last_code <= '0; last_otr <= 1'b0;
    end else if (valid) begin
      last_code <= twos ? data[15:4] : {!data[15], data[14:4]};
      last_otr  <= ovr;
    end
  end
endmodule
`default_nettype wire
