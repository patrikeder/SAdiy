// Self-checking testbench for pe4302_mbb: all 64 x 64 transitions, both polarities, against
// vectors/mbb_high.hex and mbb_low.hex (made by running drivers/pe4302.py on recording fake
// lines). Line = {old[5:0], new[5:0], make[5:0]}. Also the hold time of the make and final state.
`timescale 1ns / 1ps
module tb_pe4302_mbb;
  logic clk = 0, resetn = 0;
  logic [15:0] gap = 16'd3;
  logic active_high = 1;
  logic load = 0, set = 0;
  logic [5:0] value = '0;
  logic [5:0] pins;
  logic busy;

  always #5 clk = ~clk;

  pe4302_mbb dut (.*);

  logic [17:0] vec_high [0:4095];
  logic [17:0] vec_low  [0:4095];

  task automatic fail(input string why);
    $display("TB FAIL: %s (time %0t)", why, $time);
    $finish;
  endtask

  // Go from `o` to `n` and check the pins in every clock.
  task automatic transition(input logic [5:0] o, input logic [5:0] n, input logic [5:0] make,
                            input int g);
    int hold;
    hold = (g < 1) ? 1 : g;
    gap = g[15:0];
    value = o;
    @(negedge clk); load = 1;
    @(negedge clk); load = 0;
    if (pins !== o) fail("load did not set the pins");
    if (busy) fail("busy after load");
    value = n; set = 1;
    @(negedge clk); set = 0; value = ~n;         // value must have been taken
    for (int i = 0; i < hold; i++) begin
      if (pins !== make) fail($sformatf("%02x -> %02x: make state %02x, expected %02x", o, n, pins, make));
      if (!busy) fail("not busy in the make state");
      @(negedge clk);
    end
    for (int i = 0; i < hold; i++) begin
      if (pins !== n) fail($sformatf("%02x -> %02x: final state %02x", o, n, pins));
      if (!busy) fail("not busy while holding the final state");
      @(negedge clk);
    end
    if (busy) fail("busy too long");
    if (pins !== n) fail("pins changed after the end");
  endtask

  initial begin
    $readmemh("vectors/mbb_high.hex", vec_high);
    $readmemh("vectors/mbb_low.hex", vec_low);
    repeat (3) @(negedge clk);
    if (pins !== 6'h3F) fail("pins not all high in reset");
    resetn = 1;
    @(negedge clk);
    for (int pol = 1; pol >= 0; pol--) begin
      active_high = pol[0];
      for (int i = 0; i < 4096; i++) begin
        logic [17:0] v;
        v = pol ? vec_high[i] : vec_low[i];
        if (v[17:12] !== i[11:6] || v[11:6] !== i[5:0]) fail("vector file is not in old*64+new order");
        transition(v[17:12], v[11:6], v[5:0], 3);
      end
    end
    active_high = 1;
    transition(6'h1F, 6'h20, 6'h3F, 100);        // 15.5 dB -> 16 dB passes 31.5 dB, never 0 dB
    transition(6'h1F, 6'h20, 6'h3F, 1);
    transition(6'h1F, 6'h20, 6'h3F, 0);
    // set and load are ignored while busy
    gap = 16'd10; value = 6'h00;
    @(negedge clk); load = 1; @(negedge clk); load = 0;
    value = 6'h2A; set = 1; @(negedge clk); set = 0;
    value = 6'h15; set = 1; @(negedge clk); set = 0;
    load = 1; @(negedge clk); load = 0;
    while (busy) @(negedge clk);
    if (pins !== 6'h2A) fail("set / load during a change disturbed it");
    $display("TB PASS  (8192 transitions)");
    $finish;
  end

  initial begin #50ms; $display("TB FAIL: timeout"); $finish; end
endmodule
