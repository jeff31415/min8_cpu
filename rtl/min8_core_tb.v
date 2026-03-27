`timescale 1ns/1ps

module min8_core_tb #(
    parameter MEM_INIT_FILE = "",
    parameter CORE_LATCH_OPCODE = 1
);

    reg clk;
    reg rst;

    reg [7:0] rx_data;
    reg       rx_valid;
    reg       tx_ready;
    reg       tb_mem_we;
    reg [7:0] tb_mem_addr;
    reg [7:0] tb_mem_wdata;

    wire [7:0] imem_addr;
    wire       imem_en;
    wire [7:0] imem_rdata;
    wire [7:0] dmem_addr;
    wire       dmem_en;
    wire       dmem_we;
    wire [7:0] dmem_wdata;
    wire [7:0] dmem_rdata;
    wire       rx_pop;
    wire [7:0] tx_data;
    wire       tx_push;
    wire [7:0] io_chan;

    wire [2:0] dbg_state;
    wire [7:0] dbg_pc_before;
    wire [7:0] dbg_opcode;
    wire [63:0] dbg_regs_flat;
    wire [7:0] dbg_pc;
    wire       dbg_z;
    wire       dbg_c;
    wire [7:0] dbg_iosel;
    wire       dbg_retire;
    wire       dbg_blocked;
    wire       dbg_halted;
    wire       dbg_illegal;
    wire       dbg_mem_write_en;
    wire [7:0] dbg_mem_write_addr;
    wire [7:0] dbg_mem_write_data;
    wire       dbg_io_valid;
    wire       dbg_io_dir;
    wire [7:0] dbg_io_channel;
    wire [7:0] dbg_io_data;
    wire       halted;
    wire       illegal_instr;
    wire       faulted;
    wire [7:0] mem_dmem_addr;
    wire       mem_dmem_en;
    wire       mem_dmem_we;
    wire [7:0] mem_dmem_wdata;

    initial begin
        clk = 1'b0;
        rst = 1'b1;
        rx_data = 8'h00;
        rx_valid = 1'b0;
        tx_ready = 1'b1;
        tb_mem_we = 1'b0;
        tb_mem_addr = 8'h00;
        tb_mem_wdata = 8'h00;
    end

    assign mem_dmem_addr = tb_mem_we ? tb_mem_addr : dmem_addr;
    assign mem_dmem_en = tb_mem_we ? 1'b1 : dmem_en;
    assign mem_dmem_we = tb_mem_we ? 1'b1 : dmem_we;
    assign mem_dmem_wdata = tb_mem_we ? tb_mem_wdata : dmem_wdata;

    /* verilator lint_off UNUSEDSIGNAL */
    wire _unused_ok = &{
        1'b0,
        rx_pop,
        tx_push,
        tx_data,
        io_chan,
        dbg_state,
        dbg_pc_before,
        dbg_opcode,
        dbg_regs_flat,
        dbg_pc,
        dbg_z,
        dbg_c,
        dbg_iosel,
        dbg_retire,
        dbg_blocked,
        dbg_halted,
        dbg_illegal,
        dbg_mem_write_en,
        dbg_mem_write_addr,
        dbg_mem_write_data,
        dbg_io_valid,
        dbg_io_dir,
        dbg_io_channel,
        dbg_io_data,
        halted,
        illegal_instr,
        faulted
    };
    /* verilator lint_on UNUSEDSIGNAL */

    min8_core #(
        .LATCH_OPCODE(CORE_LATCH_OPCODE)
    ) u_core (
        .clk(clk),
        .rst(rst),
        .imem_addr(imem_addr),
        .imem_en(imem_en),
        .imem_rdata(imem_rdata),
        .dmem_addr(dmem_addr),
        .dmem_en(dmem_en),
        .dmem_we(dmem_we),
        .dmem_wdata(dmem_wdata),
        .dmem_rdata(dmem_rdata),
        .rx_data(rx_data),
        .rx_valid(rx_valid),
        .rx_pop(rx_pop),
        .tx_data(tx_data),
        .tx_ready(tx_ready),
        .tx_push(tx_push),
        .io_chan(io_chan),
        .dbg_state(dbg_state),
        .dbg_pc_before(dbg_pc_before),
        .dbg_opcode(dbg_opcode),
        .dbg_regs_flat(dbg_regs_flat),
        .dbg_pc(dbg_pc),
        .dbg_z(dbg_z),
        .dbg_c(dbg_c),
        .dbg_iosel(dbg_iosel),
        .dbg_retire(dbg_retire),
        .dbg_blocked(dbg_blocked),
        .dbg_halted(dbg_halted),
        .dbg_illegal(dbg_illegal),
        .dbg_mem_write_en(dbg_mem_write_en),
        .dbg_mem_write_addr(dbg_mem_write_addr),
        .dbg_mem_write_data(dbg_mem_write_data),
        .dbg_io_valid(dbg_io_valid),
        .dbg_io_dir(dbg_io_dir),
        .dbg_io_channel(dbg_io_channel),
        .dbg_io_data(dbg_io_data),
        .halted(halted),
        .illegal_instr(illegal_instr),
        .faulted(faulted)
    );

    min8_bram_wrap #(
        .MEM_INIT_FILE(MEM_INIT_FILE)
    ) u_mem (
        .clk(clk),
        .imem_en(imem_en),
        .imem_addr(imem_addr),
        .imem_rdata(imem_rdata),
        .dmem_en(mem_dmem_en),
        .dmem_we(mem_dmem_we),
        .dmem_addr(mem_dmem_addr),
        .dmem_wdata(mem_dmem_wdata),
        .dmem_rdata(dmem_rdata)
    );
endmodule
