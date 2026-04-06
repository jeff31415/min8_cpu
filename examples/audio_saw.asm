; Drive the default audio device on channel 0x11 with a simple sawtooth.
; The audio backend consumes 8-bit unsigned samples at 16 kHz.

    SETIOI 0x11
    LI R3, 0x80
    LI R4, 0x03
    LI R6, loop

loop:
    OUT R3
    ADD R3, R3, R4
    JMP R6
