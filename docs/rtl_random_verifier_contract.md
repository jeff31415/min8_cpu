# Min8 Randomized RTL Verifier Contract v1

This document freezes the integration contract for the randomized RTL verifier.
Future Min8 RTL implementations should satisfy this contract to reuse the
existing Python generator, lockstep runner, and failure-analysis tooling.

## Scope

This contract covers:

- Python-side verifier entry points
- RTL wrapper signal semantics
- architectural event semantics
- failure artifact schema expectations

This contract does not cover:

- internal RTL micro-architecture
- cycle counts between architectural events
- FPGA top-level integration

## Stability Rules

- Required fields and signal semantics in this document are stable.
- New optional JSON fields may be added to artifacts.
- Existing JSON fields may be extended but should not change meaning.
- A future incompatible change must create a new contract version.

## Python Entry Points

### `tests_rtl.support.randomized.RandomizedTestConfig`

Required fields:

- `base_seed: int`
- `case_count: int`
- `case_offset: int`
- `max_events: int`
- `max_program_bytes: int`
- `enable_cycle_detect: bool`
- `artifact_root: Path`

Semantics:

- `case_offset` rebases local shard indices onto globally reproducible case indices
- `enable_cycle_detect` enables optional exact cycle termination when callers
  provide a matching state-key function

### `tests_rtl.support.randomized.RandomProgramCase`

Required fields:

- `case_index: int`
- `seed: int`
- `io_seed: int`
- `image: bytes`
- `used_bytes: int`
- `halt_address: int`
- `instructions: tuple[str, ...]`

Semantics:

- `image` must be the exact 256-byte DUT preload image
- `halt_address` must point at the inserted terminating `HALT`
- `instructions` must describe the used program bytes in execution order

### `tests_rtl.support.randomized.RandomizedIOScript`

Required methods:

- `setup(io) -> None`
- `on_event(io, rtl_event: str, result: StepResult, event_index: int) -> None`
- `snapshot() -> dict`

Semantics:

- `setup()` configures the synchronized DUT/reference I/O model before reset release
- `on_event()` may mutate only future I/O availability and backpressure
- `snapshot()` must return deterministic replay metadata

### `tests_rtl.support.lockstep.run_lockstep_image()`

Required behavior:

- preload the image into the DUT memory model
- run until one architectural event occurs
- step the Python simulator once per architectural event
- compare architectural state at retirement boundaries only
- optionally accept a caller-provided exact cycle-state key callback
- return `LockstepResult` on `halted_match`, `bounded_match`, `cycle_match`, or `illegal_match`
- write failure artifacts before re-raising on mismatch when `artifact_root` is set

### `tests_rtl.support.lockstep.run_lockstep_program()`

Required behavior:

- assemble source to an image
- delegate to `run_lockstep_image()`

### `tests_rtl.support.lockstep.LockstepResult`

Required fields:

- `events: tuple[str, ...]`
- `trace: tuple[TraceEntry, ...]`
- `outcome: str`
- `completed_events: int`
- `case_name: str | None`
- `cycle_first_seen_event_index: int | None`
- `cycle_repeat_event_index: int | None`

Semantics:

- `outcome` is one of `halted_match`, `bounded_match`, `cycle_match`, or
  `illegal_match`
- `completed_events` is the number of architectural events consumed before the
  successful stop condition
- cycle index fields are populated only for `cycle_match`

## RTL Wrapper Contract

The randomized verifier is written against a simulation wrapper, not against an
internal core module directly.

### Required wrapper top-level

The current verifier assumes a DUT top compatible with `rtl/min8_core_tb.v`.

Required top-level writable inputs:

- `clk`
- `rst`
- `rx_data[7:0]`
- `rx_valid`
- `tx_ready`
- `tb_mem_we`
- `tb_mem_addr[7:0]`
- `tb_mem_wdata[7:0]`

Required top-level readable outputs:

- `io_chan[7:0]`
- `halted`
- `illegal_instr`
- `faulted`
- `dbg_state`
- `dbg_pc_before[7:0]`
- `dbg_opcode[7:0]`
- `dbg_regs_flat[63:0]`
- `dbg_pc[7:0]`
- `dbg_z`
- `dbg_c`
- `dbg_iosel[7:0]`
- `dbg_retire`
- `dbg_blocked`
- `dbg_halted`
- `dbg_illegal`
- `dbg_mem_write_en`
- `dbg_mem_write_addr[7:0]`
- `dbg_mem_write_data[7:0]`
- `dbg_io_valid`
- `dbg_io_dir`
- `dbg_io_channel[7:0]`
- `dbg_io_data[7:0]`

Required readable memory model path:

- `u_mem.mem[0:255]`

This direct memory visibility is part of the contract because the verifier
captures whole-memory snapshots on each architectural event.

## Architectural Event Semantics

Exactly one of these events may be observed for one completed wait loop:

- `dbg_retire`
- `dbg_blocked`
- `dbg_halted`
- `dbg_illegal`

Semantics:

- `dbg_retire`
  - one instruction retired successfully
- `dbg_blocked`
  - the currently pending I/O instruction could not complete
  - the RTL must retain that instruction and retry it when readiness changes
- `dbg_halted`
  - the current instruction retired as `HALT`
- `dbg_illegal`
  - the RTL detected an illegal instruction condition

The verifier treats these as architectural boundaries, not cycle-level trace
points.

## State Semantics At Comparison Boundary

When an event pulse is observed, the following values must already represent the
post-event architectural state:

- `dbg_pc`
- `dbg_regs_flat`
- `dbg_z`
- `dbg_c`
- `dbg_iosel`
- `halted`
- memory contents visible through `u_mem.mem`

The following fields must still describe the instruction that caused the event:

- `dbg_pc_before`
- `dbg_opcode`

## I/O Semantics

`dbg_io_valid` describes a completed I/O transfer, not an attempted one.

When `dbg_io_valid=1`:

- `dbg_io_dir=0` means `IN`
- `dbg_io_dir=1` means `OUT`
- `dbg_io_channel` is the architectural `IOSEL` channel used by the transfer
- `dbg_io_data` is the transferred byte

When the event is `blocked`:

- `dbg_io_dir` must describe the blocked direction
- `dbg_io_channel` must describe the blocked channel
- `dbg_io_valid` must remain `0`

## Memory-Write Semantics

When the current instruction does not write memory:

- `dbg_mem_write_en=0`

When the current instruction writes memory:

- `dbg_mem_write_en=1`
- `dbg_mem_write_addr` is the written address
- `dbg_mem_write_data` is the committed post-write byte value

The verifier currently expects at most one architectural memory write per Min8
instruction.

## Failure Artifact Contract

Budget exhaustion without divergence is a successful bounded run, not a failure.
Matched illegal-instruction faults are also successful verification outcomes.

When `artifact_root` is configured, the verifier writes one directory per
failure:

- `<artifact_root>/<sanitized_case_name>/image.bin`
- `<artifact_root>/<sanitized_case_name>/image.memh`
- `<artifact_root>/<sanitized_case_name>/failure.json`

### `failure.json` required top-level fields

- `case_name: str`
- `image_sha256: str`
- `image_size: int`
- `error_type: str`
- `error_message: str`
- `event_index: int | null`
- `rtl_event: str | null`
- `step_result: object | null`
- `reference_before: object | null`
- `reference_after: object | null`
- `rtl_snapshot: object | null`
- `io: object`
- `trace: array`
- `context: object | null`

### `context` contract

The randomized test entry point currently stores:

- `random_case`
  - case seed and image metadata
- `io_script`
  - deterministic I/O action history

Future callers may extend `context`, but should preserve these keys when they
reuse the built-in generator.

## Parallel Runner Contract

The bundled Verilator unittest runner may shard randomized cases across
multiple cocotb invocations.

Runner-specific environment knobs:

- `MIN8_RTL_RANDOM_JOBS`
  - number of randomized shards to run in parallel
- `MIN8_RTL_RANDOM_CASE_OFFSET`
  - first global case index assigned to a shard

Shard requirements:

- shard case ranges must be disjoint
- each shard must preserve the same per-case seed derivation as a single-process
  run would for the same global case index
- shards must not share process-scoped randomized environment overrides in a way
  that can change another shard's configuration
- separate worker processes are the recommended implementation strategy
- each shard must write failure artifacts into its own artifact subtree so
  independent failures do not overwrite each other

## Reuse Checklist For A New RTL Variant

1. Implement a simulation wrapper that satisfies the required signal names and
   semantics.
2. Ensure wrapper memory is visible as `u_mem.mem[0:255]`, or update the
   capture helper and version this contract.
3. Reuse `run_lockstep_image()` unchanged if possible.
4. Keep the failure artifact schema stable.
5. Add the new RTL sources to a dedicated Verilator runner.
6. Re-run both directed lockstep and randomized suites.
