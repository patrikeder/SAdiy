// PE4302 pin driver with make-before-break. docs/rtl-spec.md section 9.
//   set : pins = make(old, value), held max(gap,1) clocks, then pins = value, held max(gap,1) clocks.
//         make = old | value when active_high, old & value otherwise: no intermediate state has
//         less attenuation than the lower of the two settings.
//   load: pins = value at once (only used when the engine takes the pins from the PS).
// Reset: all pins high (all stages in on an active-high module).
`default_nettype none
module pe4302_mbb (
  input  wire logic        clk,
  input  wire logic        resetn,
  input  wire logic [15:0] gap,
  input  wire logic        active_high,
  input  wire logic        load,      // one clock; ignored while busy
  input  wire logic        set,       // one clock; ignored while busy
  input  wire logic [5:0]  value,
  output      logic [5:0]  pins,
  output      logic        busy
);
  typedef enum logic [1:0] {S_IDLE, S_MAKE, S_FINAL} state_t;
  state_t      state;
  logic [15:0] cnt;
  logic [5:0]  target;

  assign busy = (state != S_IDLE);

  always_ff @(posedge clk) begin
    if (!resetn) begin
      state  <= S_IDLE;
      pins   <= 6'h3F;
      target <= 6'h3F;
      cnt    <= '0;
    end else begin
      unique case (state)
        S_IDLE: begin
          if (load) begin
            pins <= value;
          end else if (set) begin
            target <= value;
            pins   <= active_high ? (pins | value) : (pins & value);
            cnt    <= gap;
            state  <= S_MAKE;
          end
        end
        S_MAKE: begin
          if (cnt <= 16'd1) begin
            pins  <= target;
            cnt   <= gap;
            state <= S_FINAL;
          end else begin
            cnt <= cnt - 16'd1;
          end
        end
        S_FINAL: begin
          if (cnt <= 16'd1) state <= S_IDLE;
          else              cnt   <= cnt - 16'd1;
        end
        default: state <= S_IDLE;
      endcase
    end
  end
endmodule
`default_nettype wire
