// True dual port RAM, one clock, registered read on both ports (read before write). Infers block RAM.
`default_nettype none
module tdp_ram #(
  parameter int AW = 12,
  parameter int DW = 48
) (
  input  wire logic          clk,
  input  wire logic          we_a,
  input  wire logic [AW-1:0] addr_a,
  input  wire logic [DW-1:0] din_a,
  output      logic [DW-1:0] dout_a,
  input  wire logic          we_b,
  input  wire logic [AW-1:0] addr_b,
  input  wire logic [DW-1:0] din_b,
  output      logic [DW-1:0] dout_b
);
  /* verilator lint_off MULTIDRIVEN */
  (* ram_style = "block" *) logic [DW-1:0] mem [0:(1<<AW)-1];
  /* verilator lint_on MULTIDRIVEN */
  always_ff @(posedge clk) begin
    if (we_a) mem[addr_a] <= din_a;
    dout_a <= mem[addr_a];
  end
  always_ff @(posedge clk) begin
    if (we_b) mem[addr_b] <= din_b;
    dout_b <= mem[addr_b];
  end
endmodule
`default_nettype wire
