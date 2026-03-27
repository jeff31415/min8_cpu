`timescale 1ns/1ps

module min8_alu (
    input  [4:0] op,
    input  [7:0] a,
    input  [7:0] b,
    input        cin,
    output reg [7:0] y,
    output reg       cout,
    output reg       illegal
);
    reg [8:0] add_ext;
    reg [8:0] sub_ext;
    reg [7:0] bit_mask;

    always @* begin
        y = 8'h00;
        cout = 1'b0;
        illegal = 1'b0;
        add_ext = 9'h000;
        sub_ext = 9'h000;
        bit_mask = (8'h01 << b[2:0]);

        case (op)
            5'h00: begin
                add_ext = {1'b0, a} + {1'b0, b};
                y = add_ext[7:0];
                cout = add_ext[8];
            end
            5'h01: begin
                y = a - b;
                cout = ({1'b0, a} < {1'b0, b});
            end
            5'h02: begin
                y = a & b;
            end
            5'h03: begin
                y = a | b;
            end
            5'h04: begin
                y = a ^ b;
            end
            5'h05: begin
                y = ~a;
            end
            5'h06: begin
                y = a << 1;
                cout = a[7];
            end
            5'h07: begin
                y = a >> 1;
                cout = a[0];
            end
            5'h08: begin
                add_ext = {1'b0, a} + 9'h001;
                y = add_ext[7:0];
                cout = add_ext[8];
            end
            5'h09: begin
                y = a - 8'h01;
                cout = (a == 8'h00);
            end
            5'h0A: begin
                y = a >> 2;
                cout = a[1];
            end
            5'h0B: begin
                y = a >> 3;
                cout = a[2];
            end
            5'h0C: begin
                y = a << 2;
                cout = a[6];
            end
            5'h0D: begin
                y = a << 3;
                cout = a[5];
            end
            5'h0E: begin
                y = a | bit_mask;
            end
            5'h0F: begin
                y = a & ~bit_mask;
            end
            5'h10: begin
                y = a ^ bit_mask;
            end
            5'h11: begin
                y = a & bit_mask;
            end
            5'h12: begin
                y = a & 8'h07;
            end
            5'h13: begin
                y = a & 8'h0F;
            end
            5'h14: begin
                add_ext = {1'b0, a} + {1'b0, b} + {8'h00, cin};
                y = add_ext[7:0];
                cout = add_ext[8];
            end
            5'h15: begin
                sub_ext = {1'b0, b} + {8'h00, cin};
                y = a - sub_ext[7:0];
                cout = ({1'b0, a} < sub_ext);
            end
            default: begin
                illegal = 1'b1;
            end
        endcase
    end
endmodule
