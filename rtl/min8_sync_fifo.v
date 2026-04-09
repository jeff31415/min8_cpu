`timescale 1ns/1ps

module min8_sync_fifo #(
    parameter WIDTH = 8,
    parameter DEPTH = 4,
    parameter ADDR_WIDTH = 2
) (
    input                   clk,
    input                   rst,
    input                   push,
    input      [WIDTH-1:0]  din,
    input                   pop,
    output     [WIDTH-1:0]  dout,
    output                  full,
    output                  empty,
    output reg [ADDR_WIDTH:0] level
);
    reg [WIDTH-1:0] mem [0:DEPTH-1];
    reg [ADDR_WIDTH-1:0] wr_ptr;
    reg [ADDR_WIDTH-1:0] rd_ptr;
    integer index;

    wire [31:0] level_ext = {{(32 - (ADDR_WIDTH + 1)){1'b0}}, level};
    wire do_push = push && !full;
    wire do_pop = pop && !empty;

    assign full = (level_ext == DEPTH);
    assign empty = (level == 0);
    assign dout = mem[rd_ptr];

    always @(posedge clk) begin
        if (rst) begin
            wr_ptr <= {ADDR_WIDTH{1'b0}};
            rd_ptr <= {ADDR_WIDTH{1'b0}};
            level <= {(ADDR_WIDTH + 1){1'b0}};
            for (index = 0; index < DEPTH; index = index + 1) begin
                mem[index] <= {WIDTH{1'b0}};
            end
        end else begin
            if (do_push) begin
                mem[wr_ptr] <= din;
                wr_ptr <= wr_ptr + 1'b1;
            end

            if (do_pop) begin
                rd_ptr <= rd_ptr + 1'b1;
            end

            case ({do_push, do_pop})
                2'b10: level <= level + 1'b1;
                2'b01: level <= level - 1'b1;
                default: level <= level;
            endcase
        end
    end
endmodule
