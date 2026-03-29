`timescale 1ns/1ps

module min8_uart_rx #(
    parameter integer CLK_FREQ_HZ = 100_000_000,
    parameter integer BAUD_RATE = 115_200
) (
    input        clk,
    input        rst,
    input        rxd,
    output reg [7:0] data_out,
    output reg   valid
);
    localparam integer CLKS_PER_BIT = (CLK_FREQ_HZ + (BAUD_RATE / 2)) / BAUD_RATE;
    localparam integer HALF_CLKS_PER_BIT = (CLKS_PER_BIT > 1) ? (CLKS_PER_BIT / 2) : 1;

    localparam [1:0] S_IDLE  = 2'd0;
    localparam [1:0] S_START = 2'd1;
    localparam [1:0] S_DATA  = 2'd2;
    localparam [1:0] S_STOP  = 2'd3;

    reg [1:0] rx_sync_q;
    reg [1:0] state_q;
    reg [2:0] bit_index_q;
    reg [7:0] shift_q;
    reg [31:0] baud_counter_q;

    wire rxd_sync = rx_sync_q[1];

    always @(posedge clk) begin
        if (rst) begin
            rx_sync_q <= 2'b11;
            state_q <= S_IDLE;
            bit_index_q <= 3'd0;
            shift_q <= 8'h00;
            baud_counter_q <= 32'd0;
            data_out <= 8'h00;
            valid <= 1'b0;
        end else begin
            rx_sync_q <= {rx_sync_q[0], rxd};
            valid <= 1'b0;

            case (state_q)
                S_IDLE: begin
                    if (!rxd_sync) begin
                        state_q <= S_START;
                        baud_counter_q <= HALF_CLKS_PER_BIT - 1;
                    end
                end

                S_START: begin
                    if (baud_counter_q != 0) begin
                        baud_counter_q <= baud_counter_q - 1'b1;
                    end else if (!rxd_sync) begin
                        state_q <= S_DATA;
                        bit_index_q <= 3'd0;
                        baud_counter_q <= CLKS_PER_BIT - 1;
                    end else begin
                        state_q <= S_IDLE;
                    end
                end

                S_DATA: begin
                    if (baud_counter_q != 0) begin
                        baud_counter_q <= baud_counter_q - 1'b1;
                    end else begin
                        shift_q[bit_index_q] <= rxd_sync;
                        baud_counter_q <= CLKS_PER_BIT - 1;
                        if (bit_index_q == 3'd7) begin
                            state_q <= S_STOP;
                        end else begin
                            bit_index_q <= bit_index_q + 1'b1;
                        end
                    end
                end

                S_STOP: begin
                    if (baud_counter_q != 0) begin
                        baud_counter_q <= baud_counter_q - 1'b1;
                    end else begin
                        if (rxd_sync) begin
                            data_out <= shift_q;
                            valid <= 1'b1;
                        end
                        state_q <= S_IDLE;
                    end
                end

                default: begin
                    state_q <= S_IDLE;
                end
            endcase
        end
    end
endmodule
