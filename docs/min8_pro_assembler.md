# Min8-Pro Assembler Specification

This document describes the current assembly language accepted by
`min8_pro.asm`.

Important distinction:

- an **alias** maps to one encoded opcode
- a **pseudo-instruction** expands into multiple opcodes

The current implementation matches this document.

## 1. Output Model

- output image size: `65536` bytes
- address space: `0x0000..0xFFFF`
- unspecified bytes are emitted as `0x00`
- `.bin` output writes the full 64K image
- `.memh` output writes one byte per line for the full 64K image

## 2. Source Form

- instruction mnemonics are case-insensitive
- register names are case-insensitive
- labels use the same syntax as Min8:
  - `[A-Za-z_.$][A-Za-z0-9_.$]*:`
- comments start with `;`
- multiple labels may prefix one line

## 3. True Alias

### `NOP`

Source form:

```asm
NOP
```

Expansion:

```asm
MOV R0, R0
```

Encoding:

- `0x00`

## 4. Direct ISA Mnemonics

The assembler accepts all directly encodable Min8-Pro ISA mnemonics:

- `MOV Rd, Rs`
- `ST Rr`
- `LD Rr`
- `JMP Rr`
- `JZ Rr`
- `JC Rr`
- `JNZ Rr`
- `ST+ Rr`
- `LD+ Rr`
- `HALT`
- `LDI_L_R0 imm4`
- `LDI_H_R0 imm4`
- `LDI_L_R7 imm4`
- `LDI_H_R7 imm4`
- ALU ops with implicit operands:
  - `ADD`
  - `SUB`
  - `AND`
  - `OR`
  - `XOR`
  - `NOT`
  - `SHL`
  - `SHR`
  - `INC`
  - `DEC`
  - `SHR2`
  - `SHR3`
  - `SHL2`
  - `SHL3`
  - `BSET`
  - `BCLR`
  - `BTGL`
  - `BTST`
  - `MASK3`
  - `MASK4`
  - `ADC`
  - `SBB`
- selector ops:
  - `R0L`
  - `R0H`
  - `R7L`
  - `R7H`
- I/O ops:
  - `SETIO Rs`
  - `GETIO Rd`
  - `IN Rd`
  - `OUT Rs`

Assembler rejection rules:

- `LD+ R7` is rejected because `0x7F` remains `HALT`
- reserved opcodes are never emitted

## 5. Pseudo-Instructions

## 5.1 `LI Rd, imm8`

Purpose:

- load an 8-bit immediate into any register

Accepted operands:

- `Rd` may be any `R0..R7`
- `imm8` may be a byte-valued expression or symbol

Expansion rules:

- `LI R0, imm8`:

```asm
LDI_L_R0 low4
LDI_H_R0 high4
```

- if `imm8 < 0x10`:

```asm
LDI_L_R0 imm4
```

- `LI R7, imm8`:

```asm
LDI_L_R7 low4
LDI_H_R7 high4
```

- if `imm8 < 0x10`:

```asm
LDI_L_R7 imm4
```

- `LI Rd, imm8` for `R1..R6`:

```asm
LDI_L_R0 low4
LDI_H_R0 high4
MOV Rd, R0
```

- if `imm8 < 0x10`:

```asm
LDI_L_R0 imm4
MOV Rd, R0
```

Notes:

- `LI` is byte-only; 16-bit immediates require `LI16`
- for `R1..R6`, `LI` uses `R0` as an internal temporary
- labels after `LI` resolve after the expanded sequence

## 5.2 `LI16 Rd, imm16`

Purpose:

- load a full 16-bit immediate into `R0` or `R7`

Accepted operands:

- `Rd` must be `R0` or `R7`
- `imm16` may be any 16-bit expression or symbol

Expansion model:

For `LI16 R0, 0x1234`:

```asm
R0L
LDI_L_R0 0x4
LDI_H_R0 0x3
R0H
LDI_L_R0 0x2
LDI_H_R0 0x1
R0L
```

For `LI16 R7, 0x1234`:

```asm
R7L
LDI_L_R7 0x4
LDI_H_R7 0x3
R7H
LDI_L_R7 0x2
LDI_H_R7 0x1
R7L
```

Properties:

- fixed size: `7` instructions
- selector is restored to low byte afterward
- no size optimization is currently performed
- `LI16 R1..R6` is rejected

## 5.3 `LJMP scratch, imm16`

Purpose:

- perform an explicit long jump through a specified wide register

Accepted operands:

- `scratch` must be `R0` or `R7`
- `imm16` may be any 16-bit expression or symbol

Expansion:

```asm
LI16 scratch, imm16
JMP scratch
```

Properties:

- fixed size: `8` instructions
- explicit `scratch` is clobbered
- no automatic conversion from `JMP` to `LJMP` exists

## 5.4 `LJZ scratch, imm16`

Expansion:

```asm
LI16 scratch, imm16
JZ scratch
```

Properties:

- fixed size: `8` instructions
- explicit `scratch` is clobbered whether or not the branch is taken

## 5.5 `LJC scratch, imm16`

Expansion:

```asm
LI16 scratch, imm16
JC scratch
```

Properties:

- fixed size: `8` instructions
- explicit `scratch` is clobbered whether or not the branch is taken

## 5.6 `LJNZ scratch, imm16`

Expansion:

```asm
LI16 scratch, imm16
JNZ scratch
```

Properties:

- fixed size: `8` instructions
- explicit `scratch` is clobbered whether or not the branch is taken

## 5.7 `SETIOI imm8`

Purpose:

- load an immediate byte into `IOSEL`

Expansion:

```asm
LDI_L_R0 low4
LDI_H_R0 high4
SETIO R0
```

- if `imm8 < 0x10`:

```asm
LDI_L_R0 imm4
SETIO R0
```

Notes:

- expands to `2` instructions for small immediates
- expands to `3` instructions otherwise
- uses `R0` as a temporary

## 5.8 Explicit-Register ALU Pseudo-Forms

Supported binary source forms:

```asm
ADD   Rd, Ra, Rb
SUB   Rd, Ra, Rb
AND   Rd, Ra, Rb
OR    Rd, Ra, Rb
XOR   Rd, Ra, Rb
BSET  Rd, Ra, Rb
BCLR  Rd, Ra, Rb
BTGL  Rd, Ra, Rb
BTST  Rd, Ra, Rb
ADC   Rd, Ra, Rb
SBB   Rd, Ra, Rb
```

Supported unary source forms:

```asm
NOT   Rd, Rs
SHL   Rd, Rs
SHR   Rd, Rs
INC   Rd, Rs
DEC   Rd, Rs
SHR2  Rd, Rs
SHR3  Rd, Rs
SHL2  Rd, Rs
SHL3  Rd, Rs
MASK3 Rd, Rs
MASK4 Rd, Rs
```

Expansion model:

```asm
MOV R1, Ra   ; omitted if Ra is already R1
MOV R2, Rb   ; omitted if Rb is already R2
ALU_OP
MOV Rd, R0   ; omitted if Rd is already R0
```

```asm
MOV R1, Rs   ; omitted if Rs is already R1
ALU_OP
MOV Rd, R0   ; omitted if Rd is already R0
```

Properties:

- original implicit forms still work
- redundant setup and writeback moves are elided
- commutative ops may swap inputs to save moves
- when a non-commutative binary op needs `R1` and `R2` swapped, `R0` is used as a temporary

## 6. Directives

The current directive set is:

- `.org addr`
- `.byte expr [, expr ...]`
- `.fill count [, value]`
- `.equ name, expr`

Directive rules:

- `.org` accepts a 16-bit address
- `.byte` values must fit in 8 bits
- `.fill` count must be non-negative
- `.fill` default fill byte is `0`
- `.equ` values must fit in 16 bits
- labels may not share a line with `.equ`

## 7. Expressions

Accepted expression forms:

- integer literals:
  - decimal: `10`
  - hex: `0x20`
  - binary: `0b1010`
- character literals:
  - `'A'`
- symbol references
- unary operators:
  - `+`
  - `-`
  - `~`
- binary operators:
  - `+`
  - `-`
  - `*`
  - `//`
  - `%`
  - `<<`
  - `>>`
  - `&`
  - `|`
  - `^`

Expression width checks depend on use site:

- nibble operands must fit `0x0..0xF`
- byte operands must fit `0x00..0xFF`
- addresses and `imm16` operands must fit `0x0000..0xFFFF`

## 8. Addressing and Layout Rules

- the assembler performs iterative symbol layout until instruction sizes stabilize
- because jump width is explicit, there is no short/long jump optimization pass
- overlapping writes are rejected
- writing beyond `0xFFFF` is rejected

## 9. Things The Assembler Does Not Currently Do

- no auto-promotion from short jump to long jump
- no `LI16` support for `R1..R6`
- no immediate ALU shortcuts such as `ADD R3, #1`
- no addressing sugar such as `LD R4, [R7+]`
- no macros beyond the pseudo-instructions listed above
