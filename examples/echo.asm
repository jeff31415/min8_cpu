; Echo bytes on channel 3 forever.

    LI R4, loop
    SETIOI 0x03

loop:
    IN R3
    OUT R3
    JMP R4
