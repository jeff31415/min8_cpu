    SETIOI 0xFF
    LI R3, 0x01
    OUT R3
    LI16 R7, 0x01FF
    LI R3, 0x11
    ST+ R3
    LI R4, 0x22
    ST+ R4
    HALT
