; Min8 LED demo for the xc7k70t board.
; Output Fibonacci values on I/O channel 0 forever.
;
; The FPGA top-level exposes channel 0 on the 8 user LEDs and only
; asserts tx_ready once per second, so the CPU naturally blocks on OUT
; and advances the sequence at 1 Hz.

    SETIOI 0x00
    LI R3, 0x01
    LI R4, 0x01
    LI R6, loop

loop:
    OUT R3
    MOV R1, R3
    MOV R2, R4
    ADD
    MOV R5, R4
    MOV R4, R0
    MOV R3, R5
    JMP R6
