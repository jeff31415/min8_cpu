; Demonstrate the FILO stack device on channel 0x13.
; Push 0x11, 0x22, 0x33, then pop them back and emit the observed order on
; generic TX channel 0x03. Expected output is 33 22 11.

    SETIOI 0x13
    LI R1, 0x11
    LI R2, 0x22
    LI R3, 0x33

    OUT R1
    OUT R2
    OUT R3

    IN R4
    IN R5
    IN R6

    SETIOI 0x03
    OUT R4
    OUT R5
    OUT R6
    HALT
