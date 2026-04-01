    SETIOI 0xFF
    LI R3, 0x01
    OUT R3
    LI16 R7, target
    LI R3, 0x7F
    ST R3
    LJMP R0, target

.org 0x0120
target:
    .byte 0x00
