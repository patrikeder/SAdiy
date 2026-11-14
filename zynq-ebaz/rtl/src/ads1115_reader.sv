// ADS1115 reader: I2C master that takes single-shot conversions while `run` is high and hands each one to
// det_sampler as a 16-bit unsigned sample. docs/rtl-spec.md section 8a.
//
// One sample = config write (starts the conversion), wait t_conv_us, pointer write, 2-byte read:
//   S addr+W 01 cfg_hi cfg_lo P | wait | S addr+W 00 P | S addr+R hi(ACK) lo(NACK) P
// A bit is four quarter periods of H = max(div, 4) clocks: SCL low / high / high / low; SDA changes at the
// start of the first quarter and is sampled at the end of the second. SCL and SDA are open drain
// (`*_t` = 1 releases the line). No clock stretching and no arbitration (single master, the ADS1115 never
// stretches). A NACK ends the transaction with a STOP, sets `err_nack` and delivers the sample 0, so a sweep
// does not hang when the ADC is missing. A negative code (below GND) is delivered as 0.
// If `run` goes low during a sample, the bus transaction still ends properly but nothing is delivered.
`default_nettype none
module ads1115_reader #(
  parameter int CLK_PER_US = 100
) (
  input  wire logic        clk,
  input  wire logic        resetn,
  input  wire logic        run,          // take samples while high
  input  wire logic [6:0]  addr,         // I2C address
  input  wire logic [15:0] cfg,          // config register word (OS = 1, single shot)
  input  wire logic [11:0] div,          // quarter bit period in clocks
  input  wire logic [19:0] t_conv_us,    // wait between the config write and the read
  input  wire logic        err_clear,    // one clock: clear err_nack
  output      logic        valid,        // one clock per sample
  output      logic [15:0] data,         // unsigned (negative codes clamped to 0)
  output      logic [15:0] last_raw,     // last conversion register as read (two's complement)
  output      logic        err_nack,     // sticky
  output      logic [7:0]  count,        // conversions read since reset, wraps
  output      logic        busy,         // a bus transaction or the conversion wait is running
  // I2C, open drain
  output      logic        scl_t,
  output      logic        sda_t,
  input  wire logic        sda_i
);
  // ---- program: one entry per bus operation ----
  typedef enum logic [2:0] {OP_START, OP_TX, OP_RX, OP_STOP, OP_WAIT, OP_EMIT} op_t;
  localparam int LAST_STEP = 16;
  logic [4:0] step;
  op_t        op;
  logic [7:0] tx_byte;
  logic       rx_ack;                    // RX: 1 = answer with ACK (more bytes follow)

  always_comb begin
    tx_byte = 8'h00;
    rx_ack  = 1'b0;
    unique case (step)
      5'd0:    op = OP_START;
      5'd1:    begin op = OP_TX; tx_byte = {addr, 1'b0}; end
      5'd2:    begin op = OP_TX; tx_byte = 8'h01; end           // pointer: config
      5'd3:    begin op = OP_TX; tx_byte = cfg[15:8]; end
      5'd4:    begin op = OP_TX; tx_byte = cfg[7:0]; end
      5'd5:    op = OP_STOP;
      5'd6:    op = OP_WAIT;
      5'd7:    op = OP_START;
      5'd8:    begin op = OP_TX; tx_byte = {addr, 1'b0}; end
      5'd9:    begin op = OP_TX; tx_byte = 8'h00; end           // pointer: conversion
      5'd10:   op = OP_STOP;
      5'd11:   op = OP_START;
      5'd12:   begin op = OP_TX; tx_byte = {addr, 1'b1}; end
      5'd13:   begin op = OP_RX; rx_ack = 1'b1; end
      5'd14:   op = OP_RX;
      5'd15:   op = OP_STOP;
      default: op = OP_EMIT;                                    // LAST_STEP
    endcase
  end

  // ---- timing ----
  localparam int USW = $clog2(CLK_PER_US);
  logic [11:0]  h, qcnt;
  logic         qtick;                   // last clock of a quarter
  logic [1:0]   q;                       // quarter within the bit
  logic [USW:0] us_div;
  logic [19:0]  us_cnt;
  assign h     = (div < 12'd4) ? 12'd4 : div;
  assign qtick = (qcnt == h - 12'd1);

  // ---- state ----
  logic        active;                   // a sample cycle is running
  logic        cancelled;                // run went low during the cycle
  logic        nack;                     // this cycle saw a NACK
  logic        to_stop;                  // after a NACK: the STOP in progress ends the cycle
  logic [3:0]  bit_i;                    // 0..7 data, 8 ack
  logic [7:0]  sh;
  logic [15:0] rx_word;
  logic [1:0]  sda_sync;
  logic [1:0]  gap;                      // clocks after a sample before `run` is looked at again

  assign busy = active;

  always_ff @(posedge clk) begin
    sda_sync <= {sda_sync[0], sda_i};
    valid    <= 1'b0;
    if (!resetn) begin
      active <= 1'b0; cancelled <= 1'b0; nack <= 1'b0; to_stop <= 1'b0; gap <= '0;
      step <= '0; q <= '0; qcnt <= '0; bit_i <= '0; sh <= '0; rx_word <= '0;
      us_div <= '0; us_cnt <= '0;
      scl_t <= 1'b1; sda_t <= 1'b1;
      data <= '0; last_raw <= '0; err_nack <= 1'b0; count <= '0;
    end else begin
      if (err_clear) err_nack <= 1'b0;
      if (!active) begin
        scl_t <= 1'b1; sda_t <= 1'b1;
        step <= '0; q <= '0; qcnt <= '0; bit_i <= '0;
        cancelled <= 1'b0; nack <= 1'b0; to_stop <= 1'b0;
        // the sampler needs two clocks to take the sample and drop `run` after the last one
        if (gap != 2'd0) gap <= gap - 2'd1;
        else if (run)    active <= 1'b1;
      end else begin
        if (!run) cancelled <= 1'b1;
        unique case (op)
          OP_START: begin                       // q0, q1: bus idle; q2: SDA low; q3: SCL low
            unique case (q)
              2'd0, 2'd1: begin scl_t <= 1'b1; sda_t <= 1'b1; end
              2'd2:       begin scl_t <= 1'b1; sda_t <= 1'b0; end
              default:    begin scl_t <= 1'b0; sda_t <= 1'b0; end
            endcase
            if (qtick) begin
              qcnt <= '0; q <= q + 2'd1;
              if (q == 2'd3) begin step <= step + 5'd1; bit_i <= '0; end
            end else qcnt <= qcnt + 12'd1;
          end
          OP_TX, OP_RX: begin
            scl_t <= (q == 2'd1 || q == 2'd2);
            if (q == 2'd0 && qcnt == '0) begin  // SDA for this bit
              if (op == OP_TX) sda_t <= (bit_i == 4'd8) ? 1'b1 : tx_byte[3'd7 - bit_i[2:0]];
              else             sda_t <= (bit_i == 4'd8) ? !rx_ack : 1'b1;
            end
            if (qtick) begin
              qcnt <= '0; q <= q + 2'd1;
              if (q == 2'd1) begin              // middle of SCL high
                if (bit_i != 4'd8) sh <= {sh[6:0], sda_sync[1]};
                else if (op == OP_TX && sda_sync[1]) nack <= 1'b1;
              end
              if (q == 2'd3) begin
                if (bit_i == 4'd8) begin
                  bit_i <= '0;
                  if (op == OP_RX) rx_word <= {rx_word[7:0], sh};
                  if (op == OP_TX && nack) begin step <= 5'd15; to_stop <= 1'b1; end   // STOP, then give up
                  else step <= step + 5'd1;
                end else bit_i <= bit_i + 4'd1;
              end
            end else qcnt <= qcnt + 12'd1;
          end
          OP_STOP: begin                        // q0: SDA low; q1: SCL high; q2: SDA high; q3: idle
            unique case (q)
              2'd0:    begin scl_t <= 1'b0; sda_t <= 1'b0; end
              2'd1:    begin scl_t <= 1'b1; sda_t <= 1'b0; end
              default: begin scl_t <= 1'b1; sda_t <= 1'b1; end
            endcase
            if (qtick) begin
              qcnt <= '0; q <= q + 2'd1;
              if (q == 2'd3) begin
                step   <= to_stop ? 5'(LAST_STEP) : step + 5'd1;
                us_div <= '0; us_cnt <= '0;
              end
            end else qcnt <= qcnt + 12'd1;
          end
          OP_WAIT: begin                        // bus idle: a cancelled cycle ends here
            if (cancelled) active <= 1'b0;
            else if (us_div == (USW+1)'(CLK_PER_US - 1)) begin
              us_div <= '0;
              if (us_cnt + 20'd1 >= t_conv_us) step <= step + 5'd1;
              else us_cnt <= us_cnt + 20'd1;
            end else us_div <= us_div + 1'b1;
          end
          default: begin                        // OP_EMIT
            active <= 1'b0;
            gap    <= 2'd3;
            if (nack) err_nack <= 1'b1;
            else begin last_raw <= rx_word; count <= count + 8'd1; end
            if (!cancelled && run) begin
              valid <= 1'b1;
              data  <= (nack || rx_word[15]) ? 16'd0 : rx_word;
            end
          end
        endcase
      end
    end
  end
endmodule
`default_nettype wire
