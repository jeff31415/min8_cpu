; Store three bytes starting at address 0x20, then halt.

    LI R3, 0x11
    LI R4, 0x22
    LI R5, 0x33
    LI R7, 0x20

    ST+ R3
    ST+ R4
    ST+ R5
    HALT
