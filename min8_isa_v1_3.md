# Minimalist 8-Bit CPU ISA (Min8) Reference Manual
**Version:** 1.3  
**Status:** Frozen draft for simulator and RTL implementation

---

## 1. Overview

Min8 is a minimalist 8-bit, fixed-length ISA intended for simple software simulation and compact RTL implementation.

### Core properties
- **Word width:** 8-bit
- **Instruction width:** 8-bit, fixed length
- **Address space:** 256 bytes
- **Memory model:** unified code/data space (Von Neumann)
- **General-purpose registers:** 8 × 8-bit (`R0..R7`)
- **Implicit datapath binding:**
  - `R1`, `R2` are the implicit ALU inputs
  - `R0` is the implicit ALU output
  - `R7` is the implicit memory address register for `LD/ST`
- **I/O model:** dedicated I/O instructions using a hidden 8-bit channel select register `IOSEL`

### Design intent
This ISA deliberately trades code density and orthogonality for:
- very small decode logic
- simple datapath control
- single-byte instruction encoding
- straightforward software emulation

---

## 2. Architectural State

## 2.1 General-purpose registers

| Encoding | Name | Role |
|---|---|---|
| `000` | `R0` | Accumulator / implicit ALU output / immediate-load target |
| `001` | `R1` | Implicit ALU input A |
| `010` | `R2` | Implicit ALU input B |
| `011` | `R3` | GPR |
| `100` | `R4` | GPR |
| `101` | `R5` | GPR |
| `110` | `R6` | GPR |
| `111` | `R7` | GPR with implicit role as memory address register for `LD/ST` |

**Important note:** `R7` is still a normal register and may be read/written by ordinary instructions.  
Its special role is only that memory instructions use `R7` implicitly as the address.

---

## 2.2 Special registers

### Program Counter (`PC`)
- Width: 8-bit
- Reset value: `0x00`
- Sequential execution: fetch from `MEM[PC]`, then increment `PC` modulo 256

### Flags
Only two architectural flags are defined:

- `Z` — Zero flag
- `C` — Carry / Borrow / Shift-out flag

Unless stated otherwise:
- **only ALU instructions update `Z` and `C`**
- all other instructions leave flags unchanged

### I/O Select Register (`IOSEL`)
- Width: 8-bit
- Hidden architectural register
- Selects which I/O channel is accessed by `IN` / `OUT`

`IOSEL` is not part of the normal GPR file, but it can be accessed using dedicated instructions:
- `SETIO Rs`
- `GETIO Rd`

---

## 3. Memory and I/O Model

## 3.1 Memory
- 256 bytes, byte-addressed
- instructions and data share the same address space
- address arithmetic wraps modulo 256

## 3.2 I/O
The ISA models I/O as **channel-indexed FIFOs** selected by `IOSEL`.

A convenient implementation model is:

- `RX_FIFO[c]`: input queue for channel `c`
- `TX_FIFO[c]`: output queue for channel `c`

where `c = IOSEL`.

Instruction semantics:
- `IN Rd`  => pop one byte from `RX_FIFO[IOSEL]` into `Rd`
- `OUT Rs` => push one byte from `Rs` into `TX_FIFO[IOSEL]`

### Blocking behavior
This ISA defines **blocking I/O**:

- `IN` blocks until `RX_FIFO[IOSEL]` is non-empty
- `OUT` blocks until `TX_FIFO[IOSEL]` has space

This blocking behavior is architectural.

---

## 4. Instruction Space Summary

| Prefix | Hex Range | Class |
|---|---:|---|
| `00xxxxxx` | `0x00..0x3F` | `MOV` |
| `01xxxxxx` | `0x40..0x7F` | `MEM / CTRL` |
| `10xxxxxx` | `0x80..0xBF` | `LDI` |
| `110xxxxx` | `0xC0..0xDF` | `ALU` |
| `111xxxxx` | `0xE0..0xFF` | `IO` |

---

## 5. Instruction Reference

## 5.1 Data move (`MOV`)

### Encoding
```text
00 ddd sss
```

- `ddd`: destination register
- `sss`: source register

### Semantics
```text
Rd <- Rs
```

### Flags
- unchanged

### Notes
- `0x00` = `MOV R0, R0`, which may be treated as `NOP`

### Full opcode range
- `0x00..0x3F`

---

## 5.2 Memory and control (`MEM / CTRL`)

### Encoding
```text
01 ooo rrr
```

- `ooo`: sub-opcode
- `rrr`: register field

### Opcode map

| `ooo` | Mnemonic | Semantics |
|---|---|---|
| `000` | `ST Rr` | `MEM[R7] <- Rr` |
| `001` | `LD Rr` | `Rr <- MEM[R7]` |
| `010` | `JMP Rr` | `PC <- Rr` |
| `011` | `JZ Rr` | `if Z == 1: PC <- Rr` |
| `100` | `JC Rr` | `if C == 1: PC <- Rr` |
| `101` | `JNZ Rr` | `if Z == 0: PC <- Rr` |
| `110` | `ST+ Rr` | `MEM[R7] <- Rr; R7 <- R7 + 1` |
| `111` | `LD+ Rr` or `HALT` | see below |

### `LD+` and `ST+` precise semantics

`ST+ Rr` is **post-increment store**:
```text
addr = R7
MEM[addr] <- Rr
R7 <- addr + 1
```

`LD+ Rr` is **post-increment load**:
```text
addr = R7
Rr <- MEM[addr]
R7 <- addr + 1
```

Address increment wraps modulo 256.

### Special encoding for `HALT`
The machine code `0x7F` (`01 111 111`) is **reserved for `HALT`**.

Therefore:

- `0x78..0x7E` = `LD+ R0..R6`
- `0x7F` = `HALT`
- `LD+ R7` **does not exist**

Assembler rule:
- `LD+ R7` must be rejected as invalid

### `ST+ R7`
`ST+ R7` **is legal** and is encoded as `0x77`.

Its semantics are:
```text
addr = R7
MEM[addr] <- R7
R7 <- addr + 1
```

### Flags
- unchanged

### Full opcode range
- `0x40..0x7F`

---

## 5.3 Immediate load (`LDI`)

`LDI` supports immediate construction of only two architectural destinations:
- `R0`
- `R7`

This is intentional.

### Encoding
```text
10 H T iiii
```

- `H`: nibble select
  - `0` = low nibble load
  - `1` = high nibble load
- `T`: target select
  - `0` = `R0`
  - `1` = `R7`
- `iiii`: 4-bit immediate

### Exact semantics

| Encoding | Mnemonic | Semantics |
|---|---|---|
| `10 0 0 iiii` | `LDI_L_R0 imm4` | `R0 <- {0000, iiii}` |
| `10 1 0 iiii` | `LDI_H_R0 imm4` | `R0 <- {iiii, R0[3:0]}` |
| `10 0 1 iiii` | `LDI_L_R7 imm4` | `R7 <- {0000, iiii}` |
| `10 1 1 iiii` | `LDI_H_R7 imm4` | `R7 <- {iiii, R7[3:0]}` |

### Usage note
To build a full byte, software should normally emit:
1. `LDI_L_*`
2. `LDI_H_*`

This avoids stale upper bits from prior register contents.

### Flags
- unchanged

### Full opcode range
- `0x80..0xBF`

---

## 5.4 Arithmetic / Logic (`ALU`)

The ALU uses:
- implicit input A: `R1`
- implicit input B: `R2`
- implicit output: `R0`

### Encoding
```text
110 xxxxx
```

- `xxxxx`: 5-bit ALU sub-opcode

### Defined opcodes

| `xxxxx` | Hex | Mnemonic | Semantics | `Z` | `C` |
|---|---:|---|---|---|---|
| `00000` | `0xC0` | `ADD` | `R0 <- R1 + R2` | result == 0 | carry-out |
| `00001` | `0xC1` | `SUB` | `R0 <- R1 - R2` | result == 0 | borrow-out |
| `00010` | `0xC2` | `AND` | `R0 <- R1 & R2` | result == 0 | `0` |
| `00011` | `0xC3` | `OR`  | `R0 <- R1 \| R2` | result == 0 | `0` |
| `00100` | `0xC4` | `XOR` | `R0 <- R1 ^ R2` | result == 0 | `0` |
| `00101` | `0xC5` | `NOT` | `R0 <- ~R1` | result == 0 | `0` |
| `00110` | `0xC6` | `SHL` | `R0 <- R1 << 1` | result == 0 | old `R1[7]` |
| `00111` | `0xC7` | `SHR` | `R0 <- R1 >> 1` | result == 0 | old `R1[0]` |
| `01000` | `0xC8` | `INC` | `R0 <- R1 + 1` | result == 0 | carry-out |
| `01001` | `0xC9` | `DEC` | `R0 <- R1 - 1` | result == 0 | borrow-out |

## 5.4.1 Graphics and Bit Manipulation Extensions

These ALU extensions accelerate VRAM access, pixel positioning, masking, and single-bit updates.

| `xxxxx` | Hex | Mnemonic | Semantics | `Z` | `C` |
|---|---:|---|---|---|---|
| `01010` | `0xCA` | `SHR2` | `R0 <- R1 >> 2` | result == 0 | old `R1[1]` |
| `01011` | `0xCB` | `SHR3` | `R0 <- R1 >> 3` | result == 0 | old `R1[2]` |
| `01100` | `0xCC` | `SHL2` | `R0 <- R1 << 2` | result == 0 | old `R1[6]` |
| `01101` | `0xCD` | `SHL3` | `R0 <- R1 << 3` | result == 0 | old `R1[5]` |
| `01110` | `0xCE` | `BSET` | `R0 <- R1 \| (1 << R2[2:0])` | result == 0 | `0` |
| `01111` | `0xCF` | `BCLR` | `R0 <- R1 & ~(1 << R2[2:0])` | result == 0 | `0` |
| `10000` | `0xD0` | `BTGL` | `R0 <- R1 ^ (1 << R2[2:0])` | result == 0 | `0` |
| `10001` | `0xD1` | `BTST` | `R0 <- R1 & (1 << R2[2:0])` | result == 0 | `0` |
| `10010` | `0xD2` | `MASK3` | `R0 <- R1 & 0x07` | result == 0 | `0` |
| `10011` | `0xD3` | `MASK4` | `R0 <- R1 & 0x0F` | result == 0 | `0` |

### Extension usage notes

- `SHR2`, `SHR3`, `SHL2`, and `SHL3` are intended as fast address-scaling helpers.
  - `SHR3` is equivalent to divide-by-8.
  - `SHL3` is equivalent to multiply-by-8.
- `BSET`, `BCLR`, `BTGL`, and `BTST` use the low 3 bits of `R2` as an implicit bit index.
- `MASK3` and `MASK4` are fast modulo helpers for powers of two.
  - `MASK3` is equivalent to `R1 % 8`.
  - `MASK4` is equivalent to `R1 % 16`.

## 5.4.2 Extended Precision Arithmetic

These ALU extensions make multi-byte integer arithmetic practical without software-emulated carry propagation.

| `xxxxx` | Hex | Mnemonic | Semantics | `Z` | `C` |
|---|---:|---|---|---|---|
| `10100` | `0xD4` | `ADC` | `R0 <- R1 + R2 + C` | result == 0 | carry-out |
| `10101` | `0xD5` | `SBB` | `R0 <- R1 - R2 - C` | result == 0 | borrow-out |

### Usage notes

- `ADC` consumes the incoming carry bit and writes a new carry-out.
- `SBB` consumes the incoming borrow bit from `C`.
- `SBB` follows the same subtraction convention as `SUB` and `DEC`.
  - `C = 1` means a borrow occurred.
  - `C = 0` means no borrow occurred.

### Carry / borrow convention
For subtraction-class instructions (`SUB`, `DEC`, `SBB`):
- `C = 1` means a **borrow occurred**
- `C = 0` means **no borrow**

### Reserved ALU space
Encodings `0xD6..0xDF` are currently **reserved**.

### Reserved opcode behavior
For simulator and RTL consistency, the following behavior is defined:

- executing a reserved ALU opcode is an **illegal instruction**
- a simulator should raise an explicit `IllegalInstruction`
- an RTL core should enter a halted or faulted state and may expose an internal `illegal_instr` signal

Assembler rule:
- reserved encodings must not be emitted

---

## 5.5 I/O instructions (`IO`)

## 5.5.1 `SETIO`

### Encoding
```text
11100 sss
```

### Range
- `0xE0..0xE7`

### Semantics
```text
IOSEL <- Rs
```

### Flags
- unchanged

---

## 5.5.2 `GETIO`

### Encoding
```text
11101 ddd
```

### Range
- `0xE8..0xEF`

### Semantics
```text
Rd <- IOSEL
```

### Flags
- unchanged

---

## 5.5.3 `IN`

### Encoding
```text
11110 ddd
```

### Range
- `0xF0..0xF7`

### Semantics
```text
Rd <- pop(RX_FIFO[IOSEL])
```

### Blocking rule
If `RX_FIFO[IOSEL]` is empty, the processor blocks until one byte becomes available.

### Flags
- unchanged

---

## 5.5.4 `OUT`

### Encoding
```text
11111 sss
```

### Range
- `0xF8..0xFF`

### Semantics
```text
push(TX_FIFO[IOSEL], Rs)
```

### Blocking rule
If `TX_FIFO[IOSEL]` is full, the processor blocks until space becomes available.

### Flags
- unchanged

---

## 6. Exact Architectural Semantics

## 6.1 PC update rule
The architectural model assumes:
1. fetch instruction at current `PC`
2. increment `PC` modulo 256
3. execute the fetched instruction
4. branch/jump instructions overwrite `PC` during execution

This model is recommended for both simulator and RTL.

## 6.2 Memory wraparound
All address calculations are 8-bit and wrap modulo 256.

Examples:
- `R7 = 0xFF`, then `ST+ R3` => store at `0xFF`, then `R7 = 0x00`
- `PC = 0xFF`, next sequential fetch wraps to `0x00`

## 6.3 Self-modifying code
Because code and data share one memory space:
- self-modifying code is legal
- instruction fetch sees whatever value is currently in memory

## 6.4 Flag stability
Unless an instruction is in the `ALU` class:
- `Z` and `C` must remain unchanged

This includes:
- `MOV`
- `LD`, `ST`, `LD+`, `ST+`
- `JMP`, `JZ`, `JC`, `JNZ`
- `LDI`
- `SETIO`, `GETIO`, `IN`, `OUT`
- `HALT`

---

## 7. Reset State

On reset:

- `PC <- 0x00`
- `Z <- 0`
- `C <- 0`
- `IOSEL <- 0x00`
- `R0..R7 <- 0x00`

Resetting memory contents is implementation-defined:
- a simulator may initialize memory to zero
- RTL may rely on external ROM/RAM initialization

---

## 8. Recommended Implementation Model

## 8.1 Simulator model
A reference interpreter can implement one architectural instruction per `step()`:
1. fetch
2. increment `PC`
3. decode
4. execute or block

For blocking I/O:
- either actually block
- or expose an external “not ready” status and suspend retirement of the current instruction

The important architectural requirement is:
- `IN` and `OUT` do not complete until the transfer succeeds

## 8.2 RTL model
A compact multi-cycle implementation is recommended.

### Suggested states
- **FETCH**
  - `IR <- MEM[PC]`
  - `PC <- PC + 1`
- **EXEC**
  - decode and execute register/ALU/control instructions
  - compute memory address for `LD/ST/LD+/ST+`
- **MEM**
  - perform memory read/write for `LD/ST/LD+/ST+`
  - for post-increment forms, update `R7` after the memory access
- **IOWAIT**
  - for `IN` or `OUT`, stall until the selected FIFO is ready
  - retire the instruction only when transfer succeeds

### Unified memory note
Because instruction fetch and data access share one memory:
- single-port RAM is acceptable with a multi-cycle controller
- pseudo dual-port RAM is optional, not required

---

## 9. Assembler Notes

## 9.1 Legal aliases
- `NOP` = `MOV R0, R0` = `0x00`

## 9.2 Recommended pseudo-ops
These are assembler conveniences, not ISA instructions.

### Load 8-bit immediate into arbitrary register
```asm
LDI_L_R0 low4
LDI_H_R0 high4
MOV Rd, R0
```

### Load 8-bit memory address into `R7`
```asm
LDI_L_R7 low4
LDI_H_R7 high4
```

### Set `IOSEL` from immediate
```asm
LDI_L_R0 low4
LDI_H_R0 high4
SETIO R0
```

## 9.3 Invalid source form
Assembler must reject:
```asm
LD+ R7
```
because its encoding is occupied by `HALT`.

---

## 10. Worked Examples

## 10.1 Add two registers
Goal: `R3 <- R3 + R4`

```asm
MOV R1, R3
MOV R2, R4
ADD
MOV R3, R0
```

## 10.2 Sequential store
Store three bytes from `R3`, `R4`, `R5` starting at address `0x20`:

```asm
LDI_L_R7 0x0
LDI_H_R7 0x2
ST+ R3
ST+ R4
ST+ R5
```

## 10.3 Sequential load
Load three bytes into `R3`, `R4`, `R5` starting at address `0x20`:

```asm
LDI_L_R7 0x0
LDI_H_R7 0x2
LD+ R3
LD+ R4
LD+ R5
```

## 10.4 Use I/O channel 3
Read a byte from channel `3`, then echo it back to channel `3`:

```asm
LDI_L_R0 0x3
SETIO R0
IN  R3
OUT R3
```

---

## 11. Canonical Opcode Map

```text
00xxxxxx  MOV          (0x00..0x3F)

01xxxxxx  MEM/CTRL     (0x40..0x7F)
01000rrr  ST   Rr      (0x40..0x47)
01001rrr  LD   Rr      (0x48..0x4F)
01010rrr  JMP  Rr      (0x50..0x57)
01011rrr  JZ   Rr      (0x58..0x5F)
01100rrr  JC   Rr      (0x60..0x67)
01101rrr  JNZ  Rr      (0x68..0x6F)
01110rrr  ST+  Rr      (0x70..0x77)
01111rrr  LD+  Rr      (0x78..0x7E)
01111111  HALT         (0x7F)

10xxxxxx  LDI          (0x80..0xBF)
1000iiii  LDI_L_R0     (0x80..0x8F)
1010iiii  LDI_H_R0     (0xA0..0xAF)
1001iiii  LDI_L_R7     (0x90..0x9F)
1011iiii  LDI_H_R7     (0xB0..0xBF)

110xxxxx  ALU          (0xC0..0xDF)
11000000  ADD          (0xC0)
11000001  SUB          (0xC1)
11000010  AND          (0xC2)
11000011  OR           (0xC3)
11000100  XOR          (0xC4)
11000101  NOT          (0xC5)
11000110  SHL          (0xC6)
11000111  SHR          (0xC7)
11001000  INC          (0xC8)
11001001  DEC          (0xC9)
11001010  SHR2         (0xCA)
11001011  SHR3         (0xCB)
11001100  SHL2         (0xCC)
11001101  SHL3         (0xCD)
11001110  BSET         (0xCE)
11001111  BCLR         (0xCF)
11010000  BTGL         (0xD0)
11010001  BTST         (0xD1)
11010010  MASK3        (0xD2)
11010011  MASK4        (0xD3)
11010100  ADC          (0xD4)
11010101  SBB          (0xD5)
11010110..11011111     reserved / illegal

111xxxxx  IO           (0xE0..0xFF)
11100sss  SETIO        (0xE0..0xE7)
11101ddd  GETIO        (0xE8..0xEF)
11110ddd  IN           (0xF0..0xF7)
11111sss  OUT          (0xF8..0xFF)
```

---

## 12. Compliance Notes

A compliant Min8 implementation must:
- implement all defined opcodes exactly as specified
- preserve flags for non-ALU instructions
- implement blocking semantics for `IN`/`OUT`
- treat `0x7F` as `HALT`
- reject or fault on reserved ALU encodings
- reject `LD+ R7` at the assembler level

---

## 13. Revision History

### Version 1.3
- added ALU graphics and bit-manipulation extensions:
  - `SHR2`, `SHR3`, `SHL2`, `SHL3`
  - `BSET`, `BCLR`, `BTGL`, `BTST`
  - `MASK3`, `MASK4`
- added extended-precision arithmetic opcodes:
  - `ADC`, `SBB`
- reduced remaining reserved ALU space to `0xD6..0xDF`

### Version 1.2
- restored `R6` as GPR
- moved implicit memory pointer role to `R7`
- introduced hidden `IOSEL`
- added dedicated `SETIO`, `GETIO`, `IN`, `OUT`
- expanded ALU encoding space to 32 entries
- added `ST+` and `LD+`
- fixed `HALT = 0x7F` while preserving legal `ST+ R7` by assigning:
  - `ST`  to `01000rrr`
  - `LD`  to `01001rrr`
  - `ST+` to `01110rrr`
  - `LD+` to `01111rrr` except `0x7F`
