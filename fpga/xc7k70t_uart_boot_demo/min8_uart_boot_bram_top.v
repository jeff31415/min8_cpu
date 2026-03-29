`timescale 1ns/1ps

module min8_uart_boot_bram_top #(
    parameter CORE_LATCH_OPCODE = 1,
    parameter integer IO0_TICK_DIVISOR = 100_000_000,
    parameter MEM_INIT_FILE = ""
) (
    input         clk_200M_p,
    input         clk_200M_n,
    input         uart_rx,
    output        uart_tx,
    output [7:0]  leds
);
    localparam integer POWER_ON_RESET_CYCLES = 16;
    localparam integer IO0_COUNTER_WIDTH = (IO0_TICK_DIVISOR > 1) ? $clog2(IO0_TICK_DIVISOR) : 1;
    localparam [7:0] LED_CHANNEL = 8'h00;
    localparam [7:0] UART_CHANNEL = 8'h01;

    wire clk_200m_ibuf;
    wire clk_100m_pll;
    wire clkfb_pll;
    wire clkfb_bufg;
    wire clk_core;
    wire pll_locked;

    reg [4:0] por_count = 5'd0;
    reg       core_rst = 1'b1;
    reg [7:0] led_latch = 8'h00;
    reg [IO0_COUNTER_WIDTH-1:0] io0_tick_counter = {IO0_COUNTER_WIDTH{1'b0}};

    wire [7:0] imem_addr;
    wire       imem_en;
    wire [7:0] imem_rdata;
    wire [7:0] dmem_addr;
    wire       dmem_en;
    wire       dmem_we;
    wire [7:0] dmem_wdata;
    wire [7:0] dmem_rdata;

    wire [7:0] core_rx_data;
    wire       core_rx_valid;
    wire       core_rx_pop;
    wire [7:0] core_tx_data;
    wire       core_tx_ready;
    wire       core_tx_push;
    wire [7:0] io_chan;

    wire [7:0] uart_rx_data;
    wire       uart_rx_valid;

    wire [7:0] rx_fifo_dout;
    wire       rx_fifo_full;
    wire       rx_fifo_empty;
    wire       rx_fifo_push;
    wire       rx_fifo_pop;

    wire [7:0] tx_fifo_dout;
    wire       tx_fifo_full;
    wire       tx_fifo_empty;
    wire       tx_fifo_push;
    wire       tx_fifo_pop;

    wire uart_tx_valid;
    wire uart_tx_ready;
    wire io0_tick;

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

    assign io0_tick =
        (IO0_TICK_DIVISOR <= 1) ? 1'b1 :
        (io0_tick_counter == IO0_TICK_DIVISOR - 1);

    assign core_rx_valid = (io_chan == UART_CHANNEL) && !rx_fifo_empty;
    assign core_rx_data = rx_fifo_dout;
    assign core_tx_ready =
        (io_chan == LED_CHANNEL) ? io0_tick :
        (io_chan == UART_CHANNEL) ? !tx_fifo_full :
        1'b0;

    assign rx_fifo_push = uart_rx_valid && !rx_fifo_full;
    assign rx_fifo_pop = core_rx_pop && (io_chan == UART_CHANNEL) && !rx_fifo_empty;

    assign tx_fifo_push = core_tx_push && (io_chan == UART_CHANNEL) && !tx_fifo_full;
    assign uart_tx_valid = !tx_fifo_empty;
    assign tx_fifo_pop = uart_tx_ready && uart_tx_valid;

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
        .rx_data(core_rx_data),
        .rx_valid(core_rx_valid),
        .rx_pop(core_rx_pop),
        .tx_data(core_tx_data),
        .tx_ready(core_tx_ready),
        .tx_push(core_tx_push),
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

    min8_uart_rx #(
        .CLK_FREQ_HZ(100_000_000),
        .BAUD_RATE(115_200)
    ) u_uart_rx (
        .clk(clk_core),
        .rst(core_rst),
        .rxd(uart_rx),
        .data_out(uart_rx_data),
        .valid(uart_rx_valid)
    );

    min8_sync_fifo #(
        .WIDTH(8),
        .DEPTH(4),
        .ADDR_WIDTH(2)
    ) u_rx_fifo (
        .clk(clk_core),
        .rst(core_rst),
        .push(rx_fifo_push),
        .din(uart_rx_data),
        .pop(rx_fifo_pop),
        .dout(rx_fifo_dout),
        .full(rx_fifo_full),
        .empty(rx_fifo_empty),
        .level()
    );

    min8_sync_fifo #(
        .WIDTH(8),
        .DEPTH(4),
        .ADDR_WIDTH(2)
    ) u_tx_fifo (
        .clk(clk_core),
        .rst(core_rst),
        .push(tx_fifo_push),
        .din(core_tx_data),
        .pop(tx_fifo_pop),
        .dout(tx_fifo_dout),
        .full(tx_fifo_full),
        .empty(tx_fifo_empty),
        .level()
    );

    min8_uart_tx #(
        .CLK_FREQ_HZ(100_000_000),
        .BAUD_RATE(115_200)
    ) u_uart_tx (
        .clk(clk_core),
        .rst(core_rst),
        .data_in(tx_fifo_dout),
        .valid(uart_tx_valid),
        .ready(uart_tx_ready),
        .txd(uart_tx)
    );

    assign leds = led_latch;

    always @(posedge clk_core) begin
        if (core_rst) begin
            led_latch <= 8'h00;
            io0_tick_counter <= {IO0_COUNTER_WIDTH{1'b0}};
        end else if (core_tx_push && (io_chan == LED_CHANNEL)) begin
            led_latch <= core_tx_data;
            if (IO0_TICK_DIVISOR > 1) begin
                io0_tick_counter <= {IO0_COUNTER_WIDTH{1'b0}};
            end
        end else if (IO0_TICK_DIVISOR > 1) begin
            if (io0_tick) begin
                io0_tick_counter <= {IO0_COUNTER_WIDTH{1'b0}};
            end else begin
                io0_tick_counter <= io0_tick_counter + 1'b1;
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
