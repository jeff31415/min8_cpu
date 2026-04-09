`timescale 1ns/1ps

module min8_io_peripheral_chain #(
    parameter [7:0] PS2_CHANNEL = 8'h10,
    parameter integer PS2_RX_FIFO_DEPTH = 8,
    parameter integer PS2_RX_FIFO_ADDR_WIDTH = 3,
    parameter integer PS2_CMD_FIFO_DEPTH = 4,
    parameter integer PS2_CMD_FIFO_ADDR_WIDTH = 2,
    parameter [7:0] AUDIO_CHANNEL = 8'h11,
    parameter integer AUDIO_FIFO_DEPTH = 8,
    parameter integer AUDIO_FIFO_ADDR_WIDTH = 3,
    parameter integer AUDIO_SAMPLE_TICK_DIVISOR = 6250,
    parameter integer AUDIO_MOD_TICK_DIVISOR = 10,
    parameter [7:0] AUDIO_SILENCE_VALUE = 8'h80,
    parameter [7:0] AUDIO_READBACK_VALUE = 8'h80,
    parameter [7:0] WS2812_CHANNEL = 8'h12,
    parameter integer WS2812_FIFO_DEPTH = 16,
    parameter integer WS2812_FIFO_ADDR_WIDTH = 4,
    parameter integer WS2812_FRAME_BYTES = 12,
    parameter integer WS2812_T0H_CYCLES = 40,
    parameter integer WS2812_T0L_CYCLES = 85,
    parameter integer WS2812_T1H_CYCLES = 80,
    parameter integer WS2812_T1L_CYCLES = 45,
    parameter integer WS2812_RESET_CYCLES = 6000,
    parameter [7:0] FILO_CHANNEL = 8'h13,
    parameter integer FILO_DEPTH = 8
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
    input        ps2_clk_in,
    input        ps2_data_in,
    output       audio_dsm_out,
    output       ws2812_out,
    output [7:0] dbg_ps2_rx_level,
    output [7:0] dbg_ps2_cmd_level,
    output [15:0] dbg_ps2_dropped_count,
    output [15:0] dbg_ps2_frame_error_count,
    output [7:0] dbg_audio_fifo_level,
    output [7:0] dbg_audio_current_sample,
    output [15:0] dbg_audio_underflow_count,
    output [7:0] dbg_ws2812_fifo_level,
    output       dbg_ws2812_busy,
    output [7:0] dbg_ws2812_frame_byte_count,
    output [7:0] dbg_filo_level,
    output       dbg_filo_empty,
    output       dbg_filo_full,
    output [7:0] dbg_filo_top
);
    wire [7:0] stage1_rx_data;
    wire       stage1_rx_valid;
    wire       stage1_rx_pop;
    wire [7:0] stage1_tx_data;
    wire       stage1_tx_ready;
    wire       stage1_tx_push;

    wire [7:0] stage2_rx_data;
    wire       stage2_rx_valid;
    wire       stage2_rx_pop;
    wire [7:0] stage2_tx_data;
    wire       stage2_tx_ready;
    wire       stage2_tx_push;

    wire [7:0] stage3_rx_data;
    wire       stage3_rx_valid;
    wire       stage3_rx_pop;
    wire [7:0] stage3_tx_data;
    wire       stage3_tx_ready;
    wire       stage3_tx_push;

    min8_io_filo #(
        .CHANNEL(FILO_CHANNEL),
        .DEPTH(FILO_DEPTH)
    ) u_filo (
        .clk(clk),
        .rst(rst),
        .io_chan(io_chan),
        .ext_rx_data_in(stage1_rx_data),
        .ext_rx_valid_in(stage1_rx_valid),
        .ext_rx_pop_out(stage1_rx_pop),
        .ext_tx_ready_in(stage1_tx_ready),
        .ext_tx_data_out(stage1_tx_data),
        .ext_tx_push_out(stage1_tx_push),
        .core_rx_data_out(core_rx_data_out),
        .core_rx_valid_out(core_rx_valid_out),
        .core_rx_pop_in(core_rx_pop_in),
        .core_tx_ready_out(core_tx_ready_out),
        .core_tx_data_in(core_tx_data_in),
        .core_tx_push_in(core_tx_push_in),
        .dbg_level(dbg_filo_level),
        .dbg_empty(dbg_filo_empty),
        .dbg_full(dbg_filo_full),
        .dbg_top(dbg_filo_top)
    );

    min8_io_ws2812 #(
        .CHANNEL(WS2812_CHANNEL),
        .FIFO_DEPTH(WS2812_FIFO_DEPTH),
        .FIFO_ADDR_WIDTH(WS2812_FIFO_ADDR_WIDTH),
        .FRAME_BYTES(WS2812_FRAME_BYTES),
        .T0H_CYCLES(WS2812_T0H_CYCLES),
        .T0L_CYCLES(WS2812_T0L_CYCLES),
        .T1H_CYCLES(WS2812_T1H_CYCLES),
        .T1L_CYCLES(WS2812_T1L_CYCLES),
        .RESET_CYCLES(WS2812_RESET_CYCLES)
    ) u_ws2812 (
        .clk(clk),
        .rst(rst),
        .io_chan(io_chan),
        .ext_rx_data_in(stage2_rx_data),
        .ext_rx_valid_in(stage2_rx_valid),
        .ext_rx_pop_out(stage2_rx_pop),
        .ext_tx_ready_in(stage2_tx_ready),
        .ext_tx_data_out(stage2_tx_data),
        .ext_tx_push_out(stage2_tx_push),
        .core_rx_data_out(stage1_rx_data),
        .core_rx_valid_out(stage1_rx_valid),
        .core_rx_pop_in(stage1_rx_pop),
        .core_tx_ready_out(stage1_tx_ready),
        .core_tx_data_in(stage1_tx_data),
        .core_tx_push_in(stage1_tx_push),
        .ws2812_out(ws2812_out),
        .dbg_fifo_level(dbg_ws2812_fifo_level),
        .dbg_busy(dbg_ws2812_busy),
        .dbg_frame_byte_count(dbg_ws2812_frame_byte_count)
    );

    min8_io_audio #(
        .CHANNEL(AUDIO_CHANNEL),
        .FIFO_DEPTH(AUDIO_FIFO_DEPTH),
        .FIFO_ADDR_WIDTH(AUDIO_FIFO_ADDR_WIDTH),
        .SAMPLE_TICK_DIVISOR(AUDIO_SAMPLE_TICK_DIVISOR),
        .MOD_TICK_DIVISOR(AUDIO_MOD_TICK_DIVISOR),
        .SILENCE_VALUE(AUDIO_SILENCE_VALUE),
        .READBACK_VALUE(AUDIO_READBACK_VALUE)
    ) u_audio (
        .clk(clk),
        .rst(rst),
        .io_chan(io_chan),
        .ext_rx_data_in(stage3_rx_data),
        .ext_rx_valid_in(stage3_rx_valid),
        .ext_rx_pop_out(stage3_rx_pop),
        .ext_tx_ready_in(stage3_tx_ready),
        .ext_tx_data_out(stage3_tx_data),
        .ext_tx_push_out(stage3_tx_push),
        .core_rx_data_out(stage2_rx_data),
        .core_rx_valid_out(stage2_rx_valid),
        .core_rx_pop_in(stage2_rx_pop),
        .core_tx_ready_out(stage2_tx_ready),
        .core_tx_data_in(stage2_tx_data),
        .core_tx_push_in(stage2_tx_push),
        .audio_dsm_out(audio_dsm_out),
        .dbg_fifo_level(dbg_audio_fifo_level),
        .dbg_current_sample(dbg_audio_current_sample),
        .dbg_underflow_count(dbg_audio_underflow_count)
    );

    min8_io_ps2 #(
        .CHANNEL(PS2_CHANNEL),
        .RX_FIFO_DEPTH(PS2_RX_FIFO_DEPTH),
        .RX_FIFO_ADDR_WIDTH(PS2_RX_FIFO_ADDR_WIDTH),
        .CMD_FIFO_DEPTH(PS2_CMD_FIFO_DEPTH),
        .CMD_FIFO_ADDR_WIDTH(PS2_CMD_FIFO_ADDR_WIDTH)
    ) u_ps2 (
        .clk(clk),
        .rst(rst),
        .io_chan(io_chan),
        .ext_rx_data_in(ext_rx_data_in),
        .ext_rx_valid_in(ext_rx_valid_in),
        .ext_rx_pop_out(ext_rx_pop_out),
        .ext_tx_ready_in(ext_tx_ready_in),
        .ext_tx_data_out(ext_tx_data_out),
        .ext_tx_push_out(ext_tx_push_out),
        .core_rx_data_out(stage3_rx_data),
        .core_rx_valid_out(stage3_rx_valid),
        .core_rx_pop_in(stage3_rx_pop),
        .core_tx_ready_out(stage3_tx_ready),
        .core_tx_data_in(stage3_tx_data),
        .core_tx_push_in(stage3_tx_push),
        .ps2_clk_in(ps2_clk_in),
        .ps2_data_in(ps2_data_in),
        .dbg_rx_level(dbg_ps2_rx_level),
        .dbg_cmd_level(dbg_ps2_cmd_level),
        .dbg_dropped_count(dbg_ps2_dropped_count),
        .dbg_frame_error_count(dbg_ps2_frame_error_count)
    );
endmodule
