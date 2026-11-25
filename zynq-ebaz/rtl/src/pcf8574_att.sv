// PE4302 attenuator through a PCF8574 I2C port expander, make-before-break. docs/rtl-spec.md section 9.
// Replaces the direct pin driver pe4302_mbb of register map 1.x. Port wiring (fixed, user 2026-11-25; the
// PCF8574 board is an I2C-to-LCD adapter):
//   P0 = V1 (0.5 dB)  P1 = V2  P2 = V3  P3 = backlight LED (p3)  P4 = V4  P5 = V5  P6 = V6 (16 dB)  P7 = p7
//   set : one transaction S addr+W make final P, make = old | value when active_high (old & value otherwise):
//         the PCF8574 takes each byte at its ACK, so the make state is held one byte (9 SCL periods) and no
//         intermediate state has less attenuation than the lower of the two settings. When make = value
//         (only stages switched in) the transaction carries the one byte. Then `gap` clocks of hold.
//   load: S addr+W value P (used when the engine takes the pins: its first write).
// `levels` is what the engine sent last (V1..V6); reset 0x3F = the PCF8574's power-up state (all ports high).
`default_nettype none
module pcf8574_att (
  input  wire logic        clk,
  input  wire logic        resetn,
  input  wire logic [15:0] gap,
  input  wire logic        active_high,
  input  wire logic        load,         // one clock; ignored while busy
  input  wire logic        set,          // one clock; ignored while busy
  input  wire logic [5:0]  value,
  input  wire logic [6:0]  addr,
  input  wire logic        p3,
  input  wire logic        p7,
  input  wire logic [11:0] div,
  input  wire logic        err_clear,    // one clock: clear err_nack
  output      logic [5:0]  levels,
  output      logic        busy,
  output      logic        err_nack,     // sticky
  output      logic [7:0]  last_byte,
  output      logic [7:0]  count,        // transactions finished, wraps
  output      logic        scl_t,
  output      logic        sda_t,
  input  wire logic        sda_i
);
  function automatic logic [7:0] port_byte(input logic [5:0] v, input logic bl, input logic b7);
    return {b7, v[5], v[4], v[3], bl, v[2], v[1], v[0]};
  endfunction

  typedef enum logic [1:0] {S_IDLE, S_WR, S_HOLD} state_t;
  state_t      state;
  logic [15:0] cnt;
  logic [5:0]  target, make;
  logic        wr_start, wr_two, wr_busy, wr_done, wr_nack;
  logic [7:0]  wr_b0, wr_b1;

  assign busy = (state != S_IDLE);
  assign make = active_high ? (levels | value) : (levels & value);

  always_comb begin
    wr_start = 1'b0;
    wr_two   = 1'b0;
    wr_b0    = port_byte(value, p3, p7);
    wr_b1    = port_byte(value, p3, p7);
    if (state == S_IDLE && !wr_busy) begin
      if (load) begin
        wr_start = 1'b1;
      end else if (set) begin
        wr_start = 1'b1;
        if (make != value) begin
          wr_two = 1'b1;
          wr_b0  = port_byte(make, p3, p7);
        end
      end
    end
  end

  i2c_wr u_i2c (
    .clk, .resetn,
    .start (wr_start),
    .addr,
    .two   (wr_two),
    .b0    (wr_b0),
    .b1    (wr_b1),
    .div,
    .busy  (wr_busy),
    .done  (wr_done),
    .nack  (wr_nack),
    .scl_t, .sda_t, .sda_i
  );

  always_ff @(posedge clk) begin
    if (!resetn) begin
      state <= S_IDLE; cnt <= '0; target <= 6'h3F; levels <= 6'h3F;
      err_nack <= 1'b0; last_byte <= 8'hFF; count <= '0;
    end else begin
      if (err_clear) err_nack <= 1'b0;
      unique case (state)
        S_IDLE: begin
          if (wr_start) begin
            target <= value;
            state  <= S_WR;
          end
        end
        S_WR: begin
          if (wr_done) begin
            levels    <= target;
            last_byte <= port_byte(target, p3, p7);
            count     <= count + 8'd1;
            if (wr_nack) err_nack <= 1'b1;
            cnt       <= gap;
            state     <= S_HOLD;
          end
        end
        S_HOLD: begin
          if (cnt <= 16'd1) state <= S_IDLE;
          else              cnt   <= cnt - 16'd1;
        end
        default: state <= S_IDLE;
      endcase
    end
  end
endmodule
`default_nettype wire
