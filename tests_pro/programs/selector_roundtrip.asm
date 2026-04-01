    SETIOI 0xFF
    LI R3, 0x01
    OUT R3
    LI16 R0, 0x1234
    R0H
    MOV R3, R0
    R0L
    MOV R4, R0
    HALT
