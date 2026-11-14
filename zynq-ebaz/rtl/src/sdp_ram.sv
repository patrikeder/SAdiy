// Simple dual port RAM, one clock, registered read. Infers block RAM in Vivado.
// Read during write of the same address returns the old content.
`default_nettype none
module sdp_ram #(
  parameter int AW = 12,
  parameter int DW = 32
) (
  input  wire logic          clk,
  input  wire logic          we,
  input  wire logic [AW-1:0] waddr,
  input  wire logic [DW-1:0] wdata,
  input  wire logic [AW-1:0] raddr,
  output      logic [DW-1:0] rdata
);
  (* ram_style = "block" *) logic [DW-1:0] mem [0:(1<<AW)-1];

  always_ff @(posedge clk) begin
    if (we) mem[waddr] <= wdata;
    rdata <= mem[raddr];
  end
endmodule
`default_nettype wire
