; Output fib

    LI R6, loop
    LI R5, halt
    SETIOI 0
    LI R3, 0
    LI R4, 1

loop:
    MOV R1, R3
    MOV R2, R4
    ADD
    MOV R3, R4
    MOV R4, R0
    OUT R3
    JC R5
    JMP R6

halt:
    HALT