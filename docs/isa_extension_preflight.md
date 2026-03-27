# Min8 ISA Extension Preflight

This note captures the concrete change surface for extending the current Min8 ISA implementation.

## Current Opcode Space

- `00xxxxxx`: `MOV Rd, Rs`
- `01xxxxxx`: memory/control family
  - `0x40-0x47`: `ST Rn`
  - `0x48-0x4F`: `LD Rn`
  - `0x50-0x57`: `JMP Rn`
  - `0x58-0x5F`: `JZ Rn`
  - `0x60-0x67`: `JC Rn`
  - `0x68-0x6F`: `JNZ Rn`
  - `0x70-0x77`: `ST+ Rn`
  - `0x78-0x7E`: `LD+ Rn`
  - `0x7F`: `HALT`
- `10xxxxxx`: `LDI_{L/H}_{R0/R7} imm4`
- `110xxxxx`: ALU family
  - used: `ADD SUB AND OR XOR NOT SHL SHR INC DEC SHR2 SHR3 SHL2 SHL3 BSET BCLR BTGL BTST MASK3 MASK4 ADC SBB`
  - free: subopcodes `0x16-0x1F`
- `111xxxxx`: I/O family
  - `SETIO`, `GETIO`, `IN`, `OUT`

## Practical Extension Options

### Option A: Extend inside ALU free space

Best when the new instruction:

- has no explicit operand bits
- naturally uses the existing implicit ALU datapath
- writes `R0` and optionally updates `Z/C`

Impact is smallest because the encoding shape already exists.

### Option B: Reassign reserved encodings in another family

Needed when the new instruction:

- needs a register operand
- needs different side effects than ALU instructions
- needs new addressing behavior

This is a larger change because decode, formatting, execution, and assembler parsing all need new cases.

## Files That Must Stay In Sync

- `min8/isa.py`
  - source of truth for opcode decode tables
  - update `DecodedInstruction` if the new instruction carries new operands or metadata
- `min8/cpu.py`
  - implement execution semantics
  - update flag behavior and step trace side effects
- `min8/asm.py`
  - accept mnemonic and operands
  - encode opcode
  - update pseudo-instruction size logic if expansion rules change
- `min8/disasm.py`
  - usually no direct change if `decode_opcode()` and `instruction_text` already cover the new instruction
  - change only if formatting needs new presentation
- `min8/session.py`
  - only needed if the extension adds new visible machine state or new stop conditions
- `min8/gui.py`
  - only needed if the extension adds new visible state, new edit targets, or display-only affordances

## Minimum Test Matrix

- `tests/test_isa.py`
  - decode of the new opcode
  - reserved/illegal behavior around adjacent encodings
- `tests/test_cpu.py`
  - execution semantics
  - flag behavior
  - corner cases such as wraparound or blocking
- `tests/test_assembler.py`
  - assembly syntax and encoding
  - rejection paths for malformed operands or illegal encodings
  - integration test that assembled code runs on the simulator
- `tests/test_disasm.py`
  - disassembly text for the new opcode
- `tests/test_session.py`
  - only if debugger-visible behavior changes

## Decisions To Lock Before Implementation

- Exact opcode encoding
- Operand form
  - no operand
  - register operand
  - immediate nibble
  - pseudo-instruction only
- Data path semantics
  - which registers are read
  - which registers are written
- Flag semantics
  - preserve flags
  - write `Z`
  - write `C`
- Whether the instruction is legal on all registers
- Whether the instruction should be surfaced in GUI affordances or editing widgets

## Recommended Implementation Order

1. Lock the opcode and behavioral spec in the ISA markdown.
2. Update `min8/isa.py` decode and instruction text.
3. Update `min8/cpu.py` execution semantics.
4. Update `min8/asm.py` encoding and diagnostics.
5. Update disassembly formatting only if needed.
6. Add tests before touching GUI behavior.
7. Update debugger/session/GUI only if the new instruction introduces new visible state.

## Current Readiness

The codebase is already in good shape for ISA work because decode, assemble, execute, and disassemble are separated cleanly. The cheapest remaining extension path is to consume free ALU subopcodes `0x16-0x1F`. If a future instruction needs an explicit register operand, expect a broader cross-module change.
