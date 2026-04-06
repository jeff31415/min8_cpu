# Min8 RTL Test Framework Proposal

This document defines the recommended verification strategy before writing the
first Min8 RTL core.

## Goals

- use the existing Python simulator as the architectural golden reference
- avoid cycle-accuracy coupling between simulator and RTL
- make it cheap to localize failures to decode, ALU, control flow, memory, or I/O
- keep the first RTL bring-up focused on architectural correctness

## Core Strategy

Do not compare RTL and simulator cycle-by-cycle.

Instead, compare them at **instruction retirement boundaries**.

That matches the current software oracle:

- `Min8CPU.step()` is instruction-level
- the planned RTL is naturally multi-cycle
- internal FSM timing may change during refactors without changing architecture

The check point should be:

- one retired instruction
- one blocked I/O event
- one halt
- one illegal-instruction fault

## Recommended Tool Stack

### Primary choice

- RTL simulator: `Verilator`
- Python testbench: `cocotb`
- existing oracle: `min8.cpu.Min8CPU`
- existing assembler: `min8.asm`

Why this is the best fit here:

- the whole project is already Python-driven
- the golden model is already in Python
- cocotb can directly call the oracle without file-based trace glue
- Verilator is fast enough for random and regression tests

### What not to do first

- do not start with handwritten Verilog self-checking testbenches
- do not require cycle-accurate matching with the Python simulator
- do not start with FPGA hardware-in-loop as the primary correctness gate

## Verification Layers

### Layer 1: Directed architectural tests

Small hand-written programs for:

- reset state
- `MOV`, `LDI`, ALU base ops
- graphics/bit extensions
- `ADC` / `SBB` carry chains
- jumps and `PC` overwrite behavior
- `ST`, `LD`, `ST+`, `LD+`
- self-modifying code visibility
- blocking `IN` / `OUT`
- illegal opcode handling
- `HALT`
- wraparound at `0xFF`

These should be the first RTL tests written.

### Layer 2: Lockstep retirement tests

For each test program:

1. load the same 256-byte image into simulator and RTL wrapper memory
2. run RTL until one architectural event occurs
3. step the Python oracle once
4. compare architectural state and event type

Compare at minimum:

- retired / blocked / halted / illegal status
- `pc_before`
- fetched opcode
- `R0..R7`
- `PC`
- `Z`, `C`
- `IOSEL`
- any memory write address/data
- I/O transfer direction, channel, and value

### Layer 3: Random program regression

Generate short legal initial images and compare complete architectural traces.

Constraints:

- keep program length small, for example 8 to 32 instructions
- emit legal initial opcode bytes, while allowing later self-modification to
  create loops or illegal decodes
- treat the event budget as a resource cap, not as a correctness assertion
- allow non-halting and illegal-ending cases to pass when they still match the
  simulator
- use deterministic RNG seeds

Random tests should heavily sample:

- ALU instructions
- jumps
- `R7` wraparound
- memory aliases with code space
- `ADC` / `SBB`
- I/O block and resume sequences
- self-modifying control-flow disruption

### Layer 4: Module-level micro-tests

Only if the RTL is split into modules such as:

- decoder
- ALU
- register file
- I/O block

These tests are useful, but they should not replace whole-core architectural
lockstep tests.

## Required RTL Test Wrapper

The first core should be wrapped in a simulation-only top module that provides:

- clock and reset
- an abstract instruction/data memory boundary
- a simulation memory model that backs that boundary
- simple FIFO-backed I/O model
- architectural event outputs
- optional debug visibility into state

Recommended wrapper responsibilities:

- instantiate a 256-byte unified simulation memory model
- preload memory from a hex or binary-derived image
- optionally expose a simple test-side memory write path for cocotb preload
- expose a pulse when one instruction retires
- expose a pulse when the core blocks on I/O
- expose a pulse when the core halts
- expose a pulse on illegal instruction

## Recommended Debug Signals

To make lockstep comparison cheap, expose these from the RTL in simulation:

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

This can be done either with explicit debug ports or with a packed debug bus.

## I/O Test Model

Match the software model exactly:

- channel-indexed RX FIFOs
- channel-indexed TX FIFOs
- `IN` blocks if RX is empty
- `OUT` blocks if TX is full

The RTL test wrapper should let the Python testbench:

- queue RX bytes into a selected channel
- drain TX bytes from a selected channel
- configure small TX capacities for backpressure tests

## Comparison Model

The Python testbench should maintain:

- one `Min8CPU` oracle instance
- one RTL DUT instance
- one shared initial image

Pseudo-flow:

1. assemble source or load binary image
2. initialize oracle memory and RTL memory with the same bytes
3. while step budget not exhausted:
4. clock RTL until one architectural event occurs
5. execute one oracle step
6. compare event type and full state
7. if blocked, inject I/O stimulus as needed and continue
8. return success on `HALT`, exact repeated-state cycle detection, legal budget
   exhaustion, or matched illegal-instruction fault

## Repository Layout Recommendation

Suggested structure:

- `rtl/`
  - `min8_core.v`
  - `min8_mem_model.v`
  - `min8_core_tb.v`
- `tests_rtl/`
  - `test_rtl_smoke.py`
  - `test_rtl_lockstep.py`
  - `test_rtl_random.py`
- `tests_rtl/support/`
  - `lockstep.py`
  - `randomized.py`

## Current Randomized Flow

The repository now includes a reusable randomized retirement-lockstep flow for
RTL verification.

- entry point: `tests_rtl/test_rtl_random.py`
- image generator and deterministic I/O scheduler: `tests_rtl/support/randomized.py`
- lockstep execution and failure artifact capture: `tests_rtl/support/lockstep.py`
- component guide: `docs/rtl_random_verifier.md`
- integration contract: `docs/rtl_random_verifier_contract.md`

Environment knobs:

- `MIN8_RTL_RANDOM_SEED`
- `MIN8_RTL_RANDOM_CASES`
- `MIN8_RTL_RANDOM_CASE_OFFSET`
- `MIN8_RTL_RANDOM_JOBS`
- `MIN8_RTL_RANDOM_MAX_EVENTS`
- `MIN8_RTL_RANDOM_MAX_PROGRAM_BYTES`
- `MIN8_RTL_RANDOM_ENABLE_CYCLE_DETECT`
- `MIN8_RTL_RANDOM_ARTIFACT_DIR`

Successful randomized outcomes are classified as:

- `halted_match`
- `bounded_match`
- `cycle_match`
- `illegal_match`

On any mismatch or unexpected runtime failure, the harness writes:

- `image.bin`
- `image.memh`
- `failure.json`

The artifact directory defaults to `build/rtl_random_failures/`, and the
Verilator runner overrides it per build so different RTL configurations do not
clobber each other.

The Verilator unittest runner can shard randomized cases across multiple worker
processes with `MIN8_RTL_RANDOM_JOBS`. Each shard gets a disjoint global case
range and its own artifact subtree so reproducibility is preserved.

Keep RTL tests separate from the current pure-Python unit tests.

## Rollout Plan

### Phase A

- write `rtl/min8_core.v`
- write `rtl/min8_mem_model.v`
- write `rtl/min8_core_tb.v`
- add one cocotb smoke test for reset, one `ADD`, one `HALT`

### Phase B

- add directed tests for all current instruction classes
- add lockstep compare against the Python simulator

### Phase C

- add random regression
- add waveform dumping only for failing tests

## Recommendation

The right first milestone is:

- `Verilator + cocotb`
- abstract memory ports in `min8_core`
- simulation-only memory/I/O wrapper around those ports
- retirement-boundary lockstep against `Min8CPU`

That gives the fastest path to high confidence without prematurely locking the
RTL to any particular micro-architecture.
