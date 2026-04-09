`timescale 1ns/1ps

module min8_io_ps2 #(
    parameter [7:0] CHANNEL = 8'h10,
    parameter integer RX_FIFO_DEPTH = 8,
    parameter integer RX_FIFO_ADDR_WIDTH = 3,
    parameter integer CMD_FIFO_DEPTH = 4,
    parameter integer CMD_FIFO_ADDR_WIDTH = 2
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
    output [7:0] dbg_rx_level,
    output [7:0] dbg_cmd_level,
    output [15:0] dbg_dropped_count,
    output [15:0] dbg_frame_error_count
);
    localparam integer RX_LEVEL_PAD_WIDTH =
        ((RX_FIFO_ADDR_WIDTH + 1) < 8) ? (8 - (RX_FIFO_ADDR_WIDTH + 1)) : 0;
    localparam integer CMD_LEVEL_PAD_WIDTH =
        ((CMD_FIFO_ADDR_WIDTH + 1) < 8) ? (8 - (CMD_FIFO_ADDR_WIDTH + 1)) : 0;

    reg [2:0] ps2_clk_sync_q;
    reg [2:0] ps2_data_sync_q;
    reg [10:0] frame_q;
    reg [3:0] bit_count_q;
    reg [15:0] dropped_count_q;
    reg [15:0] frame_error_count_q;

    wire channel_match = (io_chan == CHANNEL);
    wire ps2_clk_sync = ps2_clk_sync_q[2];
    wire ps2_data_sync = ps2_data_sync_q[2];
    wire ps2_clk_fall = (ps2_clk_sync_q[2:1] == 2'b10);

    reg [10:0] captured_frame;
    always @* begin
        captured_frame = frame_q;
        if (bit_count_q != 0) begin
            captured_frame[bit_count_q] = ps2_data_sync;
        end
    end

    wire [7:0] received_byte = captured_frame[8:1];
    wire parity_ok = ((^received_byte) ^ captured_frame[9]);
    wire frame_complete = ps2_clk_fall && (bit_count_q == 4'd10);
    wire frame_valid =
        frame_complete &&
        !captured_frame[0] &&
        captured_frame[10] &&
        parity_ok;

    wire [7:0] rx_fifo_dout;
    wire       rx_fifo_full;
    wire       rx_fifo_empty;
    wire [RX_FIFO_ADDR_WIDTH:0] rx_fifo_level;
    wire       rx_fifo_push = frame_valid && !rx_fifo_full;
    wire       rx_fifo_pop = channel_match && core_rx_pop_in && !rx_fifo_empty;

    wire [7:0] cmd_fifo_dout;
    wire       cmd_fifo_full;
    wire       cmd_fifo_empty;
    wire [CMD_FIFO_ADDR_WIDTH:0] cmd_fifo_level;
    wire       cmd_fifo_push = channel_match && core_tx_push_in && !cmd_fifo_full;

    assign core_rx_data_out = channel_match ? (rx_fifo_empty ? 8'h00 : rx_fifo_dout) : ext_rx_data_in;
    assign core_rx_valid_out = channel_match ? 1'b1 : ext_rx_valid_in;
    assign core_tx_ready_out = channel_match ? !cmd_fifo_full : ext_tx_ready_in;

    assign ext_rx_pop_out = !channel_match && core_rx_pop_in;
    assign ext_tx_data_out = core_tx_data_in;
    assign ext_tx_push_out = !channel_match && core_tx_push_in;

    assign dbg_rx_level = {{RX_LEVEL_PAD_WIDTH{1'b0}}, rx_fifo_level};
    assign dbg_cmd_level = {{CMD_LEVEL_PAD_WIDTH{1'b0}}, cmd_fifo_level};
    assign dbg_dropped_count = dropped_count_q;
    assign dbg_frame_error_count = frame_error_count_q;

    min8_sync_fifo #(
        .WIDTH(8),
        .DEPTH(RX_FIFO_DEPTH),
        .ADDR_WIDTH(RX_FIFO_ADDR_WIDTH)
    ) u_rx_fifo (
        .clk(clk),
        .rst(rst),
        .push(rx_fifo_push),
        .din(received_byte),
        .pop(rx_fifo_pop),
        .dout(rx_fifo_dout),
        .full(rx_fifo_full),
        .empty(rx_fifo_empty),
        .level(rx_fifo_level)
    );

    min8_sync_fifo #(
        .WIDTH(8),
        .DEPTH(CMD_FIFO_DEPTH),
        .ADDR_WIDTH(CMD_FIFO_ADDR_WIDTH)
    ) u_cmd_fifo (
        .clk(clk),
        .rst(rst),
        .push(cmd_fifo_push),
        .din(core_tx_data_in),
        .pop(1'b0),
        .dout(cmd_fifo_dout),
        .full(cmd_fifo_full),
        .empty(cmd_fifo_empty),
        .level(cmd_fifo_level)
    );

    /* verilator lint_off UNUSEDSIGNAL */
    wire _unused_ok = &{1'b0, ps2_clk_sync, cmd_fifo_dout, cmd_fifo_empty};
    /* verilator lint_on UNUSEDSIGNAL */

    always @(posedge clk) begin
        if (rst) begin
            ps2_clk_sync_q <= 3'b111;
            ps2_data_sync_q <= 3'b111;
            frame_q <= 11'h000;
            bit_count_q <= 4'd0;
            dropped_count_q <= 16'h0000;
            frame_error_count_q <= 16'h0000;
        end else begin
            ps2_clk_sync_q <= {ps2_clk_sync_q[1:0], ps2_clk_in};
            ps2_data_sync_q <= {ps2_data_sync_q[1:0], ps2_data_in};

            if (ps2_clk_fall) begin
                if (bit_count_q == 4'd0) begin
                    if (!ps2_data_sync) begin
                        frame_q <= 11'h000;
                        bit_count_q <= 4'd1;
                    end
                end else if (bit_count_q == 4'd10) begin
                    frame_q <= 11'h000;
                    bit_count_q <= 4'd0;
                    if (!frame_valid) begin
                        frame_error_count_q <= frame_error_count_q + 16'd1;
                    end else if (rx_fifo_full) begin
                        dropped_count_q <= dropped_count_q + 16'd1;
                    end
                end else begin
                    frame_q <= captured_frame;
                    bit_count_q <= bit_count_q + 4'd1;
                end
            end
        end
    end
endmodule
