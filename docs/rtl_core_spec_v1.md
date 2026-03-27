# Min8 RTL Core Spec v1

This document freezes the first RTL micro-architecture before implementation.

## Scope

This spec covers:

- the first functional RTL core
- state sequencing
- control signal ownership
- register-file shape
- memory and I/O interfaces
- simulation-first memory assumptions

This spec intentionally does not cover:

- FPGA timing closure
- BRAM-specific pipelining
- bus protocols

## Frozen Decisions

### 1. Execution model

- single-issue
- sequential
- multi-cycle
- no overlap between instructions

State machine:

- `S_FETCH`
- `S_EXEC`
- `S_MEM`
- `S_IOWAIT`
- `S_HALT`
- `S_FAULT`

### 2. Architectural latency targets

- regular register/ALU/control instructions: 2 cycles
- memory instructions: 3 cycles
- blocking I/O: 2 cycles minimum, then remain in `S_IOWAIT`

### 3. Memory strategy for v1

Use **Plan A**:

- `min8_core` talks to an abstract instruction/data memory interface
- the first simulation wrapper uses a 256-byte unified memory model
- the first memory model is **asynchronous read, synchronous write**

This keeps the intended 2-cycle / 3-cycle architectural timing without forcing
the core to absorb FPGA BRAM timing yet.

FPGA-specific BRAM wrapping is deferred to a later integration stage.

## Module Split

Recommended first RTL file split:

- `rtl/min8_core.v`
  - state machine
  - decode
  - control
  - `PC`, `IR`, `Z`, `C`, `IOSEL`
  - fault / halt handling
- `rtl/min8_regfile.v`
  - `R0..R7`
  - 4 combinational read ports
  - 2 synchronous write ports
- `rtl/min8_alu.v`
  - all ALU ops `0xC0..0xD5`
  - illegal subopcodes `0xD6..0xDF`
- `rtl/min8_mem_model.v`
  - simulation-only unified 256-byte memory
  - async read
  - sync write
- `rtl/min8_core_tb.v`
  - ties core + memory model + simple I/O model together
  - exposes debug signals for cocotb

## Core External Interface

### Clock and reset

- `input clk`
- `input rst`

### Instruction memory interface

- `output [7:0] imem_addr`
- `output       imem_en`
- `input  [7:0] imem_rdata`

For v1, `imem_rdata` is assumed combinational from `imem_addr` when `imem_en=1`.

### Data memory interface

- `output [7:0] dmem_addr`
- `output       dmem_en`
- `output       dmem_we`
- `output [7:0] dmem_wdata`
- `input  [7:0] dmem_rdata`

For v1:

- reads are combinational during `S_MEM`
- writes commit on the `S_MEM` clock edge when `dmem_we=1`

### I/O interface

- `input  [7:0] rx_data`
- `input        rx_valid`
- `output       rx_pop`
- `output [7:0] tx_data`
- `input        tx_ready`
- `output       tx_push`
- `output [7:0] io_chan`

`io_chan = IOSEL`.

## Architectural State Registers

- `PC[7:0]`
- `IR[7:0]`
- `Z`
- `C`
- `IOSEL[7:0]`
- `state`
- `halted`
- `illegal_instr`
- `faulted`

### Internal latches

- `mem_addr_q[7:0]`
- `mem_wdata_q[7:0]`
- `mem_dst_q[2:0]`
- `mem_is_load_q`
- `mem_postinc_q`
- `io_is_in_q`
- `io_dst_q[2:0]`
- `io_tx_data_q[7:0]`

## Field Extraction

These field names must be kept precise because not all instruction classes use
the same bits.

- `mov_dst = IR[5:3]`
- `mov_src = IR[2:0]`
- `reg_rrr = IR[2:0]`
- `ldi_h   = IR[5]`
- `ldi_t   = IR[4]`
- `imm4    = IR[3:0]`
- `alu_subop = IR[4:0]`

Important architectural consequence:

- `LD`, `LD+`, `GETIO`, `IN`, and `OUT` all use `IR[2:0]`
- only `MOV` uses `IR[5:3]` as a general destination field

## Register File Spec

The register file is frozen as:

- 8 registers
- 8 bits each
- 4 combinational read ports
- 2 synchronous write ports
- 1 packed state-readout bus for full register visibility

### Read ports

- `rdata_r1`  reads fixed register `R1`
- `rdata_r2`  reads fixed register `R2`
- `rdata_src` reads `IR[2:0]`
- `rdata_r7`  reads fixed register `R7`
- `regs_flat[63:0]` exposes `{R7,R6,R5,R4,R3,R2,R1,R0}`

This is intentionally more explicit than a muxed 2-read-port design because:

- the storage is tiny
- control becomes much simpler
- FPGA resource cost is negligible

`regs_flat` is not a fifth arbitrary read port. It exists so the core can:

- build `LDI_H_R0` from the old low nibble of `R0`
- export architectural state cheaply for debug and cocotb checks

### Write ports

- write port 1: main architectural writeback
- write port 2: `R7` post-increment path

Legal ISA behavior should never require both write ports to target the same
register except `R7` on port 2.

## Writeback Selects

### Main writeback data

- `WB_ALU`
- `WB_SRC`
- `WB_MEM`
- `WB_LDI`
- `WB_IOSEL`
- `WB_RX`

### Main writeback address

- `WA_MOV_DST` = `IR[5:3]`
- `WA_IR_RRR`  = `IR[2:0]`
- `WA_R0`
- `WA_R7`
- `WA_IOWAIT_DST` = `io_dst_q`

This avoids the earlier ambiguity where `GETIO` and `IN` were accidentally
treated like `MOV`.

## ALU Interface

Fixed inputs:

- `A = rdata_r1`
- `B = rdata_r2`
- `Cin = C`

Outputs:

- `Y[7:0]`
- `COUT`
- `illegal`

Defined subopcodes:

- `0x00..0x15` are legal
- `0x16..0x1F` are illegal

`SUB`, `DEC`, and `SBB` use the fixed convention:

- `borrow occurred => COUT = 1`

## State Behavior

### `S_FETCH`

- `imem_en = 1`
- `imem_addr = PC`
- `IR <= imem_rdata`
- `PC <= PC + 1`
- next state: `S_EXEC`

No other architectural state updates occur here.

### `S_EXEC`

Handles:

- `MOV`
- `LDI`
- ALU ops
- `JMP`, `JZ`, `JC`, `JNZ`
- `SETIO`, `GETIO`
- `IN`, `OUT` when immediately serviceable
- `HALT`

For memory instructions, `S_EXEC` only prepares and latches parameters.

For blocked I/O:

- latch `io_is_in_q`
- latch `io_dst_q` or `io_tx_data_q`
- hold `IR`
- hold `PC`
- move to `S_IOWAIT`

### `S_MEM`

Handles:

- `ST`
- `LD`
- `ST+`
- `LD+`

Rules:

- access memory using `mem_addr_q`
- for `LD+` and `ST+`, `R7` post-increment uses `mem_addr_q + 1`
- post-increment must be based on the latched old address, never a fresh read of `R7`

### `S_IOWAIT`

- retry the latched `IN` or `OUT`
- no fetch
- no `PC` movement
- no `IR` change

### `S_HALT`

- terminal state after `HALT`

### `S_FAULT`

- terminal state after illegal instruction

## Instruction-Class Control Summary

### `MOV Rd, Rs`

- read source from `IR[2:0]`
- write destination `IR[5:3]`
- no flags update
- next: `S_FETCH`

### `GETIO Rd`

- write destination `IR[2:0]`
- source is current `IOSEL`
- no flags update
- next: `S_FETCH`

### `IN Rd`

- destination is `IR[2:0]`
- if `rx_valid`, pop and retire
- else latch `io_is_in_q=1`, `io_dst_q=IR[2:0]`, next `S_IOWAIT`

### `OUT Rs`

- source is `IR[2:0]`
- if `tx_ready`, push and retire
- else latch `io_is_in_q=0`, `io_tx_data_q=rdata_src`, next `S_IOWAIT`

### `LD Rr` / `LD+ Rr`

- destination register is always `IR[2:0]`

### Illegal ALU opcodes

- if `IR[7:5] == 3'b110` and `IR[4:0] >= 5'h16`
- set `illegal_instr`
- set `faulted`
- next `S_FAULT`

## Simulation Memory Model Rules

`rtl/min8_mem_model.v` should implement:

- one shared 256-byte array
- instruction read path from `imem_addr`
- data read path from `dmem_addr`
- synchronous write on `posedge clk` when `dmem_en && dmem_we`

This model is intentionally chosen for functional RTL verification, not FPGA
block RAM inference.

## Verification Hooks

The first core should expose these debug signals in simulation:

- `dbg_state`
- `dbg_retire`
- `dbg_blocked`
- `dbg_halted`
- `dbg_illegal`
- `dbg_pc_before`
- `dbg_opcode`
- `dbg_regs[0..7]`
- `dbg_z`
- `dbg_c`
- `dbg_iosel`
- `dbg_mem_write_en`
- `dbg_mem_write_addr`
- `dbg_mem_write_data`
- `dbg_io_valid`
- `dbg_io_dir`
- `dbg_io_channel`
- `dbg_io_data`

## Next Implementation Step

Once this spec is accepted, the correct coding order is:

1. `min8_alu.v`
2. `min8_regfile.v`
3. `min8_core.v`
4. `min8_mem_model.v`
5. `min8_core_tb.v`
6. cocotb smoke tests
