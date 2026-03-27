`timescale 1ns/1ps

module min8_mem_model #(
    parameter MEM_INIT_FILE = ""
) (
    input        clk,
    input        imem_en,
    input  [7:0] imem_addr,
    output [7:0] imem_rdata,
    input        dmem_en,
    input        dmem_we,
    input  [7:0] dmem_addr,
    input  [7:0] dmem_wdata,
    output [7:0] dmem_rdata
);
    reg [7:0] mem [0:255];
    integer index;

    assign imem_rdata = imem_en ? mem[imem_addr] : 8'h00;
    assign dmem_rdata = dmem_en ? mem[dmem_addr] : 8'h00;

    initial begin
        for (index = 0; index < 256; index = index + 1) begin
            mem[index] = 8'h00;
        end
        if (MEM_INIT_FILE != "") begin
            $readmemh(MEM_INIT_FILE, mem);
        end
    end

    always @(posedge clk) begin
        if (dmem_en && dmem_we) begin
            mem[dmem_addr] <= dmem_wdata;
        end
    end
endmodule
