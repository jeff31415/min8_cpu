# Min8 Peripheral I/O Library Plan

This note fixes a simulator-first plan for a reusable peripheral I/O library
that sits outside the Min8 CPU core and later maps cleanly onto RTL wrappers.

## Goals

- keep the CPU architectural contract unchanged
- preserve the existing channel-oriented I/O programming model
- let the GUI simulator host richer devices than raw FIFOs
- make the first implementation reusable between `min8` and `min8_pro`
- keep later RTL work in board-level wrappers instead of inside the core

## Non-Goals

- changing the Min8 instruction set
- making I/O timing cycle-accurate in the Python simulator
- requiring external audio dependencies for the first GUI implementation
- implementing a full PS/2 host stack beyond the byte-stream contract needed by software

## Current Constraints

Today the software stack assumes:

- CPU depends on an injectable FIFO-like I/O backend
- `IN` and `OUT` are architecturally blocking
- GUI interacts with I/O through the interactive session layer
- RTL core already exposes a wrapper-friendly `rx_*` / `tx_*` channel interface

This means the peripheral layer should replace the current plain FIFO backend
without changing CPU execution semantics.

## Frozen Direction

### 1. CPU-facing model

The CPU-facing interface stays byte-oriented and channel-oriented.

- one selected channel at a time via `IOSEL`
- `IN` reads one byte
- `OUT` writes one byte
- device-specific behavior is implemented behind the selected channel

The CPU does not know whether a channel is backed by:

- a plain FIFO
- a PS/2 adapter
- an audio sink
- a WS2812 serializer

### 2. Placement

Peripheral logic lives outside the CPU core.

- simulator: in a new shared Python peripheral library
- GUI: as an extra page that configures and observes the peripheral library
- RTL: as optional wrapper modules around `min8_core`

### 3. Shared implementation target

The first implementation should be shared instead of copied into both
`min8` and `min8_pro`.

Recommended new package split:

- `min8/peripherals.py` or `min8_common/peripherals.py`
- shared config/data model
- shared hub and device implementations

If a new common package is introduced, `min8` and `min8_pro` should both depend
on it for peripheral handling instead of growing separate copies.

## Proposed Module Shape

### 1. Core hub

Introduce a CPU-facing hub object that presents the same operational surface as
the current FIFO backend and adds simulator-side management hooks.

Suggested interface:

- `can_read(channel: int) -> bool`
- `can_write(channel: int) -> bool`
- `read(channel: int) -> int`
- `write(channel: int, value: int) -> None`
- `tick(elapsed_s: float) -> None`
- `snapshot() -> PeripheralHubState`
- `load_config(config: PeripheralHubConfig) -> None`
- `dump_config() -> PeripheralHubConfig`

Rules:

- channel numbers remain `0x00..0xFF`
- unbound channels may fall back to plain FIFO behavior
- device-local buffering and readiness are hidden behind the hub

### 2. Device base class

Suggested per-device protocol:

- `device_type: str`
- `channel: int`
- `can_read() -> bool`
- `can_write() -> bool`
- `read() -> int`
- `write(value: int) -> None`
- `tick(elapsed_s: float) -> None`
- `snapshot() -> PeripheralState`
- `to_config() -> dict`

Only the hub should resolve channel ownership.

### 3. Plain FIFO fallback

Retain a generic FIFO-backed channel device for:

- existing tests
- channels not assigned to a richer peripheral
- future UART-like or host-scripted devices

This avoids breaking the current channel-oriented workflow.

## Device Specs

### 1. PS/2 input device

This device models a host-visible byte stream with a small protocol tweak to
avoid CPU stalls on empty reads.

#### Channel behavior

- channel is bidirectional
- `IN` pops one queued keycode byte
- `OUT` pushes one command byte into a command log or command FIFO

#### Read semantics

- if the receive FIFO is non-empty, `IN` returns the oldest byte
- if the receive FIFO is empty, `IN` returns `0x00`
- empty read does not block the CPU

This is intentionally different from the architectural default blocking FIFO
model, but only for this device.

#### Write semantics

- `OUT` records one command byte for the device
- command writes may be exposed to the GUI for inspection
- first implementation does not need to emulate full PS/2 command responses

#### Buffering

- configurable RX FIFO depth
- configurable TX/command FIFO depth
- if RX FIFO is full, newly injected keycode bytes are dropped
- dropped-byte count should be visible in device state

#### Byte format

First implementation should use scan code set 2 style raw byte sequences.

- make/break prefixes such as `0xF0` are preserved
- extended prefixes such as `0xE0` are preserved
- GUI key capture may map host key events into these byte sequences

#### GUI affordances

- enable or disable host keyboard capture
- inject bytes manually
- show RX fill level
- show recent command bytes written by software
- show dropped-byte counter

### 2. Audio output device

This device models an 8-bit sample sink consumed at a fixed sample rate.

#### Channel behavior

- first version is output-only
- CPU writes 8-bit unsigned PCM samples with `OUT`
- CPU reads are optional and should return a fixed value if exposed at all

Recommended first behavior:

- `IN` is unsupported in the GUI and not used by software
- if a read path must exist for backend uniformity, return `0x80`

#### Sample format

- 8-bit unsigned mono PCM
- fixed sample rate: `16_000 Hz`

#### Buffering

- configurable TX/sample FIFO depth
- `OUT` blocks when the sample FIFO is full
- background consumption removes samples at `16 kHz`

#### Empty playback behavior

- when the sample FIFO underflows, output silence value `0x80`
- underflow count should be tracked for diagnostics

#### GUI affordances

- show FIFO fill level
- show recent waveform history
- show underflow count
- allow clearing the buffer
- optional real audio playback toggle

#### Dependency policy

The first GUI version should not require extra Python packages.
Host playback may use a platform tool such as `aplay` when available.

Suggested order:

1. implement buffering and waveform visualization
2. optionally add real playback behind an OS-level backend or extra dependency later

#### Host playback follow-up

The current `aplay` hookup is good enough for smoke testing and "can it make
sound", but it is not expected to be low-jitter. The main causes are:

- Tk scheduling jitter in the GUI event loop
- pipe writes into an external player process instead of a callback-driven audio API
- no dedicated host-side ring buffer control beyond the simulator FIFO itself
- no clock-reconciliation layer between simulated time and host playback time

If cleaner playback becomes important later, likely next options are:

1. move host audio into a small dedicated module outside `gui.py`
2. use a callback-capable backend such as PortAudio via an optional dependency
3. add a host-side PCM ring buffer with explicit high/low watermarks
4. keep fast-run wall-clock driven, but decouple simulator FIFO from host buffer depth
5. optionally support WAV dump/export as a deterministic non-realtime path

### 3. WS2812 device

This device models a buffered LED strip or matrix that consumes bytes and
updates a virtual pixel array.

#### Channel behavior

- first version is output-only
- CPU writes raw color bytes with `OUT`
- device assembles bytes into LED color values

#### Byte format

First implementation freezes:

- 3 bytes per LED
- byte order: `GRB`
- 8 bits per component

So one full frame consumes:

- `led_count * 3` bytes

#### Update rule

Recommended first rule in the simulator:

- accumulate bytes into a staging buffer
- once `led_count * 3` bytes are collected, commit one full frame
- extra bytes start the next frame

This is intentionally higher level than waveform-exact WS2812 timing.

#### Buffering

- configurable TX FIFO depth between CPU and serializer
- `OUT` blocks when that FIFO is full
- serializer consumes bytes in the background

The simulator does not need sub-microsecond timing. It only needs:

- deterministic byte consumption
- a consistent frame commit rule

#### Geometry

The GUI config should support both strip and matrix use.

Required fields:

- `width`
- `height`

Derived fields:

- `led_count = width * height`

Recommended optional fields:

- `serpentine: bool`
- `rotation: 0 | 90 | 180 | 270`

#### GUI affordances

- live pixel preview
- numeric width and height editing
- strip or matrix presentation
- serpentine toggle
- recent frame counter

### 4. FILO stack device

This device models a bounded last-in, first-out byte store that can be used as
an experimental hardware stack.

#### Channel behavior

- channel is bidirectional
- `OUT` pushes one byte onto the stack
- `IN` pops the most recently pushed byte

#### Read semantics

- if the stack is non-empty, `IN` returns the newest stored byte
- if the stack is empty, `IN` blocks

#### Write semantics

- `OUT` pushes one byte
- if the stack is full, `OUT` blocks

#### Buffering

- one configurable stack depth
- GUI-side injection may seed the stack for debugging
- injected bytes beyond capacity should be dropped and counted

#### GUI affordances

- show current depth
- show the current stack contents
- allow pushing test bytes manually
- allow clearing the stack

## Config Model

Use a versioned JSON config file that is independent from the loaded Min8
program image.

Suggested top-level shape:

```json
{
  "version": 1,
  "devices": [
    {
      "type": "ps2",
      "name": "keyboard0",
      "channel": 16,
      "rx_depth": 32,
      "tx_depth": 8
    },
    {
      "type": "audio8",
      "name": "audio0",
      "channel": 17,
      "tx_depth": 1024,
      "sample_rate_hz": 16000
    },
    {
      "type": "ws2812",
      "name": "leds0",
      "channel": 18,
      "tx_depth": 192,
      "width": 8,
      "height": 8,
      "color_order": "GRB",
      "serpentine": false
    },
    {
      "type": "filo",
      "name": "stack0",
      "channel": 19,
      "depth": 32
    }
  ]
}
```

### Validation rules

- `version` is required
- device names should be unique within one config
- channels should be unique unless explicit fanout is introduced later
- all depths must be positive integers
- WS2812 `width * height` must be greater than zero
- audio `sample_rate_hz` defaults to `16000` and may be overridden per device
- PS/2 defaults to scan code set 2 raw bytes
- FILO depth must be a positive integer

### Persistence behavior

The GUI should support:

- new config
- load config
- save config
- save config as

Config persistence should not overwrite or mutate the loaded program image.

## GUI Integration Plan

Do not overload the current small `I/O` debugger panel with peripheral setup.
Keep the existing byte-queue controls for generic FIFO channels and add a
dedicated peripheral page.

Recommended GUI layout:

- current debugger page remains focused on source, registers, memory, and raw I/O log
- new `Peripherals` tab or notebook page hosts device configuration and live state

Recommended page sections:

- device list
- add or remove device controls
- selected device configuration form
- selected device live preview
- config load and save actions

### Session integration

Session should own exactly one hub instance.

- `session.io` becomes a peripheral hub instead of a plain FIFO
- raw queue or drain helpers can delegate to fallback FIFO channels
- GUI device widgets should use typed device APIs through the hub

## Time Model

The simulator should use an explicit peripheral tick path rather than burying
timing in ad hoc GUI callbacks.

Rules:

- device consumption is driven by elapsed simulated wall-clock time
- GUI run loop calls `hub.tick(elapsed_s)` before or after CPU batches
- tests can drive the same path with a fake clock

This is especially important for:

- audio sample consumption
- WS2812 serializer progress
- future timed peripherals

## Recommended Phase Split

### Phase 0: freeze the software contract

Deliverables:

- this design note
- config schema and validation rules
- explicit device behavior notes for empty, full, and unsupported cases

### Phase 1: shared simulator library

Deliverables:

- shared peripheral hub
- plain FIFO fallback device
- PS/2 device
- audio device without mandatory playback dependency
- WS2812 device with matrix preview semantics
- FILO stack device for hardware-stack experiments
- unit tests for device behavior and config round-trip

### Phase 2: GUI integration

Deliverables:

- `Peripherals` page
- load and save config actions
- device state panels
- host keyboard capture for PS/2
- waveform preview for audio
- matrix preview for WS2812

### Phase 3: Min8-Pro hookup

Deliverables:

- reusing the same peripheral library from `min8_pro`
- no copied device logic between `min8` and `min8_pro`

### Phase 4: optional RTL wrappers

Deliverables:

- PS/2 wrapper with RX/TX FIFOs and host state machine
- audio wrapper with sample FIFO and DAC or PWM output path
- WS2812 wrapper with TX FIFO and serializer
- FILO stack wrapper using a small LIFO memory and channel adapter

The RTL core remains unchanged.

## Test Matrix

Minimum software tests:

- PS/2 empty read returns `0x00`
- PS/2 FIFO overflow drops new bytes
- PS/2 command writes are observable
- audio `OUT` blocks when FIFO is full
- audio `tick()` consumes samples at `16 kHz`
- audio underflow increments a counter and outputs silence
- WS2812 commits a frame after `led_count * 3` bytes
- WS2812 geometry mapping is stable for matrix mode
- FILO returns bytes in last-written, first-read order
- config JSON round-trips through parse and emit
- session still supports generic raw FIFO channels when no rich device is bound

GUI integration tests can stay lightweight, but the core device logic should be
covered without Tk dependencies.

## RTL Mapping Notes

The existing RTL core interface is already suitable for wrapper-based device
integration.

- `io_chan` selects the active channel
- `rx_valid` and `rx_data` feed reads
- `rx_pop` acknowledges a consumed input byte
- `tx_ready` gates writes
- `tx_push` and `tx_data` emit output bytes

That maps cleanly onto:

- PS/2 FIFOs
- audio sample FIFOs
- WS2812 transmit FIFOs

This keeps peripheral behavior out of `min8_core`.

## Open Choices

These are intentionally deferred but should be decided before Phase 2 is fully
implemented.

- exact host-key to PS/2 scan-code mapping table used by the GUI
- whether audio playback gets an optional runtime dependency in-tree
- whether WS2812 matrix rotation is needed in version 1 or can wait
- whether generic FIFO channels remain configurable from the same page or only
  from the existing raw I/O panel

## Recommended Immediate Next Step

Implement Phase 1 first:

1. add the shared peripheral hub and config model
2. wire session to use the hub
3. add unit tests for PS/2, audio, WS2812, and config round-trip
4. only then extend the GUI
