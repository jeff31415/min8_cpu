`timescale 1ns/1ps

module min8_bram_wrap #(
    parameter MEM_INIT_FILE = ""
) (
    input        clk,
    input        imem_en,
    input  [7:0] imem_addr,
    output reg [7:0] imem_rdata,
    input        dmem_en,
    input        dmem_we,
    input  [7:0] dmem_addr,
    input  [7:0] dmem_wdata,
    output reg [7:0] dmem_rdata
);
    (* ram_style = "block" *) reg [7:0] mem [0:255];
    integer index;

    initial begin
        for (index = 0; index < 256; index = index + 1) begin
            mem[index] = 8'h00;
        end
        imem_rdata = 8'h00;
        dmem_rdata = 8'h00;
        if (MEM_INIT_FILE != "") begin
            $readmemh(MEM_INIT_FILE, mem);
        end
    end

    always @(posedge clk) begin
        if (imem_en) begin
            imem_rdata <= mem[imem_addr];
        end

        if (dmem_en) begin
            dmem_rdata <= mem[dmem_addr];
            if (dmem_we) begin
                mem[dmem_addr] <= dmem_wdata;
            end
        end
    end
endmodule
