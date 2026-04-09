`timescale 1ns/1ps

module min8_io_audio #(
    parameter [7:0] CHANNEL = 8'h11,
    parameter integer FIFO_DEPTH = 8,
    parameter integer FIFO_ADDR_WIDTH = 3,
    parameter integer SAMPLE_TICK_DIVISOR = 6250,
    parameter integer MOD_TICK_DIVISOR = 10,
    parameter [7:0] SILENCE_VALUE = 8'h80,
    parameter [7:0] READBACK_VALUE = 8'h80
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
    output reg   audio_dsm_out,
    output [7:0] dbg_fifo_level,
    output [7:0] dbg_current_sample,
    output [15:0] dbg_underflow_count
) ;
    localparam integer FIFO_LEVEL_PAD_WIDTH =
        ((FIFO_ADDR_WIDTH + 1) < 8) ? (8 - (FIFO_ADDR_WIDTH + 1)) : 0;

    reg [31:0] sample_counter_q;
    reg [31:0] mod_counter_q;
    reg [7:0] current_sample_q;
    reg [7:0] dsm_error_q;
    reg [15:0] underflow_count_q;

    wire channel_match = (io_chan == CHANNEL);
    wire sample_tick =
        (SAMPLE_TICK_DIVISOR <= 1) ? 1'b1 :
        (sample_counter_q == SAMPLE_TICK_DIVISOR - 1);
    wire mod_tick =
        (MOD_TICK_DIVISOR <= 1) ? 1'b1 :
        (mod_counter_q == MOD_TICK_DIVISOR - 1);

    wire [7:0] fifo_dout;
    wire       fifo_full;
    wire       fifo_empty;
    wire [FIFO_ADDR_WIDTH:0] fifo_level;
    wire       fifo_push = channel_match && core_tx_push_in && !fifo_full;
    wire       fifo_pop = sample_tick && !fifo_empty;
    wire [8:0] dsm_sum = {1'b0, dsm_error_q} + {1'b0, current_sample_q};

    assign core_rx_data_out = channel_match ? READBACK_VALUE : ext_rx_data_in;
    assign core_rx_valid_out = channel_match ? 1'b1 : ext_rx_valid_in;
    assign core_tx_ready_out = channel_match ? !fifo_full : ext_tx_ready_in;

    assign ext_rx_pop_out = !channel_match && core_rx_pop_in;
    assign ext_tx_data_out = core_tx_data_in;
    assign ext_tx_push_out = !channel_match && core_tx_push_in;

    assign dbg_fifo_level = {{FIFO_LEVEL_PAD_WIDTH{1'b0}}, fifo_level};
    assign dbg_current_sample = current_sample_q;
    assign dbg_underflow_count = underflow_count_q;

    min8_sync_fifo #(
        .WIDTH(8),
        .DEPTH(FIFO_DEPTH),
        .ADDR_WIDTH(FIFO_ADDR_WIDTH)
    ) u_sample_fifo (
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
            sample_counter_q <= 32'd0;
            mod_counter_q <= 32'd0;
            current_sample_q <= SILENCE_VALUE;
            dsm_error_q <= 8'h00;
            audio_dsm_out <= 1'b0;
            underflow_count_q <= 16'h0000;
        end else begin
            if (SAMPLE_TICK_DIVISOR > 1) begin
                if (sample_tick) begin
                    sample_counter_q <= 32'd0;
                end else begin
                    sample_counter_q <= sample_counter_q + 32'd1;
                end
            end

            if (MOD_TICK_DIVISOR > 1) begin
                if (mod_tick) begin
                    mod_counter_q <= 32'd0;
                end else begin
                    mod_counter_q <= mod_counter_q + 32'd1;
                end
            end

            if (sample_tick) begin
                if (fifo_empty) begin
                    current_sample_q <= SILENCE_VALUE;
                    underflow_count_q <= underflow_count_q + 16'd1;
                end else begin
                    current_sample_q <= fifo_dout;
                end
            end

            if (mod_tick) begin
                {audio_dsm_out, dsm_error_q} <= dsm_sum;
            end
        end
    end
endmodule
