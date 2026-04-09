`timescale 1ns/1ps

module min8_io_filo #(
    parameter [7:0] CHANNEL = 8'h13,
    parameter integer DEPTH = 32
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
    output [7:0] dbg_level,
    output       dbg_empty,
    output       dbg_full,
    output [7:0] dbg_top
);
    localparam integer LEVEL_WIDTH = (DEPTH <= 1) ? 1 : $clog2(DEPTH + 1);
    localparam integer INDEX_WIDTH = (DEPTH <= 2) ? 1 : $clog2(DEPTH);
    localparam integer LEVEL_PAD_WIDTH = (LEVEL_WIDTH < 8) ? (8 - LEVEL_WIDTH) : 0;

    reg [7:0] stack_mem [0:DEPTH-1];
    reg [LEVEL_WIDTH-1:0] level_q;

    wire channel_match = (io_chan == CHANNEL);
    wire stack_empty = (level_q == {LEVEL_WIDTH{1'b0}});
    wire [31:0] level_q_ext = {{(32 - LEVEL_WIDTH){1'b0}}, level_q};
    wire stack_full = (level_q_ext == DEPTH);
    wire do_pop = channel_match && core_rx_pop_in && !stack_empty;
    wire do_push = channel_match && core_tx_push_in && !stack_full;
    wire [INDEX_WIDTH-1:0] stack_push_index = level_q[INDEX_WIDTH-1:0];
    wire [INDEX_WIDTH-1:0] stack_top_index = level_q[INDEX_WIDTH-1:0] - 1'b1;
    wire [7:0] stack_top = stack_empty ? 8'h00 : stack_mem[stack_top_index];

    assign core_rx_data_out = channel_match ? stack_top : ext_rx_data_in;
    assign core_rx_valid_out = channel_match ? !stack_empty : ext_rx_valid_in;
    assign core_tx_ready_out = channel_match ? !stack_full : ext_tx_ready_in;

    assign ext_rx_pop_out = !channel_match && core_rx_pop_in;
    assign ext_tx_data_out = core_tx_data_in;
    assign ext_tx_push_out = !channel_match && core_tx_push_in;

    assign dbg_level = {{LEVEL_PAD_WIDTH{1'b0}}, level_q};
    assign dbg_empty = stack_empty;
    assign dbg_full = stack_full;
    assign dbg_top = stack_top;

    always @(posedge clk) begin
        if (rst) begin
            level_q <= {LEVEL_WIDTH{1'b0}};
        end else begin
            case ({do_push, do_pop})
                2'b10: begin
                    stack_mem[stack_push_index] <= core_tx_data_in;
                    level_q <= level_q + 1'b1;
                end
                2'b01: begin
                    level_q <= level_q - 1'b1;
                end
                2'b11: begin
                    stack_mem[stack_top_index] <= core_tx_data_in;
                end
                default: begin
                end
            endcase
        end
    end
endmodule
