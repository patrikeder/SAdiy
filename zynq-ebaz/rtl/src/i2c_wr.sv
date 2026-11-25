// I2C write master: one transaction  S addr+W b0 [b1] P  per `start`. docs/rtl-spec.md section 9a.
// Bit timing as in the ADS1115 reader of register map 1.x (run on the board): a bit is four quarter periods of
// H = max(div, 4) clocks: SCL low / high / high / low; SDA changes at the start of the first quarter and is
// sampled at the end of the second. SCL and SDA are open drain (`*_t` = 1 releases the line). No clock
// stretching and no arbitration (single master; the PCF8574 never stretches). A NACK ends the transaction with
// a STOP and is reported with `done`.
`default_nettype none
module i2c_wr (
  input  wire logic        clk,
  input  wire logic        resetn,
  input  wire logic        start,        // one clock; ignored while busy
  input  wire logic [6:0]  addr,
  input  wire logic        two,          // 1 = send b0 and b1, 0 = b0 only
  input  wire logic [7:0]  b0,
  input  wire logic [7:0]  b1,
  input  wire logic [11:0] div,          // quarter bit period in clocks
  output      logic        busy,
  output      logic        done,         // one clock at the end of the STOP
  output      logic        nack,         // with done: a byte was not acknowledged
  output      logic        scl_t,
  output      logic        sda_t,
  input  wire logic        sda_i
);
  typedef enum logic [1:0] {OP_START, OP_TX, OP_STOP} op_t;
  logic [2:0] step;                      // 0 START, 1 addr, 2 b0, 3 b1, 4 STOP
  op_t        op;
  logic [7:0] tx_byte;
  logic        nack_q, two_q;
  logic [6:0]  addr_q;
  logic [7:0]  b0_q, b1_q;

  always_comb begin
    unique case (step)
      3'd0:    begin op = OP_START; tx_byte = 8'h00; end
      3'd1:    begin op = OP_TX;    tx_byte = {addr_q, 1'b0}; end
      3'd2:    begin op = OP_TX;    tx_byte = b0_q; end
      3'd3:    begin op = OP_TX;    tx_byte = b1_q; end
      default: begin op = OP_STOP;  tx_byte = 8'h00; end
    endcase
  end

  logic [11:0] h, qcnt;
  logic        qtick;
  logic [1:0]  q;
  logic [3:0]  bit_i;                    // 0..7 data, 8 ack
  logic [1:0]  sda_sync;
  assign h     = (div < 12'd4) ? 12'd4 : div;
  assign qtick = (qcnt == h - 12'd1);

  always_ff @(posedge clk) begin
    sda_sync <= {sda_sync[0], sda_i};
    done     <= 1'b0;
    if (!resetn) begin
      busy <= 1'b0; step <= '0; q <= '0; qcnt <= '0; bit_i <= '0;
      nack <= 1'b0; nack_q <= 1'b0; two_q <= 1'b0; addr_q <= '0; b0_q <= '0; b1_q <= '0;
      scl_t <= 1'b1; sda_t <= 1'b1;
    end else if (!busy) begin
      scl_t <= 1'b1; sda_t <= 1'b1;
      step <= '0; q <= '0; qcnt <= '0; bit_i <= '0;
      if (start) begin
        busy <= 1'b1; nack_q <= 1'b0;
        addr_q <= addr; two_q <= two; b0_q <= b0; b1_q <= b1;
      end
    end else begin
      unique case (op)
        OP_START: begin                         // q0, q1: bus idle; q2: SDA low; q3: SCL low
          unique case (q)
            2'd0, 2'd1: begin scl_t <= 1'b1; sda_t <= 1'b1; end
            2'd2:       begin scl_t <= 1'b1; sda_t <= 1'b0; end
            default:    begin scl_t <= 1'b0; sda_t <= 1'b0; end
          endcase
          if (qtick) begin
            qcnt <= '0; q <= q + 2'd1;
            if (q == 2'd3) begin step <= 3'd1; bit_i <= '0; end
          end else qcnt <= qcnt + 12'd1;
        end
        OP_TX: begin
          scl_t <= (q == 2'd1 || q == 2'd2);
          if (q == 2'd0 && qcnt == '0)
            sda_t <= (bit_i == 4'd8) ? 1'b1 : tx_byte[3'd7 - bit_i[2:0]];
          if (qtick) begin
            qcnt <= '0; q <= q + 2'd1;
            if (q == 2'd1 && bit_i == 4'd8 && sda_sync[1]) nack_q <= 1'b1;
            if (q == 2'd3) begin
              if (bit_i == 4'd8) begin
                bit_i <= '0;
                if (nack_q || step == 3'd3 || (step == 3'd2 && !two_q)) step <= 3'd4;   // STOP
                else                                                    step <= step + 3'd1;
              end else bit_i <= bit_i + 4'd1;
            end
          end else qcnt <= qcnt + 12'd1;
        end
        default: begin                          // OP_STOP  q0: SDA low; q1: SCL high; q2: SDA high; q3: idle
          unique case (q)
            2'd0:    begin scl_t <= 1'b0; sda_t <= 1'b0; end
            2'd1:    begin scl_t <= 1'b1; sda_t <= 1'b0; end
            default: begin scl_t <= 1'b1; sda_t <= 1'b1; end
          endcase
          if (qtick) begin
            qcnt <= '0; q <= q + 2'd1;
            if (q == 2'd3) begin busy <= 1'b0; done <= 1'b1; nack <= nack_q; end
          end else qcnt <= qcnt + 12'd1;
        end
      endcase
    end
  end
endmodule
`default_nettype wire
