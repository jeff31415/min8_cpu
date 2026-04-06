; Stream alternating 2x2 frames to the default WS2812 device on channel 0x12.
; This example assumes the GUI device is configured as width=2, height=2.
; Byte order is GRB per LED.

    SETIOI 0x12
    LI R1, 0x00
    LI R2, 0xFF
    LI R3, 0x80
    LI R6, loop

loop:
    ; Frame A: red, green, blue, white
    OUT R1
    OUT R2
    OUT R1
    OUT R2
    OUT R1
    OUT R1
    OUT R1
    OUT R1
    OUT R2
    OUT R2
    OUT R2
    OUT R2

    ; Frame B: white, blue, green, red
    OUT R2
    OUT R2
    OUT R2
    OUT R1
    OUT R1
    OUT R2
    OUT R2
    OUT R1
    OUT R1
    OUT R1
    OUT R2
    OUT R1
    JMP R6
