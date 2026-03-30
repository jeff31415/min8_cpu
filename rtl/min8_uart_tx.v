`timescale 1ns/1ps

module min8_uart_tx #(
    parameter integer CLK_FREQ_HZ = 100_000_000,
    parameter integer BAUD_RATE = 115_200
) (
    input        clk,
    input        rst,
    input  [7:0] data_in,
    input        valid,
    output       ready,
    output reg   txd
);
    localparam integer CLKS_PER_BIT =
        ((64'd1 * CLK_FREQ_HZ) + (BAUD_RATE / 2)) / BAUD_RATE;

    reg [9:0] frame_q;
    reg [3:0] bit_index_q;
    reg [31:0] baud_counter_q;
    reg busy_q;

    assign ready = !busy_q;

    always @(posedge clk) begin
        if (rst) begin
            frame_q <= 10'h3FF;
            bit_index_q <= 4'd0;
            baud_counter_q <= 32'd0;
            busy_q <= 1'b0;
            txd <= 1'b1;
        end else if (!busy_q) begin
            txd <= 1'b1;
            if (valid) begin
                frame_q <= {1'b1, data_in, 1'b0};
                bit_index_q <= 4'd0;
                baud_counter_q <= CLKS_PER_BIT - 1;
                busy_q <= 1'b1;
                txd <= 1'b0;
            end
        end else if (baud_counter_q != 0) begin
            baud_counter_q <= baud_counter_q - 1'b1;
        end else begin
            baud_counter_q <= CLKS_PER_BIT - 1;
            if (bit_index_q == 4'd9) begin
                busy_q <= 1'b0;
                txd <= 1'b1;
            end else begin
                bit_index_q <= bit_index_q + 1'b1;
                txd <= frame_q[bit_index_q + 1'b1];
            end
        end
    end
endmodule
