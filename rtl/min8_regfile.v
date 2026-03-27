`timescale 1ns/1ps

module min8_regfile (
    input        clk,
    input        rst,
    input  [2:0] src_addr,
    output [7:0] rdata_r1,
    output [7:0] rdata_r2,
    output [7:0] rdata_src,
    output [7:0] rdata_r7,
    output [63:0] regs_flat,
    input        we1,
    input  [2:0] waddr1,
    input  [7:0] wdata1,
    input        we2,
    input  [2:0] waddr2,
    input  [7:0] wdata2
);
    reg [7:0] regs [0:7];
    integer index;

    assign rdata_r1 = regs[1];
    assign rdata_r2 = regs[2];
    assign rdata_src = regs[src_addr];
    assign rdata_r7 = regs[7];
    assign regs_flat = {
        regs[7],
        regs[6],
        regs[5],
        regs[4],
        regs[3],
        regs[2],
        regs[1],
        regs[0]
    };

    always @(posedge clk) begin
        if (rst) begin
            for (index = 0; index < 8; index = index + 1) begin
                regs[index] <= 8'h00;
            end
        end else begin
            if (we1) begin
                regs[waddr1] <= wdata1;
            end
            if (we2) begin
                regs[waddr2] <= wdata2;
            end
        end
    end
endmodule
