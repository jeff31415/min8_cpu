`timescale 1ns/1ps

module min8_io_ws2812 #(
    parameter [7:0] CHANNEL = 8'h12,
    parameter integer FIFO_DEPTH = 16,
    parameter integer FIFO_ADDR_WIDTH = 4,
    parameter integer FRAME_BYTES = 12,
    parameter integer T0H_CYCLES = 40,
    parameter integer T0L_CYCLES = 85,
    parameter integer T1H_CYCLES = 80,
    parameter integer T1L_CYCLES = 45,
    parameter integer RESET_CYCLES = 6000
) (
    input        clk,
    input        rst,
    input  [7:0] io_chan,
    input  [7:0] ext_rx_data_in,
    input        ext_rx_valid_in,
    output       ext_rx_pop_out,
    input        ext_tx_ready_in,
    output [7:0] ext_tx_data_out,
    output       ext_tx_push_out,
    output [7:0] core_rx_data_out,
    output       core_rx_valid_out,
    input        core_rx_pop_in,
    output       core_tx_ready_out,
    input  [7:0] core_tx_data_in,
    input        core_tx_push_in,
    output reg   ws2812_out,
    output [7:0] dbg_fifo_level,
    output       dbg_busy,
    output [7:0] dbg_frame_byte_count
) ;
    localparam [1:0] S_IDLE = 2'd0;
    localparam [1:0] S_HIGH = 2'd1;
    localparam [1:0] S_LOW = 2'd2;
    localparam [1:0] S_RESET = 2'd3;
    localparam integer FIFO_LEVEL_PAD_WIDTH =
        ((FIFO_ADDR_WIDTH + 1) < 8) ? (8 - (FIFO_ADDR_WIDTH + 1)) : 0;

    reg [1:0] state_q;
    reg [31:0] phase_counter_q;
    reg [31:0] reset_counter_q;
    reg [31:0] frame_byte_count_q;
    reg [7:0] shift_byte_q;
    reg [2:0] bit_index_q;
    reg       current_bit_q;

    wire channel_match = (io_chan == CHANNEL);

    wire [7:0] fifo_dout;
    wire       fifo_full;
    wire       fifo_empty;
    wire [FIFO_ADDR_WIDTH:0] fifo_level;
    wire       fifo_push = channel_match && core_tx_push_in && !fifo_full;

    wire load_from_idle = (state_q == S_IDLE) && !fifo_empty;
    wire byte_done = (state_q == S_LOW) && (phase_counter_q == 32'd0) && (bit_index_q == 3'd0);
    wire frame_limit_hit = (frame_byte_count_q == (FRAME_BYTES - 1));
    wire continue_frame = byte_done && !frame_limit_hit && !fifo_empty;
    wire fifo_pop = load_from_idle || continue_frame;

    assign core_rx_data_out = ext_rx_data_in;
    assign core_rx_valid_out = channel_match ? 1'b0 : ext_rx_valid_in;
    assign core_tx_ready_out = channel_match ? !fifo_full : ext_tx_ready_in;

    assign ext_rx_pop_out = !channel_match && core_rx_pop_in;
    assign ext_tx_data_out = core_tx_data_in;
    assign ext_tx_push_out = !channel_match && core_tx_push_in;

    assign dbg_fifo_level = {{FIFO_LEVEL_PAD_WIDTH{1'b0}}, fifo_level};
    assign dbg_busy = (state_q != S_IDLE);
    assign dbg_frame_byte_count = frame_byte_count_q[7:0];

    min8_sync_fifo #(
        .WIDTH(8),
        .DEPTH(FIFO_DEPTH),
        .ADDR_WIDTH(FIFO_ADDR_WIDTH)
    ) u_tx_fifo (
        .clk(clk),
        .rst(rst),
        .push(fifo_push),
        .din(core_tx_data_in),
        .pop(fifo_pop),
        .dout(fifo_dout),
        .full(fifo_full),
        .empty(fifo_empty),
        .level(fifo_level)
    );

    always @(posedge clk) begin
        if (rst) begin
            state_q <= S_IDLE;
            phase_counter_q <= 32'd0;
            reset_counter_q <= 32'd0;
            frame_byte_count_q <= 32'd0;
            shift_byte_q <= 8'h00;
            bit_index_q <= 3'd0;
            current_bit_q <= 1'b0;
            ws2812_out <= 1'b0;
        end else begin
            case (state_q)
                S_IDLE: begin
                    ws2812_out <= 1'b0;
                    if (load_from_idle) begin
                        shift_byte_q <= fifo_dout;
                        bit_index_q <= 3'd7;
                        current_bit_q <= fifo_dout[7];
                        phase_counter_q <= fifo_dout[7] ? (T1H_CYCLES - 1) : (T0H_CYCLES - 1);
                        state_q <= S_HIGH;
                        ws2812_out <= 1'b1;
                    end
                end

                S_HIGH: begin
                    if (phase_counter_q != 32'd0) begin
                        phase_counter_q <= phase_counter_q - 32'd1;
                    end else begin
                        phase_counter_q <= current_bit_q ? (T1L_CYCLES - 1) : (T0L_CYCLES - 1);
                        state_q <= S_LOW;
                        ws2812_out <= 1'b0;
                    end
                end

                S_LOW: begin
                    if (phase_counter_q != 32'd0) begin
                        phase_counter_q <= phase_counter_q - 32'd1;
                    end else if (bit_index_q != 3'd0) begin
                        shift_byte_q <= {shift_byte_q[6:0], 1'b0};
                        bit_index_q <= bit_index_q - 3'd1;
                        current_bit_q <= shift_byte_q[6];
                        phase_counter_q <= shift_byte_q[6] ? (T1H_CYCLES - 1) : (T0H_CYCLES - 1);
                        state_q <= S_HIGH;
                        ws2812_out <= 1'b1;
                    end else if (frame_limit_hit || fifo_empty) begin
                        frame_byte_count_q <= 32'd0;
                        ws2812_out <= 1'b0;
                        if (RESET_CYCLES <= 1) begin
                            state_q <= S_IDLE;
                        end else begin
                            reset_counter_q <= RESET_CYCLES - 1;
                            state_q <= S_RESET;
                        end
                    end else begin
                        shift_byte_q <= fifo_dout;
                        bit_index_q <= 3'd7;
                        current_bit_q <= fifo_dout[7];
                        phase_counter_q <= fifo_dout[7] ? (T1H_CYCLES - 1) : (T0H_CYCLES - 1);
                        frame_byte_count_q <= frame_byte_count_q + 32'd1;
                        state_q <= S_HIGH;
                        ws2812_out <= 1'b1;
                    end
                end

                S_RESET: begin
                    ws2812_out <= 1'b0;
                    if (reset_counter_q != 32'd0) begin
                        reset_counter_q <= reset_counter_q - 32'd1;
                    end else begin
                        state_q <= S_IDLE;
                    end
                end

                default: begin
                    state_q <= S_IDLE;
                    ws2812_out <= 1'b0;
                end
            endcase
        end
    end
endmodule
