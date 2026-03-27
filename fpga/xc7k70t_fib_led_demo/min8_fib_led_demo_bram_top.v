`timescale 1ns/1ps

module min8_fib_led_demo_bram_top #(
    parameter CORE_LATCH_OPCODE = 1,
    parameter MEM_INIT_FILE = ""
) (
    input         clk_200M_p,
    input         clk_200M_n,
    output [7:0]  leds
);
    localparam integer POWER_ON_RESET_CYCLES = 16;
    localparam integer ONE_HZ_DIVISOR = 100_000_000;

    wire clk_200m_ibuf;
    wire clk_100m_pll;
    wire clkfb_pll;
    wire clkfb_bufg;
    wire clk_core;
    wire pll_locked;

    reg [4:0] por_count = 5'd0;
    reg       core_rst = 1'b1;

    reg [27:0] second_counter = 28'd0;
    wire       second_tick = (second_counter == ONE_HZ_DIVISOR - 1);

    reg [7:0] led_latch = 8'h00;

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

    IBUFGDS u_ibufg_sys_clk (
        .I(clk_200M_p),
        .IB(clk_200M_n),
        .O(clk_200m_ibuf)
    );

    PLLE2_BASE #(
        .CLKIN1_PERIOD(5.000),
        .CLKFBOUT_MULT(5),
        .DIVCLK_DIVIDE(1),
        .CLKOUT0_DIVIDE(10)
    ) u_pll (
        .CLKIN1(clk_200m_ibuf),
        .CLKFBIN(clkfb_bufg),
        .RST(1'b0),
        .PWRDWN(1'b0),
        .CLKFBOUT(clkfb_pll),
        .CLKOUT0(clk_100m_pll),
        .CLKOUT1(),
        .CLKOUT2(),
        .CLKOUT3(),
        .CLKOUT4(),
        .CLKOUT5(),
        .LOCKED(pll_locked)
    );

    BUFG u_bufg_fb (
        .I(clkfb_pll),
        .O(clkfb_bufg)
    );

    BUFG u_bufg_core (
        .I(clk_100m_pll),
        .O(clk_core)
    );

    min8_core #(
        .LATCH_OPCODE(CORE_LATCH_OPCODE)
    ) u_core (
        .clk(clk_core),
        .rst(core_rst),
        .imem_addr(imem_addr),
        .imem_en(imem_en),
        .imem_rdata(imem_rdata),
        .dmem_addr(dmem_addr),
        .dmem_en(dmem_en),
        .dmem_we(dmem_we),
        .dmem_wdata(dmem_wdata),
        .dmem_rdata(dmem_rdata),
        .rx_data(8'h00),
        .rx_valid(1'b0),
        .rx_pop(rx_pop),
        .tx_data(tx_data),
        .tx_ready(second_tick),
        .tx_push(tx_push),
        .io_chan(io_chan),
        .dbg_state(),
        .dbg_pc_before(),
        .dbg_opcode(),
        .dbg_regs_flat(),
        .dbg_pc(),
        .dbg_z(),
        .dbg_c(),
        .dbg_iosel(),
        .dbg_retire(),
        .dbg_blocked(),
        .dbg_halted(),
        .dbg_illegal(),
        .dbg_mem_write_en(),
        .dbg_mem_write_addr(),
        .dbg_mem_write_data(),
        .dbg_io_valid(),
        .dbg_io_dir(),
        .dbg_io_channel(),
        .dbg_io_data(),
        .halted(),
        .illegal_instr(),
        .faulted()
    );

    min8_bram_wrap #(
        .MEM_INIT_FILE(MEM_INIT_FILE)
    ) u_mem (
        .clk(clk_core),
        .imem_en(imem_en),
        .imem_addr(imem_addr),
        .imem_rdata(imem_rdata),
        .dmem_en(dmem_en),
        .dmem_we(dmem_we),
        .dmem_addr(dmem_addr),
        .dmem_wdata(dmem_wdata),
        .dmem_rdata(dmem_rdata)
    );

    assign leds = led_latch;

    always @(posedge clk_core) begin
        if (core_rst) begin
            second_counter <= 28'd0;
            led_latch <= 8'h00;
        end else begin
            if (second_tick) begin
                second_counter <= 28'd0;
            end else begin
                second_counter <= second_counter + 28'd1;
            end

            if (tx_push && (io_chan == 8'h00)) begin
                led_latch <= tx_data;
            end
        end
    end

    always @(posedge clk_core) begin
        if (!pll_locked) begin
            por_count <= 5'd0;
            core_rst <= 1'b1;
        end else if (por_count < POWER_ON_RESET_CYCLES - 1) begin
            por_count <= por_count + 5'd1;
            core_rst <= 1'b1;
        end else begin
            core_rst <= 1'b0;
        end
    end
endmodule
