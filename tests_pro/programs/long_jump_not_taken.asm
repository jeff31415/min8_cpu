    SETIOI 0xFF
    LI R3, 0x01
    OUT R3

    LI R1, 0x01
    LI R2, 0x00
    ADD
    LJZ R0, target
    R0H
    MOV R4, R0
    R0L
    MOV R6, R0
    LI R5, 0x11
    HALT

.org 0x0120
target:
    R0H
    MOV R4, R0
    R0L
    MOV R6, R0
    LI R5, 0x5A
    HALT
