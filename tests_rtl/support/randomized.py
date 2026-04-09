from __future__ import annotations

import hashlib
import json
import os
import random
from dataclasses import asdict, dataclass
from pathlib import Path
from typing import Any

from min8.isa import ALU_MNEMONICS, IO_OPCODE_BASE, MEM_CTRL_OPCODE_BASE, decode_opcode


ENV_RANDOM_BASE_SEED = "MIN8_RTL_RANDOM_SEED"
ENV_RANDOM_CASES = "MIN8_RTL_RANDOM_CASES"
ENV_RANDOM_CASE_OFFSET = "MIN8_RTL_RANDOM_CASE_OFFSET"
ENV_RANDOM_MAX_EVENTS = "MIN8_RTL_RANDOM_MAX_EVENTS"
ENV_RANDOM_MAX_PROGRAM_BYTES = "MIN8_RTL_RANDOM_MAX_PROGRAM_BYTES"
ENV_RANDOM_ARTIFACT_DIR = "MIN8_RTL_RANDOM_ARTIFACT_DIR"
ENV_RANDOM_ENABLE_CYCLE_DETECT = "MIN8_RTL_RANDOM_ENABLE_CYCLE_DETECT"

DEFAULT_RANDOM_BASE_SEED = 0x5EED1234
DEFAULT_RANDOM_CASES = 12
DEFAULT_RANDOM_MAX_EVENTS = 256
DEFAULT_RANDOM_MAX_PROGRAM_BYTES = 48
DEFAULT_RANDOM_ENABLE_CYCLE_DETECT = False

PROJECT_ROOT = Path(__file__).resolve().parents[2]
DEFAULT_RANDOM_ARTIFACT_DIR = PROJECT_ROOT / "build" / "rtl_random_failures"
LEGAL_ALU_SUBOPCODES = tuple(sorted(ALU_MNEMONICS))
HALT_OPCODE = 0x7F
RESERVED_IO_CHANNELS = frozenset({0x10, 0x11, 0x12, 0x13})
AVAILABLE_IO_CHANNELS = tuple(channel for channel in range(256) if channel not in RESERVED_IO_CHANNELS)


@dataclass(frozen=True)
class RandomizedTestConfig:
    base_seed: int = DEFAULT_RANDOM_BASE_SEED
    case_count: int = DEFAULT_RANDOM_CASES
    case_offset: int = 0
    max_events: int = DEFAULT_RANDOM_MAX_EVENTS
    max_program_bytes: int = DEFAULT_RANDOM_MAX_PROGRAM_BYTES
    artifact_root: Path = DEFAULT_RANDOM_ARTIFACT_DIR
    enable_cycle_detect: bool = DEFAULT_RANDOM_ENABLE_CYCLE_DETECT


@dataclass(frozen=True)
class RandomProgramCase:
    case_index: int
    seed: int
    io_seed: int
    image: bytes
    used_bytes: int
    halt_address: int
    instructions: tuple[str, ...]

    @property
    def label(self) -> str:
        return f"seed_{self.seed:016X}_case_{self.case_index:03d}"

    def to_metadata(self) -> dict[str, Any]:
        return {
            "case_index": self.case_index,
            "seed": self.seed,
            "seed_hex": f"0x{self.seed:016X}",
            "io_seed": self.io_seed,
            "io_seed_hex": f"0x{self.io_seed:016X}",
            "used_bytes": self.used_bytes,
            "halt_address": self.halt_address,
            "instructions": list(self.instructions),
        }


@dataclass(frozen=True)
class IOScriptAction:
    phase: str
    event_index: int | None = None
    direction: str | None = None
    channel: int | None = None
    value: int | None = None
    tx_ready: bool | None = None


class RandomizedIOScript:
    def __init__(
        self,
        seed: int,
        *,
        preload_events: int = 3,
        max_rx_burst: int = 3,
        tx_stall_probability: float = 0.30,
    ) -> None:
        self.seed = seed
        self._rng = random.Random(seed)
        self._preload_events = max(0, preload_events)
        self._max_rx_burst = max(1, max_rx_burst)
        self._tx_stall_probability = tx_stall_probability
        self._actions: list[IOScriptAction] = []

    def setup(self, io) -> None:
        self._record(phase="setup", tx_ready=True)
        io.set_tx_ready(True)
        for _ in range(self._rng.randrange(self._preload_events + 1)):
            channel = _random_io_channel(self._rng)
            values = [self._rng.randrange(256) for _ in range(1 + self._rng.randrange(self._max_rx_burst))]
            io.queue_rx(channel, *values)
            for value in values:
                self._record(phase="setup", direction="in", channel=channel, value=value)

    def on_event(self, io, rtl_event: str, result, event_index: int) -> None:
        if rtl_event == "blocked":
            blocked = result.blocked_on
            if blocked is None:
                raise AssertionError("blocked event did not expose blocked_on metadata")
            if blocked.direction == "in":
                value = self._rng.randrange(256)
                io.queue_rx(blocked.channel, value)
                self._record(
                    phase="blocked_resume",
                    event_index=event_index,
                    direction="in",
                    channel=blocked.channel,
                    value=value,
                )
            else:
                io.set_tx_ready(True)
                self._record(
                    phase="blocked_resume",
                    event_index=event_index,
                    direction="out",
                    channel=blocked.channel,
                    tx_ready=True,
                )
            return

        if rtl_event != "retire":
            return

        tx_ready = self._rng.random() >= self._tx_stall_probability
        io.set_tx_ready(tx_ready)
        self._record(phase="retire_schedule", event_index=event_index, tx_ready=tx_ready)

    def snapshot(self) -> dict[str, Any]:
        return {
            "seed": self.seed,
            "seed_hex": f"0x{self.seed:016X}",
            "actions": [asdict(action) for action in self._actions],
        }

    def replay_state_key(self) -> tuple[Any, ...]:
        return (self.seed, self._rng.getstate())

    def _record(
        self,
        *,
        phase: str,
        event_index: int | None = None,
        direction: str | None = None,
        channel: int | None = None,
        value: int | None = None,
        tx_ready: bool | None = None,
    ) -> None:
        self._actions.append(
            IOScriptAction(
                phase=phase,
                event_index=event_index,
                direction=direction,
                channel=None if channel is None else channel & 0xFF,
                value=None if value is None else value & 0xFF,
                tx_ready=tx_ready,
            )
        )


def load_randomized_test_config_from_env() -> RandomizedTestConfig:
    return RandomizedTestConfig(
        base_seed=_env_int(ENV_RANDOM_BASE_SEED, DEFAULT_RANDOM_BASE_SEED),
        case_count=max(1, _env_int(ENV_RANDOM_CASES, DEFAULT_RANDOM_CASES)),
        case_offset=max(0, _env_int(ENV_RANDOM_CASE_OFFSET, 0)),
        max_events=max(1, _env_int(ENV_RANDOM_MAX_EVENTS, DEFAULT_RANDOM_MAX_EVENTS)),
        max_program_bytes=max(8, min(255, _env_int(ENV_RANDOM_MAX_PROGRAM_BYTES, DEFAULT_RANDOM_MAX_PROGRAM_BYTES))),
        artifact_root=Path(os.environ.get(ENV_RANDOM_ARTIFACT_DIR, str(DEFAULT_RANDOM_ARTIFACT_DIR))),
        enable_cycle_detect=_env_bool(ENV_RANDOM_ENABLE_CYCLE_DETECT, DEFAULT_RANDOM_ENABLE_CYCLE_DETECT),
    )


def random_case_seed(base_seed: int, case_index: int) -> int:
    value = (base_seed & 0xFFFFFFFFFFFFFFFF) ^ ((case_index + 1) * 0x9E3779B97F4A7C15)
    value ^= value >> 33
    value *= 0xFF51AFD7ED558CCD
    value ^= value >> 33
    value *= 0xC4CEB9FE1A85EC53
    value ^= value >> 33
    return value & 0xFFFFFFFFFFFFFFFF


def build_random_case(seed: int, case_index: int, *, max_program_bytes: int = DEFAULT_RANDOM_MAX_PROGRAM_BYTES) -> RandomProgramCase:
    rng = random.Random(seed)
    target_size = rng.randint(max(8, max_program_bytes // 2), max_program_bytes)
    builder = _ImageBuilder()

    while builder.size < target_size - 1:
        room = target_size - builder.size - 1
        emitters = [
            (1, _emit_random_mov),
            (1, _emit_random_alu),
            (3, _emit_random_memory),
            (4, _emit_random_io),
            (4, _emit_random_branch),
        ]
        available = [emitter for minimum, emitter in emitters if room >= minimum]
        if not available:
            break
        rng.choice(available)(builder, rng, room)

    halt_address = builder.size
    builder.emit(HALT_OPCODE)
    builder.patch_branch_targets(halt_address)

    image = bytearray([HALT_OPCODE] * 256)
    image[: builder.size] = builder.code
    instructions = tuple(f"{address:02X}: {decode_opcode(opcode, pc=address).instruction_text}" for address, opcode in enumerate(builder.code))

    return RandomProgramCase(
        case_index=case_index,
        seed=seed,
        io_seed=random_case_seed(seed ^ 0xA5A5A5A5A5A5A5A5, case_index),
        image=bytes(image),
        used_bytes=builder.size,
        halt_address=halt_address,
        instructions=instructions,
    )


def write_failure_artifact(root: Path, *, case_name: str, image: bytes, payload: dict[str, Any]) -> Path:
    artifact_dir = root / _sanitize_case_name(case_name)
    artifact_dir.mkdir(parents=True, exist_ok=True)
    (artifact_dir / "image.bin").write_bytes(image)
    (artifact_dir / "image.memh").write_text(_format_memh(image), encoding="utf-8")

    payload_with_image = dict(payload)
    payload_with_image.setdefault("image_sha256", hashlib.sha256(image).hexdigest())
    payload_with_image.setdefault("image_size", len(image))
    payload_with_image.setdefault("case_name", case_name)
    (artifact_dir / "failure.json").write_text(
        json.dumps(payload_with_image, indent=2, sort_keys=True) + "\n",
        encoding="utf-8",
    )
    return artifact_dir


class _ImageBuilder:
    def __init__(self) -> None:
        self.code: list[int] = []
        self._branch_patches: list[_ConstantPatch] = []

    @property
    def size(self) -> int:
        return len(self.code)

    def emit(self, opcode: int) -> int:
        self.code.append(opcode & 0xFF)
        return len(self.code) - 1

    def emit_mov(self, dest: int, src: int) -> None:
        self.emit(((dest & 0x07) << 3) | (src & 0x07))

    def emit_load_const(self, register: int, value: int = 0) -> _ConstantPatch:
        if register == 0:
            low_index = self.emit(0x80 | (value & 0x0F))
            high_index = self.emit(0xA0 | ((value >> 4) & 0x0F))
            return _ConstantPatch(low_index=low_index, high_index=high_index)
        if register == 7:
            low_index = self.emit(0x90 | (value & 0x0F))
            high_index = self.emit(0xB0 | ((value >> 4) & 0x0F))
            return _ConstantPatch(low_index=low_index, high_index=high_index)

        patch = self.emit_load_const(0, value)
        self.emit_mov(register, 0)
        return patch

    def patch_constant(self, patch: _ConstantPatch, value: int) -> None:
        self.code[patch.low_index] = (self.code[patch.low_index] & 0xF0) | (value & 0x0F)
        self.code[patch.high_index] = (self.code[patch.high_index] & 0xF0) | ((value >> 4) & 0x0F)

    def record_branch_target(self, patch: _ConstantPatch) -> None:
        self._branch_patches.append(patch)

    def patch_branch_targets(self, target: int) -> None:
        for patch in self._branch_patches:
            self.patch_constant(patch, target)


@dataclass(frozen=True)
class _ConstantPatch:
    low_index: int
    high_index: int


def _emit_random_mov(builder: _ImageBuilder, rng: random.Random, room: int) -> None:
    del room
    builder.emit_mov(rng.randrange(8), rng.randrange(8))


def _emit_random_alu(builder: _ImageBuilder, rng: random.Random, room: int) -> None:
    if room >= 7 and rng.random() < 0.70:
        builder.emit_load_const(1, rng.randrange(256))
        builder.emit_load_const(2, rng.randrange(256))
    elif room >= 4 and rng.random() < 0.80:
        builder.emit_load_const(rng.choice((1, 2)), rng.randrange(256))
    builder.emit(0xC0 | rng.choice(LEGAL_ALU_SUBOPCODES))


def _emit_random_memory(builder: _ImageBuilder, rng: random.Random, room: int) -> None:
    operation = rng.choice(("ST", "LD", "ST+", "LD+"))
    builder.emit_load_const(7, rng.randrange(256))

    if operation in {"ST", "ST+"} and room >= 6 and rng.random() < 0.80:
        register = rng.randrange(8)
        if register != 7:
            builder.emit_load_const(register, rng.randrange(256))
    else:
        register = rng.randrange(7) if operation == "LD+" else rng.randrange(8)

    if operation == "LD+" and register == 7:
        register = 6
    builder.emit(MEM_CTRL_OPCODE_BASE[operation] | register)


def _emit_random_io(builder: _ImageBuilder, rng: random.Random, room: int) -> None:
    builder.emit_load_const(0, _random_io_channel(rng))
    builder.emit(IO_OPCODE_BASE["SETIO"])

    operation = rng.choice(("GETIO", "IN", "OUT"))
    register = rng.randrange(8)
    if operation == "OUT" and room >= 7 and rng.random() < 0.80:
        builder.emit_load_const(register, rng.randrange(256))
    builder.emit(IO_OPCODE_BASE[operation] | register)


def _emit_random_branch(builder: _ImageBuilder, rng: random.Random, room: int) -> None:
    del room
    target_register = rng.randrange(1, 7)
    patch = builder.emit_load_const(target_register, 0)
    builder.record_branch_target(patch)
    builder.emit(MEM_CTRL_OPCODE_BASE[rng.choice(("JMP", "JZ", "JC", "JNZ"))] | target_register)


def _env_int(name: str, default: int) -> int:
    value = os.environ.get(name)
    if value is None:
        return default
    return int(value, 0)


def _env_bool(name: str, default: bool) -> bool:
    value = os.environ.get(name)
    if value is None:
        return default
    normalized = value.strip().lower()
    if normalized in {"1", "true", "yes", "on"}:
        return True
    if normalized in {"0", "false", "no", "off"}:
        return False
    raise ValueError(f"Invalid boolean value for {name}: {value!r}")


def _random_io_channel(rng: random.Random) -> int:
    return AVAILABLE_IO_CHANNELS[rng.randrange(len(AVAILABLE_IO_CHANNELS))]


def _format_memh(image: bytes) -> str:
    return "\n".join(f"{value:02X}" for value in image) + "\n"


def _sanitize_case_name(case_name: str) -> str:
    cleaned = "".join(char if char.isalnum() or char in {"-", "_"} else "_" for char in case_name)
    return cleaned or "case"
