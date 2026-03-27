`timescale 1ns/1ps

module min8_core #(
    parameter LATCH_OPCODE = 1'b1
) (
    input        clk,
    input        rst,
    output [7:0] imem_addr,
    output       imem_en,
    input  [7:0] imem_rdata,
    output [7:0] dmem_addr,
    output       dmem_en,
    output       dmem_we,
    output [7:0] dmem_wdata,
    input  [7:0] dmem_rdata,
    input  [7:0] rx_data,
    input        rx_valid,
    output       rx_pop,
    output [7:0] tx_data,
    input        tx_ready,
    output       tx_push,
    output [7:0] io_chan,
    output [2:0] dbg_state,
    output [7:0] dbg_pc_before,
    output [7:0] dbg_opcode,
    output [63:0] dbg_regs_flat,
    output [7:0] dbg_pc,
    output       dbg_z,
    output       dbg_c,
    output [7:0] dbg_iosel,
    output reg   dbg_retire,
    output reg   dbg_blocked,
    output reg   dbg_halted,
    output reg   dbg_illegal,
    output reg   dbg_mem_write_en,
    output reg [7:0] dbg_mem_write_addr,
    output reg [7:0] dbg_mem_write_data,
    output reg   dbg_io_valid,
    output reg   dbg_io_dir,
    output reg [7:0] dbg_io_channel,
    output reg [7:0] dbg_io_data,
    output reg   halted,
    output reg   illegal_instr,
    output reg   faulted
);
    localparam S_FETCH  = 3'd0;
    localparam S_EXEC   = 3'd1;
    localparam S_MEM    = 3'd2;
    localparam S_IOWAIT = 3'd3;
    localparam S_HALT   = 3'd4;
    localparam S_FAULT  = 3'd5;

    reg [2:0] state;
    reg [7:0] pc;
    reg [7:0] opcode_q;
    reg [7:0] pc_before_q;
    reg       z;
    reg       c;
    reg [7:0] iosel;

    reg [7:0] mem_addr_q;
    reg [7:0] mem_wdata_q;
    reg [2:0] mem_dst_q;
    reg       mem_is_load_q;
    reg       mem_postinc_q;

    reg       io_is_in_q;
    reg [2:0] io_dst_q;
    reg [7:0] io_tx_data_q;

    wire [7:0] opcode = imem_rdata;

    wire [2:0] mov_dst = opcode[5:3];
    wire [2:0] reg_rrr = opcode[2:0];
    wire [4:0] alu_subop = opcode[4:0];
    wire       ldi_h = opcode[5];
    wire       ldi_t = opcode[4];
    wire [3:0] imm4 = opcode[3:0];
    wire [2:0] memctrl_op = opcode[5:3];
    wire [1:0] io_class = opcode[4:3];

    wire is_halt = (opcode == 8'h7F);
    wire is_mov = (opcode[7:6] == 2'b00);
    wire is_memctrl = (opcode[7:6] == 2'b01) && !is_halt;
    wire is_ldi = (opcode[7:6] == 2'b10);
    wire is_alu = (opcode[7:5] == 3'b110);
    wire is_io = (opcode[7:5] == 3'b111);

    wire is_st = is_memctrl && (memctrl_op == 3'b000);
    wire is_ld = is_memctrl && (memctrl_op == 3'b001);
    wire is_jmp = is_memctrl && (memctrl_op == 3'b010);
    wire is_jz = is_memctrl && (memctrl_op == 3'b011);
    wire is_jc = is_memctrl && (memctrl_op == 3'b100);
    wire is_jnz = is_memctrl && (memctrl_op == 3'b101);
    wire is_stp = is_memctrl && (memctrl_op == 3'b110);
    wire is_ldp = is_memctrl && (memctrl_op == 3'b111);

    wire is_setio = is_io && (io_class == 2'b00);
    wire is_getio = is_io && (io_class == 2'b01);
    wire is_in = is_io && (io_class == 2'b10);
    wire is_out = is_io && (io_class == 2'b11);

    wire [7:0] rdata_r1;
    wire [7:0] rdata_r2;
    wire [7:0] rdata_src;
    wire [7:0] rdata_r7;
    wire [63:0] regs_flat;
    wire [3:0] rdata_r0_low = regs_flat[3:0];

    wire [3:0] ldi_old_low = ldi_t ? rdata_r7[3:0] : rdata_r0_low;
    wire [7:0] ldi_result = ldi_h ? {imm4, ldi_old_low} : {4'h0, imm4};

    wire [7:0] alu_y;
    wire       alu_cout;
    wire       alu_illegal;

    wire in_fire_exec = (state == S_EXEC) && is_in && rx_valid;
    wire out_fire_exec = (state == S_EXEC) && is_out && tx_ready;
    wire in_fire_wait = (state == S_IOWAIT) && io_is_in_q && rx_valid;
    wire out_fire_wait = (state == S_IOWAIT) && !io_is_in_q && tx_ready;

    wire reg_we1 =
        ((state == S_EXEC) && is_mov) ||
        ((state == S_EXEC) && is_ldi) ||
        ((state == S_EXEC) && is_alu && !alu_illegal) ||
        ((state == S_EXEC) && is_getio) ||
        in_fire_exec ||
        ((state == S_MEM) && mem_is_load_q) ||
        in_fire_wait;

    wire [2:0] reg_waddr1 =
        ((state == S_EXEC) && is_mov) ? mov_dst :
        ((state == S_EXEC) && is_ldi) ? (ldi_t ? 3'b111 : 3'b000) :
        ((state == S_EXEC) && is_alu) ? 3'b000 :
        ((state == S_EXEC) && is_getio) ? reg_rrr :
        in_fire_exec ? reg_rrr :
        ((state == S_MEM) && mem_is_load_q) ? mem_dst_q :
        in_fire_wait ? io_dst_q :
        3'b000;

    wire [7:0] reg_wdata1 =
        ((state == S_EXEC) && is_mov) ? rdata_src :
        ((state == S_EXEC) && is_ldi) ? ldi_result :
        ((state == S_EXEC) && is_alu) ? alu_y :
        ((state == S_EXEC) && is_getio) ? iosel :
        in_fire_exec ? rx_data :
        ((state == S_MEM) && mem_is_load_q) ? dmem_rdata :
        in_fire_wait ? rx_data :
        8'h00;

    wire reg_we2 = (state == S_MEM) && mem_postinc_q;
    wire [2:0] reg_waddr2 = 3'b111;
    wire [7:0] reg_wdata2 = mem_addr_q + 8'h01;

    assign imem_en = (state == S_FETCH);
    assign imem_addr = pc;

    assign dmem_en =
        ((state == S_EXEC) && (is_ld || is_ldp)) ||
        ((state == S_MEM) && !mem_is_load_q);
    assign dmem_we = (state == S_MEM) && !mem_is_load_q;
    assign dmem_addr = ((state == S_EXEC) && (is_ld || is_ldp)) ? rdata_r7 : mem_addr_q;
    assign dmem_wdata = mem_wdata_q;

    assign rx_pop = in_fire_exec || in_fire_wait;
    assign tx_push = out_fire_exec || out_fire_wait;
    assign tx_data = (state == S_IOWAIT) ? io_tx_data_q : rdata_src;
    assign io_chan = iosel;

    assign dbg_state = state;
    assign dbg_pc_before = pc_before_q;
    assign dbg_opcode = LATCH_OPCODE ? opcode_q : opcode;
    assign dbg_regs_flat = regs_flat;
    assign dbg_pc = pc;
    assign dbg_z = z;
    assign dbg_c = c;
    assign dbg_iosel = iosel;

    min8_regfile u_regfile (
        .clk(clk),
        .rst(rst),
        .src_addr(reg_rrr),
        .rdata_r1(rdata_r1),
        .rdata_r2(rdata_r2),
        .rdata_src(rdata_src),
        .rdata_r7(rdata_r7),
        .regs_flat(regs_flat),
        .we1(reg_we1),
        .waddr1(reg_waddr1),
        .wdata1(reg_wdata1),
        .we2(reg_we2),
        .waddr2(reg_waddr2),
        .wdata2(reg_wdata2)
    );

    min8_alu u_alu (
        .op(alu_subop),
        .a(rdata_r1),
        .b(rdata_r2),
        .cin(c),
        .y(alu_y),
        .cout(alu_cout),
        .illegal(alu_illegal)
    );

    always @(posedge clk) begin
        if (rst) begin
            state <= S_FETCH;
            pc <= 8'h00;
            opcode_q <= 8'h00;
            pc_before_q <= 8'h00;
            z <= 1'b0;
            c <= 1'b0;
            iosel <= 8'h00;
            mem_addr_q <= 8'h00;
            mem_wdata_q <= 8'h00;
            mem_dst_q <= 3'b000;
            mem_is_load_q <= 1'b0;
            mem_postinc_q <= 1'b0;
            io_is_in_q <= 1'b0;
            io_dst_q <= 3'b000;
            io_tx_data_q <= 8'h00;
            dbg_retire <= 1'b0;
            dbg_blocked <= 1'b0;
            dbg_halted <= 1'b0;
            dbg_illegal <= 1'b0;
            dbg_mem_write_en <= 1'b0;
            dbg_mem_write_addr <= 8'h00;
            dbg_mem_write_data <= 8'h00;
            dbg_io_valid <= 1'b0;
            dbg_io_dir <= 1'b0;
            dbg_io_channel <= 8'h00;
            dbg_io_data <= 8'h00;
            halted <= 1'b0;
            illegal_instr <= 1'b0;
            faulted <= 1'b0;
        end else begin
            dbg_retire <= 1'b0;
            dbg_blocked <= 1'b0;
            dbg_halted <= 1'b0;
            dbg_illegal <= 1'b0;
            dbg_mem_write_en <= 1'b0;
            dbg_io_valid <= 1'b0;

            case (state)
                S_FETCH: begin
                    pc_before_q <= pc;
                    pc <= pc + 8'h01;
                    state <= S_EXEC;
                end

                S_EXEC: begin
                    if (LATCH_OPCODE) begin
                        opcode_q <= opcode;
                    end
                    if (is_mov) begin
                        dbg_retire <= 1'b1;
                        state <= S_FETCH;
                    end else if (is_ldi) begin
                        dbg_retire <= 1'b1;
                        state <= S_FETCH;
                    end else if (is_alu) begin
                        if (alu_illegal) begin
                            halted <= 1'b1;
                            illegal_instr <= 1'b1;
                            faulted <= 1'b1;
                            dbg_illegal <= 1'b1;
                            state <= S_FAULT;
                        end else begin
                            z <= (alu_y == 8'h00);
                            c <= alu_cout;
                            dbg_retire <= 1'b1;
                            state <= S_FETCH;
                        end
                    end else if (is_st) begin
                        mem_addr_q <= rdata_r7;
                        mem_wdata_q <= rdata_src;
                        mem_is_load_q <= 1'b0;
                        mem_postinc_q <= 1'b0;
                        state <= S_MEM;
                    end else if (is_ld) begin
                        mem_addr_q <= rdata_r7;
                        mem_dst_q <= reg_rrr;
                        mem_is_load_q <= 1'b1;
                        mem_postinc_q <= 1'b0;
                        state <= S_MEM;
                    end else if (is_jmp) begin
                        pc <= rdata_src;
                        dbg_retire <= 1'b1;
                        state <= S_FETCH;
                    end else if (is_jz) begin
                        if (z) begin
                            pc <= rdata_src;
                        end
                        dbg_retire <= 1'b1;
                        state <= S_FETCH;
                    end else if (is_jc) begin
                        if (c) begin
                            pc <= rdata_src;
                        end
                        dbg_retire <= 1'b1;
                        state <= S_FETCH;
                    end else if (is_jnz) begin
                        if (!z) begin
                            pc <= rdata_src;
                        end
                        dbg_retire <= 1'b1;
                        state <= S_FETCH;
                    end else if (is_stp) begin
                        mem_addr_q <= rdata_r7;
                        mem_wdata_q <= rdata_src;
                        mem_is_load_q <= 1'b0;
                        mem_postinc_q <= 1'b1;
                        state <= S_MEM;
                    end else if (is_ldp) begin
                        mem_addr_q <= rdata_r7;
                        mem_dst_q <= reg_rrr;
                        mem_is_load_q <= 1'b1;
                        mem_postinc_q <= 1'b1;
                        state <= S_MEM;
                    end else if (is_setio) begin
                        iosel <= rdata_src;
                        dbg_retire <= 1'b1;
                        state <= S_FETCH;
                    end else if (is_getio) begin
                        dbg_retire <= 1'b1;
                        state <= S_FETCH;
                    end else if (is_in) begin
                        if (rx_valid) begin
                            dbg_retire <= 1'b1;
                            dbg_io_valid <= 1'b1;
                            dbg_io_dir <= 1'b0;
                            dbg_io_channel <= iosel;
                            dbg_io_data <= rx_data;
                            state <= S_FETCH;
                        end else begin
                            io_is_in_q <= 1'b1;
                            io_dst_q <= reg_rrr;
                            dbg_blocked <= 1'b1;
                            dbg_io_dir <= 1'b0;
                            dbg_io_channel <= iosel;
                            state <= S_IOWAIT;
                        end
                    end else if (is_out) begin
                        if (tx_ready) begin
                            dbg_retire <= 1'b1;
                            dbg_io_valid <= 1'b1;
                            dbg_io_dir <= 1'b1;
                            dbg_io_channel <= iosel;
                            dbg_io_data <= rdata_src;
                            state <= S_FETCH;
                        end else begin
                            io_is_in_q <= 1'b0;
                            io_tx_data_q <= rdata_src;
                            dbg_blocked <= 1'b1;
                            dbg_io_dir <= 1'b1;
                            dbg_io_channel <= iosel;
                            dbg_io_data <= rdata_src;
                            state <= S_IOWAIT;
                        end
                    end else if (is_halt) begin
                        halted <= 1'b1;
                        dbg_halted <= 1'b1;
                        state <= S_HALT;
                    end else begin
                        halted <= 1'b1;
                        illegal_instr <= 1'b1;
                        faulted <= 1'b1;
                        dbg_illegal <= 1'b1;
                        state <= S_FAULT;
                    end
                end

                S_MEM: begin
                    dbg_retire <= 1'b1;
                    if (mem_is_load_q) begin
                        state <= S_FETCH;
                    end else begin
                        dbg_mem_write_en <= 1'b1;
                        dbg_mem_write_addr <= mem_addr_q;
                        dbg_mem_write_data <= mem_wdata_q;
                        state <= S_FETCH;
                    end
                end

                S_IOWAIT: begin
                    if (io_is_in_q) begin
                        if (rx_valid) begin
                            dbg_retire <= 1'b1;
                            dbg_io_valid <= 1'b1;
                            dbg_io_dir <= 1'b0;
                            dbg_io_channel <= iosel;
                            dbg_io_data <= rx_data;
                            state <= S_FETCH;
                        end
                    end else begin
                        if (tx_ready) begin
                            dbg_retire <= 1'b1;
                            dbg_io_valid <= 1'b1;
                            dbg_io_dir <= 1'b1;
                            dbg_io_channel <= iosel;
                            dbg_io_data <= io_tx_data_q;
                            state <= S_FETCH;
                        end
                    end
                end

                S_HALT: begin
                    state <= S_HALT;
                end

                S_FAULT: begin
                    state <= S_FAULT;
                end

                default: begin
                    halted <= 1'b1;
                    illegal_instr <= 1'b1;
                    faulted <= 1'b1;
                    dbg_illegal <= 1'b1;
                    state <= S_FAULT;
                end
            endcase
        end
    end
endmodule
