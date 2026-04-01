# Min8-Pro ISA Draft v0

## 1. Goal

Min8-Pro preserves Min8 binary compatibility after reset while adding an optional
16-bit execution and addressing extension. Programs that never use `IOSEL=0xFF`
as a system control port behave as legacy Min8 binaries.

## 2. Architectural State

- `PC`: 16-bit physical register
- `R0`: 16-bit physical register
- `R7`: 16-bit physical register
- `R1..R6`: 8-bit registers
- `Z`, `C`, `IOSEL`: unchanged from Min8
- Hidden control state:
  - `EXT16`: `0` for legacy mode, `1` for 16-bit mode
  - `R0SEL`: `0` selects `R0[7:0]`, `1` selects `R0[15:8]`
  - `R7SEL`: `0` selects `R7[7:0]`, `1` selects `R7[15:8]`

Reset state:

- `EXT16 = 0`
- `R0SEL = 0`
- `R7SEL = 0`
- `PC = 0x0000`
- `R0..R7 = 0`
- `Z = 0`, `C = 0`, `IOSEL = 0`

## 3. Legacy Byte Views

When legacy opcodes access `R0` or `R7` as ordinary byte registers, they use:

```text
R0v = EXT16 ? (R0SEL ? R0[15:8] : R0[7:0]) : R0[7:0]
R7v = EXT16 ? (R7SEL ? R7[15:8] : R7[7:0]) : R7[7:0]
```

All Min8 opcodes keep their original byte semantics by operating on `R0v` and
`R7v`. The unselected byte remains unchanged.

## 4. Mode-Dependent Addressing

In legacy mode (`EXT16=0`):

- fetch address is `PC[7:0]`
- sequential execution increments `PC[7:0]` modulo 256
- data address is `zero_extend(R7[7:0])`
- `LD+` / `ST+` increment only `R7[7:0]` modulo 256

In 16-bit mode (`EXT16=1`):

- fetch address is `PC[15:0]`
- sequential execution increments `PC` modulo 65536
- data address is `R7[15:0]`
- `LD+` / `ST+` increment `R7` modulo 65536

For memory instructions, address generation and byte data selection are distinct:

- `ST R7` stores `R7v` to memory at the current `R7` address view
- `LD R7` loads a byte from the current `R7` address view into `R7v`
- `ST+ R7` stores `R7v`, then increments the physical `R7` according to the mode

`LD+ R7` remains illegal because `0x7F` is still `HALT`.

## 5. Jumps

Legacy mode:

- all `JMP/JZ/JC/JNZ Rr` stay 8-bit and target `0x00..0xFF`

16-bit mode:

- `J* R0` and `J* R7` are long jumps and set `PC` from the full 16-bit register
- `R0SEL` / `R7SEL` do not affect long-jump target construction
- `J* R1..R6` are short jumps and replace only `PC[7:0]`

## 6. New Selector Opcodes

The top four ALU-space opcodes become selector instructions:

- `0xDC` = `R0L`
- `0xDD` = `R0H`
- `0xDE` = `R7L`
- `0xDF` = `R7H`

Rules:

- illegal when `EXT16=0`
- do not read `R1` or `R2`
- do not write `R0`
- do not update `Z` or `C`

The remaining `0xD6..0xDB` stay reserved/illegal.

## 7. System Control Port

`IOSEL=0xFF` is reserved for system configuration.

- `OUT Rs` with `IOSEL=0xFF` does not touch FIFO I/O
- the only defined control value is `0x01`, which sets `EXT16 <- 1`
- repeating the same enable write is legal and acts as a no-op
- all other writes are illegal
- `IN` with `IOSEL=0xFF` is illegal
- leaving 16-bit mode is not supported; any future disable attempt is illegal

## 8. LDI Semantics

`LDI_L_R0`, `LDI_H_R0`, `LDI_L_R7`, and `LDI_H_R7` always target the currently
selected byte view in 16-bit mode. The other byte is preserved.

## 9. Assembler Rules

The first Min8-Pro assembler keeps jump width explicit.

- no automatic short/long jump optimization
- `LI` stays 8-bit only
- new pseudo-ops:
  - `LI16 R0, imm16`
  - `LI16 R7, imm16`
  - `LJMP scratch, imm16`
  - `LJZ scratch, imm16`
  - `LJC scratch, imm16`
  - `LJNZ scratch, imm16`

Constraints:

- `scratch` must be `R0` or `R7`
- `LJ*` pseudo-ops explicitly clobber `scratch`
- `LI16` is emitted with explicit selector instructions and restores the selector
  to low byte afterward
