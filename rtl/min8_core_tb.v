`timescale 1ns/1ps

module min8_core_tb #(
    parameter MEM_INIT_FILE = "",
    parameter CORE_LATCH_OPCODE = 1,
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
);

    reg clk;
    reg rst;

    reg [7:0] rx_data;
    reg       rx_valid;
    reg       tx_ready;
    reg       ps2_clk;
    reg       ps2_data;
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
    wire [7:0] core_rx_data;
    wire       core_rx_valid;
    wire       core_rx_pop;
    wire [7:0] core_tx_data;
    wire       core_tx_ready;
    wire       core_tx_push;

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
    wire [7:0] dbg_ps2_rx_level;
    wire [7:0] dbg_ps2_cmd_level;
    wire [15:0] dbg_ps2_dropped_count;
    wire [15:0] dbg_ps2_frame_error_count;
    wire [7:0] dbg_audio_fifo_level;
    wire [7:0] dbg_audio_current_sample;
    wire [15:0] dbg_audio_underflow_count;
    wire       dbg_audio_dsm_out;
    wire [7:0] dbg_ws2812_fifo_level;
    wire       dbg_ws2812_busy;
    wire [7:0] dbg_ws2812_frame_byte_count;
    wire       dbg_ws2812_out;
    wire [7:0] dbg_filo_level;
    wire       dbg_filo_empty;
    wire       dbg_filo_full;
    wire [7:0] dbg_filo_top;
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
        ps2_clk = 1'b1;
        ps2_data = 1'b1;
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
        dbg_ps2_rx_level,
        dbg_ps2_cmd_level,
        dbg_ps2_dropped_count,
        dbg_ps2_frame_error_count,
        dbg_audio_fifo_level,
        dbg_audio_current_sample,
        dbg_audio_underflow_count,
        dbg_audio_dsm_out,
        dbg_ws2812_fifo_level,
        dbg_ws2812_busy,
        dbg_ws2812_frame_byte_count,
        dbg_ws2812_out,
        dbg_filo_level,
        dbg_filo_empty,
        dbg_filo_full,
        dbg_filo_top,
        halted,
        illegal_instr,
        faulted
    };
    /* verilator lint_on UNUSEDSIGNAL */

    min8_io_peripheral_chain #(
        .PS2_CHANNEL(PS2_CHANNEL),
        .PS2_RX_FIFO_DEPTH(PS2_RX_FIFO_DEPTH),
        .PS2_RX_FIFO_ADDR_WIDTH(PS2_RX_FIFO_ADDR_WIDTH),
        .PS2_CMD_FIFO_DEPTH(PS2_CMD_FIFO_DEPTH),
        .PS2_CMD_FIFO_ADDR_WIDTH(PS2_CMD_FIFO_ADDR_WIDTH),
        .AUDIO_CHANNEL(AUDIO_CHANNEL),
        .AUDIO_FIFO_DEPTH(AUDIO_FIFO_DEPTH),
        .AUDIO_FIFO_ADDR_WIDTH(AUDIO_FIFO_ADDR_WIDTH),
        .AUDIO_SAMPLE_TICK_DIVISOR(AUDIO_SAMPLE_TICK_DIVISOR),
        .AUDIO_MOD_TICK_DIVISOR(AUDIO_MOD_TICK_DIVISOR),
        .AUDIO_SILENCE_VALUE(AUDIO_SILENCE_VALUE),
        .AUDIO_READBACK_VALUE(AUDIO_READBACK_VALUE),
        .WS2812_CHANNEL(WS2812_CHANNEL),
        .WS2812_FIFO_DEPTH(WS2812_FIFO_DEPTH),
        .WS2812_FIFO_ADDR_WIDTH(WS2812_FIFO_ADDR_WIDTH),
        .WS2812_FRAME_BYTES(WS2812_FRAME_BYTES),
        .WS2812_T0H_CYCLES(WS2812_T0H_CYCLES),
        .WS2812_T0L_CYCLES(WS2812_T0L_CYCLES),
        .WS2812_T1H_CYCLES(WS2812_T1H_CYCLES),
        .WS2812_T1L_CYCLES(WS2812_T1L_CYCLES),
        .WS2812_RESET_CYCLES(WS2812_RESET_CYCLES),
        .FILO_CHANNEL(FILO_CHANNEL),
        .FILO_DEPTH(FILO_DEPTH)
    ) u_io (
        .clk(clk),
        .rst(rst),
        .io_chan(io_chan),
        .ext_rx_data_in(rx_data),
        .ext_rx_valid_in(rx_valid),
        .ext_rx_pop_out(rx_pop),
        .ext_tx_ready_in(tx_ready),
        .ext_tx_data_out(tx_data),
        .ext_tx_push_out(tx_push),
        .core_rx_data_out(core_rx_data),
        .core_rx_valid_out(core_rx_valid),
        .core_rx_pop_in(core_rx_pop),
        .core_tx_ready_out(core_tx_ready),
        .core_tx_data_in(core_tx_data),
        .core_tx_push_in(core_tx_push),
        .ps2_clk_in(ps2_clk),
        .ps2_data_in(ps2_data),
        .audio_dsm_out(dbg_audio_dsm_out),
        .ws2812_out(dbg_ws2812_out),
        .dbg_ps2_rx_level(dbg_ps2_rx_level),
        .dbg_ps2_cmd_level(dbg_ps2_cmd_level),
        .dbg_ps2_dropped_count(dbg_ps2_dropped_count),
        .dbg_ps2_frame_error_count(dbg_ps2_frame_error_count),
        .dbg_audio_fifo_level(dbg_audio_fifo_level),
        .dbg_audio_current_sample(dbg_audio_current_sample),
        .dbg_audio_underflow_count(dbg_audio_underflow_count),
        .dbg_ws2812_fifo_level(dbg_ws2812_fifo_level),
        .dbg_ws2812_busy(dbg_ws2812_busy),
        .dbg_ws2812_frame_byte_count(dbg_ws2812_frame_byte_count),
        .dbg_filo_level(dbg_filo_level),
        .dbg_filo_empty(dbg_filo_empty),
        .dbg_filo_full(dbg_filo_full),
        .dbg_filo_top(dbg_filo_top)
    );

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
        .rx_data(core_rx_data),
        .rx_valid(core_rx_valid),
        .rx_pop(core_rx_pop),
        .tx_data(core_tx_data),
        .tx_ready(core_tx_ready),
        .tx_push(core_tx_push),
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
