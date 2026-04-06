# Min8 Randomized RTL Verifier

This document describes the randomized RTL verification component that runs
random legal Min8 images against an RTL DUT and the Python simulator in
retirement-boundary lockstep.

## Purpose

This component exists to:

- stress RTL implementations beyond the directed lockstep programs
- keep failures reproducible with deterministic seeds
- preserve enough forensic state for post-mortem analysis
- provide a reusable verification path for future Min8 RTL variants

This component does not attempt to:

- prove cycle accuracy
- replace directed architectural tests
- hide wrapper differences between unrelated DUTs without an adapter

Correctness is defined only as architectural agreement with the Python
simulator under the same image and I/O schedule. Termination is optional.

## Code Layout

- `tests_rtl/test_rtl_random.py`
  - cocotb entry point that executes the randomized suite
- `tests_rtl/support/randomized.py`
  - random image generation
  - deterministic I/O scheduling
  - failure artifact writing helpers
- `tests_rtl/support/lockstep.py`
  - retirement-boundary lockstep runner
  - RTL/reference state capture
  - failure artifact persistence
- `tests/test_rtl_random_support.py`
  - pure-Python regression checks for deterministic generation and artifact shape

## Execution Model

For each randomized case:

1. derive a deterministic per-case seed from the suite base seed
2. generate one legal Min8 image that contains an inserted `HALT` sink in the
   initial image
3. derive a deterministic I/O seed for setup and blocked-instruction resume events
4. preload the same image into the RTL wrapper and the Python reference CPU
5. run the RTL until one architectural event occurs
6. execute one simulator `step()`
7. compare event type and full architectural state
8. if the event is `blocked`, apply the deterministic I/O resume action
9. stop on `halted`, or return a bounded-success result when the event budget is exhausted
10. fail immediately on any RTL/reference mismatch

When the Verilator unittest runner is used, randomized cases may be split into
multiple shards. Each shard gets its own case-index offset, artifact root, and
cocotb process so failures stay reproducible as standalone cases. Process
isolation is intentional because the cocotb runner consumes process-scoped
environment variables.

Comparison remains instruction-boundary only. Different internal RTL timing is
allowed as long as the architectural event stream matches the simulator.

## Random Program Strategy

The generator only emits legal Min8 opcodes. It samples:

- `MOV`
- legal ALU subopcodes
- memory ops `ST`, `LD`, `ST+`, `LD+`
- control flow `JMP`, `JZ`, `JC`, `JNZ`
- I/O ops `SETIO`, `GETIO`, `IN`, `OUT`

Generation heuristics intentionally bias toward:

- explicit register materialization before ALU and I/O ops
- `R7` traffic for memory coverage
- control-flow back into a known halt sink
- blocking I/O scenarios via deterministic `tx_ready` toggling and queued RX data

Each generated image is padded to 256 bytes with `HALT` so any accidental fall
through remains bounded and debuggable.

The initial image is legal by construction, but execution may still become
chaotic after self-modifying stores. A case may erase its own halt path, loop
forever within the configured budget, or mutate into an illegal opcode. Those
are all valid stress scenarios as long as RTL and simulator stay synchronized.

## Reproducibility Model

The suite is deterministic under the tuple:

- base seed
- case index
- max program bytes
- max events

The I/O schedule is deterministic under:

- per-case I/O seed
- observed architectural event order

When a failure occurs, the emitted artifact directory contains both the exact
image and the execution context needed to replay the case.

The verifier classifies successful randomized cases as:

- `halted_match`
  - the case halted and matched for the whole run
- `bounded_match`
  - the case consumed the configured event budget without divergence
- `cycle_match`
  - optional early termination when a caller-provided exact cycle detector proves
    the next-state tuple has repeated
- `illegal_match`
  - the case self-modified or decoded into an illegal instruction and both RTL
    and simulator faulted on the same opcode at the same PC

In particular:

- `max_events` is a runtime ceiling, not a pass/fail assertion
- budget exhaustion without divergence is a successful bounded run
- self-modifying code is expected and not treated specially
- only mismatches and unexpected harness/runtime errors produce failure artifacts

Per-case execution returns a `LockstepResult` carrying:

- `outcome`
  - final success classification
- `completed_events`
  - number of architectural events consumed before stopping
- `events` and `trace`
  - event stream and detailed per-event forensic data for the successful run
- `cycle_first_seen_event_index` and `cycle_repeat_event_index`
  - populated only for `cycle_match`

## Environment Knobs

- `MIN8_RTL_RANDOM_SEED`
  - suite base seed
  - default: `0x5EED1234`
- `MIN8_RTL_RANDOM_CASES`
  - number of randomized cases in one cocotb test
  - default: `12`
- `MIN8_RTL_RANDOM_CASE_OFFSET`
  - starting case index for the current shard
  - primarily for parallel runners and shard replay; default: `0`
- `MIN8_RTL_RANDOM_JOBS`
  - randomized shard count used by `tests_rtl.test_verilator_runner`
  - default: auto, capped at `4`
- `MIN8_RTL_RANDOM_MAX_EVENTS`
  - architectural-event budget per case
  - default: `256`
- `MIN8_RTL_RANDOM_MAX_PROGRAM_BYTES`
  - maximum generated program length before image padding
  - default: `48`
- `MIN8_RTL_RANDOM_ENABLE_CYCLE_DETECT`
  - enable optional exact cycle detection for early success termination
  - default: `0`
- `MIN8_RTL_RANDOM_ARTIFACT_DIR`
  - root directory for failure artifacts
  - default: `build/rtl_random_failures/`

## How To Run

Run the whole RTL suite:

```bash
source .venv/bin/activate
python -m unittest tests_rtl.test_verilator_runner -v
```

Run a larger randomized sample:

```bash
source .venv/bin/activate
export MIN8_RTL_RANDOM_SEED=0x12345678
export MIN8_RTL_RANDOM_CASES=100
export MIN8_RTL_RANDOM_MAX_EVENTS=128
python -m unittest tests_rtl.test_verilator_runner -v
```

Run a larger sample with parallel randomized shards:

```bash
source .venv/bin/activate
export MIN8_RTL_RANDOM_CASES=2000
export MIN8_RTL_RANDOM_JOBS=4
python -m unittest tests_rtl.test_verilator_runner -v
```

That runner executes the directed cocotb suite once per RTL configuration, then
fans the randomized suite out across per-shard cocotb worker processes. Each
shard logs its own `Randomized lockstep outcomes: halted=... bounded=... cycle=...
illegal=...` summary line.

Run with optional exact cycle detection enabled:

```bash
source .venv/bin/activate
export MIN8_RTL_RANDOM_CASES=500
export MIN8_RTL_RANDOM_ENABLE_CYCLE_DETECT=1
python -m unittest tests_rtl.test_verilator_runner -v
```

Run the pure-Python support checks without Verilator:

```bash
source .venv/bin/activate
python -m unittest tests.test_rtl_random_support -v
```

## Failure Artifacts

On any mismatch or unexpected runtime error, the harness writes:

- `image.bin`
  - exact 256-byte image used by both DUT and simulator
- `image.memh`
  - same image in hex-line form for RTL preload convenience
- `failure.json`
  - structured forensic record

Important `failure.json` content:

- failing event index and RTL event name
- serialized simulator `StepResult`
- reference CPU state before and after the step
- RTL debug snapshot at the failing boundary
- synchronized I/O queues and TX logs
- architectural event trace up to the failure
- generator metadata and I/O script history

Budget exhaustion by itself is not a failure artifact condition.

## Reusing With Other RTL Implementations

The intended reuse pattern is:

1. keep the Python-side random generator and lockstep harness unchanged
2. provide a simulation wrapper for the new RTL core that matches the verifier
   contract in `docs/rtl_random_verifier_contract.md`
3. point the Verilator runner at the new RTL source list and wrapper top
4. reuse `tests_rtl/test_rtl_random.py` directly, or clone it with a different
   runner if the DUT top name changes

If a future wrapper cannot preserve the current signal names, adapt only the
Python-side capture/drive layer. Do not fork the random program generator or
artifact schema unless the ISA itself changes.

## Operational Guidance

- Treat randomized failures as architectural bugs first, not as generator bugs.
- Re-run the exact failing seed before changing generator heuristics.
- Keep the artifact schema backward compatible so tooling can diff failures
  across RTL variants.
- If the ISA grows, update the generator legality tables and the contract
  document in the same change.
