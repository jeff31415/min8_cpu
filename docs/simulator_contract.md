# Min8 Reference Simulator Contract

This document fixes the core software interfaces before assembler and debugger
work starts.

## Goals

- one authoritative ISA/decode table shared by all tools
- deterministic instruction-level execution model
- explicit modeling of blocking I/O
- traceable side effects for debugger and RTL cross-checking

## Public Python modules

- `min8.isa`
  - register names and opcode decode helpers
  - instruction formatting for diagnostics and disassembly views
- `min8.io`
  - channel-oriented FIFO I/O backend
  - injectable test I/O and future GUI bridge point
- `min8.cpu`
  - architectural machine state
  - `Min8CPU.step()` and `Min8CPU.run()`
  - structured execution results with side-effect details
- `min8.exceptions`
  - explicit simulator exceptions such as illegal instruction faults

## Execution contract

- `step()` executes at most one architectural instruction retirement.
- The architectural fetch model is:
  1. fetch `MEM[PC]`
  2. increment `PC`
  3. execute
  4. overwrite `PC` on taken control-flow instructions
- `IN` and `OUT` are blocking instructions.
- If an I/O instruction cannot complete, the CPU exposes a blocked
  `StepResult` and retains the fetched instruction internally.
- Once the selected channel becomes ready, calling `step()` again retries the
  same instruction instead of fetching a new opcode.
- Reserved ALU encodings raise `IllegalInstruction`.

## State model

- `R0..R7`, `PC`, `Z`, `C`, `IOSEL`
- `MEM[256]`
- halted bit
- optional pending blocked instruction latch

## Trace model

Each `step()` returns a `StepResult` with:

- `status`: `retired`, `blocked`, or `halted`
- `pc_before`, `opcode`, `instruction_text`
- register writes
- memory writes
- flag values before and after the instruction
- I/O transfer or I/O block reason when relevant

This is sufficient for:

- unit tests
- text-mode tracing
- future GUI state diff views
- future RTL lockstep comparison

## Out of scope for phase 1

- assembler parsing and symbol resolution
- source-level stepping
- cycle-accurate RTL timing
- GUI event loop integration
