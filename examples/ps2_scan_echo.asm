; Poll the default PS/2 device on channel 0x10.
; Ignore the device's empty-read value 0x00 and mirror received scan-code
; bytes to generic TX channel 0x03 for inspection in the GUI I/O log.

    LI R4, 0x10
    LI R5, 0x03
    LI R6, loop
    SETIO R4

loop:
    IN R3
    OR R0, R3, R3
    JZ R6
    SETIO R5
    OUT R3
    SETIO R4
    JMP R6
