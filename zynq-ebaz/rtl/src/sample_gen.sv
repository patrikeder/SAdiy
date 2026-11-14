// Sample generator that stands in for an ADC: a pattern of up to 4096 samples, written by the PS, played
// cyclically in the sample stream format (docs/rtl-spec.md section 8b) at one sample every `div` clocks.
// With `sync_clr` (one clock) the playback restarts at sample 0: the first `valid` after it carries sample 0,
// two clocks later. No waveform logic in the PL: software computes the pattern.
`default_nettype none
module sample_gen #(
  parameter int AW = 12
) (
  input  wire logic                 clk,
  input  wire logic                 resetn,
  input  wire logic                 enable,
  input  wire logic                 sync_clr,
  input  wire logic [15:0]          div,       // clocks per sample; 0 and 1 = every clock
  input  wire logic [AW-1:0]        len_m1,    // last sample index of the pattern
  input  wire logic                 we,        // pattern write port
  input  wire logic [AW-1:0]        waddr,
  input  wire logic [15:0]          wdata,
  output      logic                 valid,
  output      logic signed [15:0]   data
);
  logic [AW-1:0] addr;
  logic [15:0]   cnt, q;
  logic          tick;
  assign tick = (cnt == 16'd0);
  assign data = $signed(q);

  sdp_ram #(.AW(AW), .DW(16)) u_ram (.clk, .we, .waddr, .wdata, .raddr(addr), .rdata(q));

  always_ff @(posedge clk) begin
    if (!resetn || !enable || sync_clr) begin
      addr <= '0; cnt <= '0; valid <= 1'b0;
    end else begin
      valid <= tick;                               // the RAM answers in the same clock
      if (tick) addr <= (addr == len_m1) ? '0 : addr + 1'b1;
      cnt <= (cnt + 16'd1 >= div) ? 16'd0 : cnt + 16'd1;
    end
  end
endmodule
`default_nettype wire
