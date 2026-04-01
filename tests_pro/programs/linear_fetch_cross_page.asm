    SETIOI 0xFF
    LI R3, 0x01
    OUT R3
    LJMP R0, near

.org 0x00FE
near:
    LI R3, 0xAA
    HALT
