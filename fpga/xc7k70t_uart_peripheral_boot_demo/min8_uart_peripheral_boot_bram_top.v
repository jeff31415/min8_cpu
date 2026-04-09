`timescale 1ns/1ps

module min8_uart_peripheral_boot_bram_top #(
    parameter CORE_LATCH_OPCODE = 1,
    parameter integer CLKIN_HZ = 200_000_000,
    parameter integer PLL_CLKFBOUT_MULT = 27,
    parameter integer PLL_DIVCLK_DIVIDE = 5,
    parameter integer PLL_CLKOUT0_DIVIDE = 6,
    parameter integer IO0_TICK_DIVISOR =
        ((64'd1 * CLKIN_HZ * PLL_CLKFBOUT_MULT) /
         (PLL_DIVCLK_DIVIDE * PLL_CLKOUT0_DIVIDE)),
    parameter integer AUDIO_SAMPLE_RATE_HZ = 16_000,
    parameter integer AUDIO_MOD_HZ = 10_000_000,
    parameter MEM_INIT_FILE = ""
) (
    input         clk_200M_p,
    input         clk_200M_n,
    input         uart_rx,
    output        uart_tx,
    input         ps2_clk,
    input         ps2_data,
    output        ws2812_out,
    output        audio_dsm_out,
    output [7:0]  leds
);
    localparam integer POWER_ON_RESET_CYCLES = 16;
    localparam real CLKIN_PERIOD_NS = 1.0e9 / CLKIN_HZ;
    localparam integer CORE_CLK_HZ =
        ((64'd1 * CLKIN_HZ * PLL_CLKFBOUT_MULT) /
         (PLL_DIVCLK_DIVIDE * PLL_CLKOUT0_DIVIDE));
    localparam integer IO0_COUNTER_WIDTH = (IO0_TICK_DIVISOR > 1) ? $clog2(IO0_TICK_DIVISOR) : 1;
    localparam integer AUDIO_SAMPLE_TICK_DIVISOR =
        (AUDIO_SAMPLE_RATE_HZ <= 0) ? 1 :
        ((64'd1 * CORE_CLK_HZ + (AUDIO_SAMPLE_RATE_HZ / 2)) / AUDIO_SAMPLE_RATE_HZ);
    localparam integer AUDIO_MOD_TICK_DIVISOR =
        (AUDIO_MOD_HZ <= 0) ? 1 :
        ((64'd1 * CORE_CLK_HZ + (AUDIO_MOD_HZ / 2)) / AUDIO_MOD_HZ);
    localparam integer WS2812_T0H_CYCLES =
        (((64'd1 * CORE_CLK_HZ * 400) + 500_000_000) / 1_000_000_000);
    localparam integer WS2812_T0L_CYCLES =
        (((64'd1 * CORE_CLK_HZ * 850) + 500_000_000) / 1_000_000_000);
    localparam integer WS2812_T1H_CYCLES =
        (((64'd1 * CORE_CLK_HZ * 800) + 500_000_000) / 1_000_000_000);
    localparam integer WS2812_T1L_CYCLES =
        (((64'd1 * CORE_CLK_HZ * 450) + 500_000_000) / 1_000_000_000);
    localparam integer WS2812_RESET_CYCLES =
        (((64'd1 * CORE_CLK_HZ * 60_000) + 500_000_000) / 1_000_000_000);
    localparam [7:0] LED_CHANNEL = 8'h00;

    wire clk_200m_ibuf;
    wire clk_pll_out;
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

    wire [7:0] peripheral_rx_data;
    wire       peripheral_rx_valid;
    wire       peripheral_rx_pop;
    wire       peripheral_tx_ready;
    wire [7:0] peripheral_tx_data;
    wire       peripheral_tx_push;

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

    wire [7:0] dbg_ps2_rx_level;
    wire [7:0] dbg_ps2_cmd_level;
    wire [15:0] dbg_ps2_dropped_count;
    wire [15:0] dbg_ps2_frame_error_count;
    wire [7:0] dbg_audio_fifo_level;
    wire [7:0] dbg_audio_current_sample;
    wire [15:0] dbg_audio_underflow_count;
    wire [7:0] dbg_ws2812_fifo_level;
    wire       dbg_ws2812_busy;
    wire [7:0] dbg_ws2812_frame_byte_count;
    wire [7:0] dbg_filo_level;
    wire       dbg_filo_empty;
    wire       dbg_filo_full;
    wire [7:0] dbg_filo_top;

    IBUFGDS u_ibufg_sys_clk (
        .I(clk_200M_p),
        .IB(clk_200M_n),
        .O(clk_200m_ibuf)
    );

    PLLE2_BASE #(
        .CLKIN1_PERIOD(CLKIN_PERIOD_NS),
        .CLKFBOUT_MULT(PLL_CLKFBOUT_MULT),
        .DIVCLK_DIVIDE(PLL_DIVCLK_DIVIDE),
        .CLKOUT0_DIVIDE(PLL_CLKOUT0_DIVIDE)
    ) u_pll (
        .CLKIN1(clk_200m_ibuf),
        .CLKFBIN(clkfb_bufg),
        .RST(1'b0),
        .PWRDWN(1'b0),
        .CLKFBOUT(clkfb_pll),
        .CLKOUT0(clk_pll_out),
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
        .I(clk_pll_out),
        .O(clk_core)
    );

    assign io0_tick =
        (IO0_TICK_DIVISOR <= 1) ? 1'b1 :
        (io0_tick_counter == IO0_TICK_DIVISOR - 1);

    assign core_rx_valid = (io_chan == LED_CHANNEL) ? 1'b0 : peripheral_rx_valid;
    assign core_rx_data = peripheral_rx_data;
    assign core_tx_ready =
        (io_chan == LED_CHANNEL) ? io0_tick :
        peripheral_tx_ready;

    assign rx_fifo_push = uart_rx_valid && !rx_fifo_full;
    assign rx_fifo_pop = peripheral_rx_pop && !rx_fifo_empty;

    assign tx_fifo_push = peripheral_tx_push && !tx_fifo_full;
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

    min8_io_peripheral_chain #(
        .AUDIO_SAMPLE_TICK_DIVISOR((AUDIO_SAMPLE_TICK_DIVISOR < 1) ? 1 : AUDIO_SAMPLE_TICK_DIVISOR),
        .AUDIO_MOD_TICK_DIVISOR((AUDIO_MOD_TICK_DIVISOR < 1) ? 1 : AUDIO_MOD_TICK_DIVISOR),
        .WS2812_T0H_CYCLES((WS2812_T0H_CYCLES < 1) ? 1 : WS2812_T0H_CYCLES),
        .WS2812_T0L_CYCLES((WS2812_T0L_CYCLES < 1) ? 1 : WS2812_T0L_CYCLES),
        .WS2812_T1H_CYCLES((WS2812_T1H_CYCLES < 1) ? 1 : WS2812_T1H_CYCLES),
        .WS2812_T1L_CYCLES((WS2812_T1L_CYCLES < 1) ? 1 : WS2812_T1L_CYCLES),
        .WS2812_RESET_CYCLES((WS2812_RESET_CYCLES < 1) ? 1 : WS2812_RESET_CYCLES)
    ) u_io (
        .clk(clk_core),
        .rst(core_rst),
        .io_chan(io_chan),
        .ext_rx_data_in(rx_fifo_dout),
        .ext_rx_valid_in(!rx_fifo_empty),
        .ext_rx_pop_out(peripheral_rx_pop),
        .ext_tx_ready_in(!tx_fifo_full),
        .ext_tx_data_out(peripheral_tx_data),
        .ext_tx_push_out(peripheral_tx_push),
        .core_rx_data_out(peripheral_rx_data),
        .core_rx_valid_out(peripheral_rx_valid),
        .core_rx_pop_in(core_rx_pop && (io_chan != LED_CHANNEL)),
        .core_tx_ready_out(peripheral_tx_ready),
        .core_tx_data_in(core_tx_data),
        .core_tx_push_in(core_tx_push && (io_chan != LED_CHANNEL)),
        .ps2_clk_in(ps2_clk),
        .ps2_data_in(ps2_data),
        .audio_dsm_out(audio_dsm_out),
        .ws2812_out(ws2812_out),
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

    min8_uart_rx #(
        .CLK_FREQ_HZ(CORE_CLK_HZ),
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
        .din(peripheral_tx_data),
        .pop(tx_fifo_pop),
        .dout(tx_fifo_dout),
        .full(tx_fifo_full),
        .empty(tx_fifo_empty),
        .level()
    );

    min8_uart_tx #(
        .CLK_FREQ_HZ(CORE_CLK_HZ),
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

    /* verilator lint_off UNUSEDSIGNAL */
    wire _unused_ok = &{
        1'b0,
        dbg_ps2_rx_level,
        dbg_ps2_cmd_level,
        dbg_ps2_dropped_count,
        dbg_ps2_frame_error_count,
        dbg_audio_fifo_level,
        dbg_audio_current_sample,
        dbg_audio_underflow_count,
        dbg_ws2812_fifo_level,
        dbg_ws2812_busy,
        dbg_ws2812_frame_byte_count,
        dbg_filo_level,
        dbg_filo_empty,
        dbg_filo_full,
        dbg_filo_top,
        rx_fifo_full
    };
    /* verilator lint_on UNUSEDSIGNAL */

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
