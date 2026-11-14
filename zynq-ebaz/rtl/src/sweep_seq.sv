// Sweep sequencer. docs/rtl-spec.md section 6 is the specification; keep both in step.
// Executes table entries 0 .. n_entries-1: attenuator (make-before-break), one SPI word, and for
// `measure` entries: minimum wait, lock wait, settle, sample, store. It only forwards table
// content; it never creates an SPI word.
`default_nettype none
module sweep_seq #(
  parameter int TABLE_AW   = 12,
  parameter int RESULT_AW  = 12,
  parameter int CLK_PER_US = 100
) (
  input  wire logic        clk,
  input  wire logic        resetn,
  // control (pulses are one clock)
  input  wire logic        start,
  input  wire logic        abort,
  input  wire logic        soft_reset,
  input  wire logic        irq_ack,
  input  wire logic        stop_on_err,
  input  wire logic        pin_owner_req,
  // configuration
  input  wire logic [15:0] n_entries,
  input  wire logic [19:0] t_min_us,
  input  wire logic [19:0] t_lock_stable_us,
  input  wire logic [19:0] t_lock_timeout_us,
  input  wire logic [19:0] t_settle_us,
  input  wire logic [5:0]  pe_manual,
  input  wire logic        pe_manual_wr,      // one clock: PE4302 was written (new value valid)
  input  wire logic [5:0]  pe_cur,            // PE4302 levels the engine drives now
  // status
  output      logic        busy,
  output      logic        done,
  output      logic        err_lock,
  output      logic        aborted,
  output      logic        err_table,
  output      logic        wait_sample,
  output      logic        pin_owner_act,
  output      logic [3:0]  state_o,
  output      logic [15:0] first_err_index,
  output      logic [15:0] point_count,
  output      logic [31:0] sweep_count,
  output      logic [15:0] entry_index,
  // table (registered read: data one clock after the address)
  output      logic [TABLE_AW-1:0]  tbl_raddr,
  input  wire logic [43:0]          tbl_rdata,   // {w1[11:0], w0}
  // results
  output      logic                 res_we,
  output      logic [RESULT_AW-1:0] res_waddr,
  output      logic [31:0]          res_wdata,
  // SPI writer
  output      logic        spi_start,
  output      logic [31:0] spi_word,
  input  wire logic        spi_busy,
  // attenuator driver
  output      logic        mbb_load,
  output      logic        mbb_set,
  output      logic [5:0]  mbb_value,
  input  wire logic        mbb_busy,
  // detector sampler
  output      logic        det_run,
  input  wire logic        det_done,
  input  wire logic [27:0] det_sum,
  // lock detect, already synchronised
  input  wire logic        ld
);
  // STATUS.state encoding: append new states, never renumber.
  typedef enum logic [3:0] {
    S_IDLE = 4'd0, S_FETCH = 4'd1, S_ATT = 4'd2, S_SPI = 4'd3, S_WAIT_MIN = 4'd4,
    S_WAIT_LOCK = 4'd5, S_SETTLE = 4'd6, S_SAMPLE = 4'd7, S_STORE = 4'd8, S_NEXT = 4'd9
  } state_t;

  localparam int USW = $clog2(CLK_PER_US);
  localparam logic [16:0] TABLE_DEPTH  = 17'd1 << TABLE_AW;
  localparam logic [16:0] RESULT_DEPTH = 17'd1 << RESULT_AW;

  state_t      state;
  logic        ph;                // second half of FETCH / ATT / SPI
  logic        start_pend, abort_pend;
  logic        manual_pend;       // PE4302 was written while idle and owner: apply it
  logic        start_owner;       // the engine owned the pins when start was written
  // entry being executed
  logic [31:0] ent_word;
  logic [5:0]  ent_att;
  logic        ent_spi_en, ent_att_en, ent_measure, ent_skip_lock;
  // point being measured
  logic        unlocked;
  logic [27:0] sum_q;
  logic [16:0] pcount;            // one bit more than the register: detects a full result memory
  // timers, restarted on every state change
  logic [USW:0] us_div, st_div;
  logic [19:0]  us_cnt, st_cnt;   // microseconds in this state / with LD high in a row
  logic         timer_clr;
  logic         spi_exit, min_done, lock_ok, lock_timeout;

  logic idle_quiet;
  assign idle_quiet    = (state == S_IDLE) && !spi_busy && !mbb_busy;
  assign busy          = (state != S_IDLE) || start_pend;
  assign wait_sample   = (state == S_SAMPLE);
  assign det_run       = (state == S_SAMPLE);
  assign state_o       = state;
  assign point_count   = pcount[15:0];
  assign tbl_raddr     = entry_index[TABLE_AW-1:0];
  assign spi_word      = ent_word;
  assign res_waddr     = pcount[RESULT_AW-1:0];
  assign res_wdata     = {unlocked, 3'b000, sum_q};

  // Combinational strobes to the SPI writer, attenuator driver and result memory.
  logic take_pins, manual_changed;
  assign take_pins      = idle_quiet && pin_owner_req && !pin_owner_act;
  assign manual_changed = idle_quiet && pin_owner_act && manual_pend && (pe_manual != pe_cur);

  always_comb begin
    mbb_load  = 1'b0;
    mbb_set   = 1'b0;
    mbb_value = pe_manual;
    spi_start = 1'b0;
    res_we    = 1'b0;
    if (take_pins) begin
      mbb_load = 1'b1;
    end else if (manual_changed) begin
      mbb_set = 1'b1;
    end else if (state == S_ATT && !ph && ent_att_en && !abort_pend) begin
      mbb_set   = 1'b1;
      mbb_value = ent_att;
    end
    if (state == S_SPI && !ph && ent_spi_en && !abort_pend) spi_start = 1'b1;
    if (state == S_STORE && !abort_pend && pcount != RESULT_DEPTH) res_we = 1'b1;
  end

  // State exits that the timers depend on. Every one of them restarts the timers.
  assign spi_exit     = (state == S_SPI) && (ph ? !spi_busy : !ent_spi_en);
  assign min_done     = (state == S_WAIT_MIN) && (us_cnt >= t_min_us);
  assign lock_ok      = (state == S_WAIT_LOCK) && ld && (st_cnt >= t_lock_stable_us);
  assign lock_timeout = (state == S_WAIT_LOCK) && !lock_ok && (us_cnt >= t_lock_timeout_us);
  assign timer_clr    = spi_exit || min_done || lock_ok || lock_timeout;

  // An SPI word or an attenuator change that has started always finishes.
  logic interruptible;
  assign interruptible = !((state == S_ATT || state == S_SPI) && ph);

  always_ff @(posedge clk) begin
    if (!resetn) begin
      state           <= S_IDLE;
      ph              <= 1'b0;
      start_pend      <= 1'b0;
      abort_pend      <= 1'b0;
      pin_owner_act   <= 1'b0;
      manual_pend     <= 1'b0;
      start_owner     <= 1'b0;
      done            <= 1'b0;
      err_lock        <= 1'b0;
      aborted         <= 1'b0;
      err_table       <= 1'b0;
      first_err_index <= '0;
      pcount          <= '0;
      sweep_count     <= '0;
      entry_index     <= '0;
      ent_word        <= '0;
      ent_att         <= '0;
      ent_spi_en      <= 1'b0;
      ent_att_en      <= 1'b0;
      ent_measure     <= 1'b0;
      ent_skip_lock   <= 1'b0;
      unlocked        <= 1'b0;
      sum_q           <= '0;
      us_div          <= '0;
      us_cnt          <= '0;
      st_div          <= '0;
      st_cnt          <= '0;
    end else if (soft_reset) begin
      // Sequencer, status and counters. The pin owner and the pins stay, and a running SPI word /
      // attenuator change finishes in its own module.
      state           <= S_IDLE;
      ph              <= 1'b0;
      start_pend      <= 1'b0;
      abort_pend      <= 1'b0;
      done            <= 1'b0;
      err_lock        <= 1'b0;
      aborted         <= 1'b0;
      err_table       <= 1'b0;
      first_err_index <= '0;
      pcount          <= '0;
      entry_index     <= '0;
      sweep_count     <= '0;
      manual_pend     <= 1'b0;
    end else begin
      if (irq_ack) done <= 1'b0;
      if (abort && state != S_IDLE) abort_pend <= 1'b1;

      // ---- pin owner and manual attenuator value, only while nothing runs ----
      if (idle_quiet) begin
        pin_owner_act <= pin_owner_req;
        manual_pend   <= 1'b0;                 // applied in this clock (mbb_set) or not needed
      end
      // A PE4302 write counts only while the engine owns the pins and no sweep runs or waits.
      if (pe_manual_wr && pin_owner_act && state == S_IDLE && !start_pend) manual_pend <= 1'b1;

      if (abort_pend && interruptible && state != S_IDLE) begin
        state      <= S_IDLE;
        ph         <= 1'b0;
        abort_pend <= 1'b0;
        done       <= 1'b1;
        aborted    <= 1'b1;
      end else begin
        unique case (state)
          S_IDLE: begin
            abort_pend <= 1'b0;
            if (start && !start_pend) begin
              start_pend  <= 1'b1;
              start_owner <= pin_owner_act;    // taking the pins and start in one write: refused
              done       <= 1'b0;
              err_lock   <= 1'b0;
              aborted    <= 1'b0;
              err_table  <= 1'b0;
              pcount     <= '0;
              first_err_index <= '0;
              entry_index     <= '0;
            end else if (start_pend && idle_quiet && !take_pins && !manual_pend) begin
              start_pend <= 1'b0;
              if (n_entries == 16'd0 || {1'b0, n_entries} > TABLE_DEPTH
                  || !start_owner || !pin_owner_act) begin
                err_table <= 1'b1;
                done      <= 1'b1;
              end else begin
                state <= S_FETCH;
                ph    <= 1'b0;
              end
            end
          end

          S_FETCH: begin                       // clock 1: RAM reads; clock 2: take the entry
            ph <= 1'b1;
            if (ph) begin
              ent_word      <= tbl_rdata[31:0];
              ent_att       <= tbl_rdata[32+5:32];
              ent_spi_en    <= tbl_rdata[32+8];
              ent_att_en    <= tbl_rdata[32+9];
              ent_measure   <= tbl_rdata[32+10];
              ent_skip_lock <= tbl_rdata[32+11];
              state <= S_ATT;
              ph    <= 1'b0;
            end
          end

          S_ATT: begin
            if (!ph) begin
              if (ent_att_en) ph <= 1'b1;      // mbb_set is high in this clock
              else            state <= S_SPI;
            end else if (!mbb_busy) begin
              state <= S_SPI;
              ph    <= 1'b0;
            end
          end

          S_SPI: begin
            if (spi_exit) begin
              ph <= 1'b0;
              if (ent_measure) begin
                state    <= S_WAIT_MIN;
                unlocked <= 1'b0;
              end else begin
                state <= S_NEXT;
              end
            end else if (!ph) begin
              ph <= 1'b1;                      // spi_start is high in this clock
            end
          end

          S_WAIT_MIN: begin
            if (min_done) state <= ent_skip_lock ? S_SETTLE : S_WAIT_LOCK;
          end

          S_WAIT_LOCK: begin
            if (lock_ok) begin
              state <= S_SETTLE;
            end else if (lock_timeout) begin
              unlocked <= 1'b1;
              err_lock <= 1'b1;
              if (!err_lock) first_err_index <= pcount[15:0];
              if (stop_on_err) begin
                state <= S_IDLE;
                done  <= 1'b1;
              end else begin
                state <= S_SETTLE;
              end
            end
          end

          S_SETTLE: begin
            if (us_cnt >= t_settle_us) state <= S_SAMPLE;
          end

          S_SAMPLE: begin
            if (det_done) begin
              sum_q <= det_sum;
              state <= S_STORE;
            end
          end

          S_STORE: begin
            if (pcount == RESULT_DEPTH) begin  // result memory full
              err_table <= 1'b1;
              done      <= 1'b1;
              state     <= S_IDLE;
            end else begin
              pcount <= pcount + 17'd1;        // res_we is high in this clock
              state  <= S_NEXT;
            end
          end

          S_NEXT: begin
            entry_index <= entry_index + 16'd1;
            if (entry_index + 16'd1 == n_entries) begin
              state       <= S_IDLE;
              done        <= 1'b1;
              sweep_count <= sweep_count + 32'd1;
            end else begin
              state <= S_FETCH;
              ph    <= 1'b0;
            end
          end

          default: state <= S_IDLE;
        endcase
      end

      // ---- timers ----
      if (timer_clr) begin
        us_div <= '0;
        us_cnt <= '0;
        st_div <= '0;
        st_cnt <= '0;
      end else begin
        if (us_div == (USW+1)'(CLK_PER_US - 1)) begin
          us_div <= '0;
          if (us_cnt != 20'hFFFFF) us_cnt <= us_cnt + 20'd1;
        end else begin
          us_div <= us_div + 1'b1;
        end
        if (!ld) begin
          st_div <= '0;
          st_cnt <= '0;
        end else if (st_div == (USW+1)'(CLK_PER_US - 1)) begin
          st_div <= '0;
          if (st_cnt != 20'hFFFFF) st_cnt <= st_cnt + 20'd1;
        end else begin
          st_div <= st_div + 1'b1;
        end
      end
    end
  end
endmodule
`default_nettype wire
