// Self-checking testbench for adf4351_spi: every word of vectors/spi_words.hex is decoded the way
// an ADF4351 does (sample DAT on rising CLK while LE is low, load on rising LE) and compared.
// Also checked: frame length 67 H, idle levels, DAT stable around the rising clock edge, the
// divider values 1 (treated as 2), 2, 3, 5, 20, and that `start` is ignored while busy.
`timescale 1ns / 1ps
module tb_adf4351_spi;
  logic clk = 0, resetn = 0;
  logic [7:0] div = 8'd5;
  logic start = 0;
  logic [31:0] word = '0;
  logic busy, sclk, sdat, le;

  always #5 clk = ~clk;

  adf4351_spi dut (.*);

  logic [31:0] words [0:4095];
  logic [31:0] cnt_mem [0:0];
  int n_words;

  // --- ADF4351 side ---
  logic [31:0] sh;
  int          nbits;
  logic [31:0] got;
  int          got_bits, frames;
  logic        sdat_prev;
  always @(negedge le) begin nbits = 0; sh = '0; end
  always @(posedge sclk) begin
    if (le) fail("clock edge while LE is high");
    if (sdat !== sdat_prev) fail("DAT changed in the clock before the rising CLK edge");
    sh = {sh[30:0], sdat};
    nbits++;
  end
  always @(posedge le) if (resetn) begin got = sh; got_bits = nbits; frames++; end
  always @(posedge clk) sdat_prev <= sdat;

  task automatic fail(input string why);
    $display("TB FAIL: %s (time %0t)", why, $time);
    $finish;
  endtask

  task automatic send(input logic [31:0] w, input int d);
    int h, t0, clocks;
    h = (d < 2) ? 2 : d;
    div = d[7:0];
    word = w;
    @(posedge clk); start <= 1;
    @(posedge clk); start <= 0; word <= ~w;      // the word must have been taken at start
    clocks = 0;
    @(posedge clk);
    if (!busy) fail("busy did not rise");
    while (busy) begin @(posedge clk); clocks++; end
    if (clocks != 67 * h) fail($sformatf("frame took %0d clocks, expected %0d (H=%0d)", clocks, 67 * h, h));
    if (got_bits != 32) fail($sformatf("%0d clock edges in a frame", got_bits));
    if (got !== w) fail($sformatf("word %08x arrived as %08x", w, got));
    if (sclk !== 0 || le !== 1 || sdat !== 0) fail("idle levels wrong after a word");
  endtask

  initial begin
    frames = 0;
    $readmemh("vectors/spi_words.cnt", cnt_mem);
    n_words = cnt_mem[0];
    $readmemh("vectors/spi_words.hex", words, 0, n_words - 1);
    if (n_words < 20) fail("too few words in vectors/spi_words.hex");
    repeat (4) @(posedge clk);
    if (sclk !== 0 || le !== 1 || busy !== 0) fail("levels wrong in reset");
    resetn = 1;
    repeat (4) @(posedge clk);
    for (int i = 0; i < n_words; i++) send(words[i], 5);
    for (int i = 0; i < 12; i++) begin
      send(words[i], 1);
      send(words[i], 2);
      send(words[i], 3);
      send(words[i], 20);
    end
    // start while busy is ignored
    div = 8'd5; word = 32'h12345678;
    @(posedge clk); start <= 1;
    @(posedge clk); start <= 0;
    repeat (50) @(posedge clk);
    word = 32'hDEADBEEF; start <= 1;
    @(posedge clk); start <= 0;
    while (busy) @(posedge clk);
    if (got !== 32'h12345678) fail("a start during a word disturbed it");
    repeat (500) @(posedge clk);
    if (frames != n_words + 48 + 1) fail($sformatf("%0d frames seen, expected %0d", frames, n_words + 49));
    $display("TB PASS  (%0d words)", frames);
    $finish;
  end

  initial begin #200ms; $display("TB FAIL: timeout"); $finish; end
endmodule
