# Min8 Assembler Aliases And Pseudo-Instructions

This document lists the assembly-level conveniences currently implemented by
the Min8 assembler.

Important distinction:

- an **alias** maps to one existing ISA instruction
- a **pseudo-instruction** expands into multiple ISA instructions

## 1. True alias

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

Notes:

- this is the only current one-to-one mnemonic alias

## 2. Pseudo-instructions

### `LI Rd, imm8`

Purpose:

- load an 8-bit immediate into any register

Source form:

```asm
LI R3, 0x44
LI R7, label
```

Expansion rules:

- `LI R0, imm8` expands to:

```asm
LDI_L_R0 low4
LDI_H_R0 high4
```

- if `imm8 < 0x10`, it is optimized to:

```asm
LDI_L_R0 imm4
```

- `LI R7, imm8` expands to:

```asm
LDI_L_R7 low4
LDI_H_R7 high4
```

- if `imm8 < 0x10`, it is optimized to:

```asm
LDI_L_R7 imm4
```

- `LI Rd, imm8` for `R1..R6` expands to:

```asm
LDI_L_R0 low4
LDI_H_R0 high4
MOV Rd, R0
```

- if `imm8 < 0x10`, it is optimized to:

```asm
LDI_L_R0 imm4
MOV Rd, R0
```

Notes:

- `imm8` may be a literal or a symbol expression
- because `LDI_L_*` clears the upper nibble, the assembler omits `LDI_H_*` when `imm8 < 0x10`
- this means `LI` is:
  - 1 instruction for `R0`/`R7` when `imm8 < 0x10`
  - 2 instructions for `R1..R6` when `imm8 < 0x10`
  - otherwise 2 instructions for `R0`/`R7`
  - otherwise 3 instructions for `R1..R6`
- labels after a `LI` will be placed after the expanded instruction sequence, not after one byte

### `SETIOI imm8`

Purpose:

- load an immediate value into hidden register `IOSEL`

Source form:

```asm
SETIOI 0x03
SETIOI channel_id
```

Expansion:

```asm
LDI_L_R0 low4
LDI_H_R0 high4
SETIO R0
```

- if `imm8 < 0x10`, it is optimized to:

```asm
LDI_L_R0 imm4
SETIO R0
```

Notes:

- expands to 2 ISA instructions when `imm8 < 0x10`, otherwise 3
- useful for simple I/O programs that do not want to materialize the channel in another register first

## 3. Non-alias assembler conveniences

These are not aliases, but they are part of the current assembly language.

### Directives

- `.org addr`
- `.byte expr [, expr ...]`
- `.fill count [, value]`
- `.equ name, expr`

### Accepted expression forms

- integer literals such as `10`, `0x20`, `0b1010`
- single-character literals such as `'A'`
- symbol references
- arithmetic and bitwise operators:
  - `+`, `-`, `*`, `//`, `%`
  - `<<`, `>>`
  - `&`, `|`, `^`, `~`

### Case handling

- instruction mnemonics are case-insensitive
- register names are case-insensitive

## 4. Things that are intentionally not aliases

The assembler currently does **not** provide higher-level ALU macros such as:

```asm
ADD R3, R4
SUB R5, R6
```

That is intentional. For now, the assembler stays close to the ISA, so
register-transfer sequences are still written explicitly:

```asm
MOV R1, R3
MOV R2, R4
ADD
MOV R3, R0
```

This keeps expansion behavior obvious and makes simulator/debugger source
mapping simpler.
