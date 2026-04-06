"""Shared channel-oriented peripheral backends."""

from __future__ import annotations

from collections import deque
from dataclasses import dataclass, field
from typing import Any

CONFIG_VERSION = 1


@dataclass(frozen=True)
class IOBlock:
    direction: str
    channel: int


@dataclass(frozen=True)
class PeripheralConfigEntry:
    type: str
    name: str
    channel: int
    options: dict[str, Any] = field(default_factory=dict)

    def to_dict(self) -> dict[str, Any]:
        data = {
            "type": self.type,
            "name": self.name,
            "channel": self.channel & 0xFF,
        }
        data.update(self.options)
        return data


@dataclass(frozen=True)
class PeripheralHubConfig:
    version: int = CONFIG_VERSION
    devices: tuple[PeripheralConfigEntry, ...] = ()

    def to_dict(self) -> dict[str, Any]:
        return {
            "version": self.version,
            "devices": [entry.to_dict() for entry in self.devices],
        }

    @classmethod
    def from_dict(cls, payload: dict[str, Any]) -> PeripheralHubConfig:
        if not isinstance(payload, dict):
            raise TypeError("peripheral config payload must be a dict")
        version = payload.get("version")
        if version != CONFIG_VERSION:
            raise ValueError(f"Unsupported peripheral config version {version!r}")
        devices_payload = payload.get("devices", [])
        if not isinstance(devices_payload, list):
            raise TypeError("'devices' must be a list")

        devices: list[PeripheralConfigEntry] = []
        for index, item in enumerate(devices_payload):
            if not isinstance(item, dict):
                raise TypeError(f"device entry {index} must be a dict")
            try:
                device_type = str(item["type"])
                name = str(item["name"])
                channel = _validate_channel(item["channel"])
            except KeyError as exc:
                raise ValueError(f"device entry {index} is missing {exc.args[0]!r}") from exc
            options = {
                key: value
                for key, value in item.items()
                if key not in {"type", "name", "channel"}
            }
            devices.append(
                PeripheralConfigEntry(
                    type=device_type,
                    name=name,
                    channel=channel,
                    options=options,
                )
            )
        return cls(version=version, devices=tuple(devices))


class PeripheralDevice:
    """Base class for hub-managed channel devices."""

    device_type = "device"

    def __init__(self, *, channel: int, name: str | None = None) -> None:
        self.channel = _validate_channel(channel)
        self.name = name or f"{self.device_type}{self.channel:02X}"

    def can_read(self) -> bool:
        return False

    def can_write(self) -> bool:
        return False

    def read(self) -> int:
        raise RuntimeError(f"{self.device_type} does not support read()")

    def write(self, value: int) -> None:
        raise RuntimeError(f"{self.device_type} does not support write()")

    def tick(self, elapsed_s: float) -> None:
        if elapsed_s < 0:
            raise ValueError("elapsed_s must be non-negative")

    def clear(self) -> None:
        """Clear transient buffered state while keeping static config."""

    def inject_rx(self, *values: int) -> None:
        raise ValueError(f"{self.device_type} does not support RX injection")

    def drain_tx(self) -> list[int]:
        return []

    def rx_depth(self) -> int:
        return 0

    def tx_depth(self) -> int:
        return 0

    def snapshot(self) -> dict[str, Any]:
        return {
            "type": self.device_type,
            "name": self.name,
            "channel": self.channel,
            "rx_depth": self.rx_depth(),
            "tx_depth": self.tx_depth(),
        }

    def to_config(self) -> PeripheralConfigEntry:
        return PeripheralConfigEntry(
            type=self.device_type,
            name=self.name,
            channel=self.channel,
            options={},
        )


class FIFOChannelDevice(PeripheralDevice):
    """Generic FIFO-backed channel used for fallback and raw channels."""

    device_type = "fifo"

    def __init__(
        self,
        *,
        channel: int,
        name: str | None = None,
        rx_capacity: int | None = None,
        tx_capacity: int | None = None,
    ) -> None:
        super().__init__(channel=channel, name=name)
        self.rx_capacity = _validate_capacity(rx_capacity, "rx_capacity")
        self.tx_capacity = _validate_capacity(tx_capacity, "tx_capacity")
        self._rx: deque[int] = deque()
        self._tx: deque[int] = deque()

    def can_read(self) -> bool:
        return bool(self._rx)

    def can_write(self) -> bool:
        if self.tx_capacity is None:
            return True
        return len(self._tx) < self.tx_capacity

    def read(self) -> int:
        return self._rx.popleft()

    def write(self, value: int) -> None:
        self._tx.append(_byte(value))

    def inject_rx(self, *values: int) -> None:
        for value in values:
            if self.rx_capacity is None or len(self._rx) < self.rx_capacity:
                self._rx.append(_byte(value))

    def drain_tx(self) -> list[int]:
        values = list(self._tx)
        self._tx.clear()
        return values

    def clear(self) -> None:
        self._rx.clear()
        self._tx.clear()

    def rx_depth(self) -> int:
        return len(self._rx)

    def tx_depth(self) -> int:
        return len(self._tx)


class PS2KeyboardDevice(PeripheralDevice):
    """Bidirectional PS/2-like byte stream with non-blocking empty reads."""

    device_type = "ps2"

    def __init__(
        self,
        *,
        channel: int,
        name: str | None = None,
        rx_depth: int = 32,
        tx_depth: int = 8,
    ) -> None:
        super().__init__(channel=channel, name=name)
        self.rx_capacity = _validate_positive_int(rx_depth, "rx_depth")
        self.tx_capacity = _validate_positive_int(tx_depth, "tx_depth")
        self._rx: deque[int] = deque()
        self._commands: deque[int] = deque()
        self.dropped_input_count = 0
        self.empty_read_count = 0

    def can_read(self) -> bool:
        return True

    def can_write(self) -> bool:
        return len(self._commands) < self.tx_capacity

    def read(self) -> int:
        if self._rx:
            return self._rx.popleft()
        self.empty_read_count += 1
        return 0x00

    def write(self, value: int) -> None:
        self._commands.append(_byte(value))

    def inject_rx(self, *values: int) -> None:
        for value in values:
            if len(self._rx) < self.rx_capacity:
                self._rx.append(_byte(value))
            else:
                self.dropped_input_count += 1

    def drain_tx(self) -> list[int]:
        values = list(self._commands)
        self._commands.clear()
        return values

    def rx_depth(self) -> int:
        return len(self._rx)

    def tx_depth(self) -> int:
        return len(self._commands)

    def snapshot(self) -> dict[str, Any]:
        state = super().snapshot()
        state.update(
            {
                "rx_capacity": self.rx_capacity,
                "tx_capacity": self.tx_capacity,
                "rx_queue": list(self._rx),
                "command_queue": list(self._commands),
                "dropped_input_count": self.dropped_input_count,
                "empty_read_count": self.empty_read_count,
            }
        )
        return state

    def clear(self) -> None:
        self._rx.clear()
        self._commands.clear()
        self.dropped_input_count = 0
        self.empty_read_count = 0

    def to_config(self) -> PeripheralConfigEntry:
        return PeripheralConfigEntry(
            type=self.device_type,
            name=self.name,
            channel=self.channel,
            options={
                "rx_depth": self.rx_capacity,
                "tx_depth": self.tx_capacity,
            },
        )


class AudioOutputDevice(PeripheralDevice):
    """8-bit PCM audio sink consumed at a fixed sample rate."""

    device_type = "audio8"

    def __init__(
        self,
        *,
        channel: int,
        name: str | None = None,
        tx_depth: int = 1024,
        sample_rate_hz: int = 16_000,
        history_limit: int = 256,
        silence_value: int = 0x80,
    ) -> None:
        super().__init__(channel=channel, name=name)
        self.tx_capacity = _validate_positive_int(tx_depth, "tx_depth")
        self.sample_rate_hz = _validate_positive_int(sample_rate_hz, "sample_rate_hz")
        self.history_limit = _validate_positive_int(history_limit, "history_limit")
        self.silence_value = _byte(silence_value)
        self._samples: deque[int] = deque()
        self._history: deque[int] = deque(maxlen=self.history_limit)
        self._output_tap_enabled = False
        self._output_tap: deque[int] = deque()
        self._sample_phase = 0.0
        self.underflow_count = 0
        self.samples_played = 0

    @property
    def sample_interval_s(self) -> float:
        return 1.0 / self.sample_rate_hz

    def can_read(self) -> bool:
        return True

    def can_write(self) -> bool:
        return len(self._samples) < self.tx_capacity

    def read(self) -> int:
        return self.silence_value

    def write(self, value: int) -> None:
        self._samples.append(_byte(value))

    def consume_samples(self, count: int = 1) -> None:
        remaining = max(0, int(count))
        for _ in range(remaining):
            if self._samples:
                sample = self._samples.popleft()
            else:
                sample = self.silence_value
                self.underflow_count += 1
            self._history.append(sample)
            if self._output_tap_enabled:
                self._output_tap.append(sample)
            self.samples_played += 1

    def set_output_tap_enabled(self, enabled: bool) -> None:
        self._output_tap_enabled = bool(enabled)
        if not self._output_tap_enabled:
            self._output_tap.clear()

    def drain_output_tap(self) -> bytes:
        if not self._output_tap:
            return b""
        data = bytes(self._output_tap)
        self._output_tap.clear()
        return data

    def tick(self, elapsed_s: float) -> None:
        super().tick(elapsed_s)
        self._sample_phase += elapsed_s * self.sample_rate_hz
        samples_due = int(self._sample_phase)
        if samples_due <= 0:
            return
        self._sample_phase -= samples_due
        self.consume_samples(samples_due)

    def drain_tx(self) -> list[int]:
        values = list(self._samples)
        self._samples.clear()
        return values

    def tx_depth(self) -> int:
        return len(self._samples)

    def snapshot(self) -> dict[str, Any]:
        state = super().snapshot()
        state.update(
            {
                "sample_rate_hz": self.sample_rate_hz,
                "silence_value": self.silence_value,
                "pending_samples": list(self._samples),
                "underflow_count": self.underflow_count,
                "samples_played": self.samples_played,
                "recent_samples": list(self._history),
                "output_tap_enabled": self._output_tap_enabled,
                "output_tap_depth": len(self._output_tap),
            }
        )
        return state

    def clear(self) -> None:
        self._samples.clear()
        self._history.clear()
        self._output_tap.clear()
        self._sample_phase = 0.0
        self.underflow_count = 0
        self.samples_played = 0

    def to_config(self) -> PeripheralConfigEntry:
        return PeripheralConfigEntry(
            type=self.device_type,
            name=self.name,
            channel=self.channel,
            options={
                "tx_depth": self.tx_capacity,
                "sample_rate_hz": self.sample_rate_hz,
            },
        )


class WS2812Device(PeripheralDevice):
    """Buffered WS2812 strip or matrix model."""

    device_type = "ws2812"

    def __init__(
        self,
        *,
        channel: int,
        name: str | None = None,
        tx_depth: int = 192,
        width: int = 8,
        height: int = 8,
        color_order: str = "GRB",
        serpentine: bool = False,
        serializer_byte_rate_hz: int = 100_000,
    ) -> None:
        super().__init__(channel=channel, name=name)
        self.tx_capacity = _validate_positive_int(tx_depth, "tx_depth")
        self.width = _validate_positive_int(width, "width")
        self.height = _validate_positive_int(height, "height")
        self.color_order = _validate_color_order(color_order)
        self.serpentine = bool(serpentine)
        self.serializer_byte_rate_hz = _validate_positive_int(
            serializer_byte_rate_hz,
            "serializer_byte_rate_hz",
        )
        self._tx: deque[int] = deque()
        self._staging: list[int] = []
        self._byte_phase = 0.0
        self.frame_count = 0
        self._pixels: list[tuple[int, int, int]] = [(0, 0, 0)] * self.led_count

    @property
    def byte_interval_s(self) -> float:
        return 1.0 / self.serializer_byte_rate_hz

    @property
    def led_count(self) -> int:
        return self.width * self.height

    @property
    def frame_size(self) -> int:
        return self.led_count * 3

    def can_write(self) -> bool:
        return len(self._tx) < self.tx_capacity

    def write(self, value: int) -> None:
        self._tx.append(_byte(value))

    def consume_bytes(self, count: int = 1) -> None:
        remaining = min(len(self._tx), max(0, int(count)))
        for _ in range(remaining):
            self._staging.append(self._tx.popleft())
            if len(self._staging) == self.frame_size:
                self._commit_frame()
                self._staging.clear()

    def tick(self, elapsed_s: float) -> None:
        super().tick(elapsed_s)
        if not self._tx:
            self._byte_phase = 0.0
            return
        self._byte_phase += elapsed_s * self.serializer_byte_rate_hz
        bytes_due = min(len(self._tx), int(self._byte_phase))
        if bytes_due <= 0:
            return
        self._byte_phase -= bytes_due
        self.consume_bytes(bytes_due)

    def drain_tx(self) -> list[int]:
        values = list(self._tx)
        self._tx.clear()
        return values

    def tx_depth(self) -> int:
        return len(self._tx)

    def pixel_matrix(self) -> tuple[tuple[tuple[int, int, int], ...], ...]:
        rows: list[tuple[tuple[int, int, int], ...]] = []
        for row_index in range(self.height):
            start = row_index * self.width
            row = self._pixels[start : start + self.width]
            if self.serpentine and row_index % 2 == 1:
                row = list(reversed(row))
            rows.append(tuple(row))
        return tuple(rows)

    def snapshot(self) -> dict[str, Any]:
        state = super().snapshot()
        state.update(
            {
                "width": self.width,
                "height": self.height,
                "color_order": self.color_order,
                "serpentine": self.serpentine,
                "frame_count": self.frame_count,
                "pending_bytes": list(self._tx),
                "staging_bytes": len(self._staging),
                "staging_data": list(self._staging),
                "pixels": tuple(self._pixels),
                "matrix": self.pixel_matrix(),
            }
        )
        return state

    def to_config(self) -> PeripheralConfigEntry:
        return PeripheralConfigEntry(
            type=self.device_type,
            name=self.name,
            channel=self.channel,
            options={
                "tx_depth": self.tx_capacity,
                "width": self.width,
                "height": self.height,
                "color_order": self.color_order,
                "serpentine": self.serpentine,
            },
        )

    def clear(self) -> None:
        self._tx.clear()
        self._staging.clear()
        self._byte_phase = 0.0
        self._pixels = [(0, 0, 0)] * self.led_count
        self.frame_count = 0

    def _commit_frame(self) -> None:
        target_index = {"R": 0, "G": 1, "B": 2}
        pixels: list[tuple[int, int, int]] = []
        for index in range(0, len(self._staging), 3):
            components = self._staging[index : index + 3]
            values = [0, 0, 0]
            for source_index, component in enumerate(components):
                values[target_index[self.color_order[source_index]]] = component
            pixels.append((values[0], values[1], values[2]))
        self._pixels = pixels
        self.frame_count += 1


class FILOStackDevice(PeripheralDevice):
    """Bidirectional finite stack device for hardware-stack experiments."""

    device_type = "filo"

    def __init__(
        self,
        *,
        channel: int,
        name: str | None = None,
        depth: int = 32,
    ) -> None:
        super().__init__(channel=channel, name=name)
        self.capacity = _validate_positive_int(depth, "depth")
        self._stack: list[int] = []
        self.dropped_input_count = 0

    def can_read(self) -> bool:
        return bool(self._stack)

    def can_write(self) -> bool:
        return len(self._stack) < self.capacity

    def read(self) -> int:
        return self._stack.pop()

    def write(self, value: int) -> None:
        self._stack.append(_byte(value))

    def inject_rx(self, *values: int) -> None:
        for value in values:
            if len(self._stack) < self.capacity:
                self._stack.append(_byte(value))
            else:
                self.dropped_input_count += 1

    def rx_depth(self) -> int:
        return len(self._stack)

    def tx_depth(self) -> int:
        return len(self._stack)

    def snapshot(self) -> dict[str, Any]:
        state = super().snapshot()
        state.update(
            {
                "depth": self.capacity,
                "stack": tuple(self._stack),
                "dropped_input_count": self.dropped_input_count,
            }
        )
        return state

    def clear(self) -> None:
        self._stack.clear()
        self.dropped_input_count = 0

    def to_config(self) -> PeripheralConfigEntry:
        return PeripheralConfigEntry(
            type=self.device_type,
            name=self.name,
            channel=self.channel,
            options={"depth": self.capacity},
        )


class PeripheralHubBase:
    """Shared channel multiplexer for generic FIFO and richer peripherals."""

    def __init__(self, *, would_block_exc_type: type[Exception], tx_capacity: int | None = None) -> None:
        self._would_block_exc_type = would_block_exc_type
        self.tx_capacity = _validate_capacity(tx_capacity, "tx_capacity")
        self._devices: dict[int, PeripheralDevice] = {}
        self._fallback_channels: dict[int, FIFOChannelDevice] = {}

    def can_read(self, channel: int) -> bool:
        return self._resolve_device(channel).can_read()

    def can_write(self, channel: int) -> bool:
        return self._resolve_device(channel).can_write()

    def read(self, channel: int) -> int:
        channel = _validate_channel(channel)
        device = self._resolve_device(channel)
        if not device.can_read():
            raise self._would_block_exc_type("in", channel)
        return _byte(device.read())

    def write(self, channel: int, value: int) -> None:
        channel = _validate_channel(channel)
        device = self._resolve_device(channel)
        if not device.can_write():
            raise self._would_block_exc_type("out", channel)
        device.write(value)

    def queue_rx(self, channel: int, *values: int) -> None:
        self._resolve_device(channel).inject_rx(*values)

    def drain_tx(self, channel: int) -> list[int]:
        return self._resolve_device(channel).drain_tx()

    def rx_depth(self, channel: int) -> int:
        return self._resolve_device(channel).rx_depth()

    def tx_depth(self, channel: int) -> int:
        return self._resolve_device(channel).tx_depth()

    def bind_device(self, device: PeripheralDevice) -> None:
        channel = _validate_channel(device.channel)
        if channel in self._devices:
            raise ValueError(f"Channel 0x{channel:02X} is already bound")
        self._devices[channel] = device
        self._fallback_channels.pop(channel, None)

    def unbind_device(self, channel: int) -> PeripheralDevice | None:
        channel = _validate_channel(channel)
        return self._devices.pop(channel, None)

    def clear_devices(self) -> None:
        self._devices.clear()
        self._fallback_channels.clear()

    def reset_state(self) -> None:
        for device in self._devices.values():
            device.clear()
        self._fallback_channels.clear()

    def get_device(self, channel: int) -> PeripheralDevice | None:
        return self._devices.get(_validate_channel(channel))

    def devices(self) -> tuple[PeripheralDevice, ...]:
        return tuple(self._devices[channel] for channel in sorted(self._devices))

    def tick(self, elapsed_s: float) -> None:
        if elapsed_s < 0:
            raise ValueError("elapsed_s must be non-negative")
        for device in self._devices.values():
            device.tick(elapsed_s)

    def snapshot(self) -> dict[str, Any]:
        return {
            "devices": [device.snapshot() for device in self.devices()],
            "fallback_channels": {
                channel: {
                    "rx_depth": device.rx_depth(),
                    "tx_depth": device.tx_depth(),
                }
                for channel, device in sorted(self._fallback_channels.items())
                if device.rx_depth() or device.tx_depth()
            },
        }

    def dump_config(self) -> PeripheralHubConfig:
        return PeripheralHubConfig(
            devices=tuple(device.to_config() for device in self.devices()),
        )

    def dump_config_dict(self) -> dict[str, Any]:
        return self.dump_config().to_dict()

    def load_config(self, config: PeripheralHubConfig | dict[str, Any]) -> None:
        parsed = config if isinstance(config, PeripheralHubConfig) else PeripheralHubConfig.from_dict(config)
        seen_names: set[str] = set()
        new_devices: dict[int, PeripheralDevice] = {}
        for entry in parsed.devices:
            if entry.name in seen_names:
                raise ValueError(f"Duplicate peripheral name {entry.name!r}")
            seen_names.add(entry.name)
            device = make_device_from_config(entry)
            if device.channel in new_devices:
                raise ValueError(f"Channel 0x{device.channel:02X} is already bound")
            new_devices[device.channel] = device
        self._devices = new_devices
        self._fallback_channels.clear()

    def _resolve_device(self, channel: int) -> PeripheralDevice:
        channel = _validate_channel(channel)
        device = self._devices.get(channel)
        if device is not None:
            return device
        fallback = self._fallback_channels.get(channel)
        if fallback is None:
            fallback = FIFOChannelDevice(channel=channel, tx_capacity=self.tx_capacity)
            self._fallback_channels[channel] = fallback
        return fallback


def make_device_from_config(config: PeripheralConfigEntry) -> PeripheralDevice:
    options = dict(config.options)
    device_type = config.type
    if device_type == "ps2":
        return PS2KeyboardDevice(
            channel=config.channel,
            name=config.name,
            rx_depth=_optional_positive_int(options, "rx_depth", default=32),
            tx_depth=_optional_positive_int(options, "tx_depth", default=8),
        )
    if device_type == "audio8":
        sample_rate_hz = _optional_positive_int(options, "sample_rate_hz", default=16_000)
        return AudioOutputDevice(
            channel=config.channel,
            name=config.name,
            tx_depth=_optional_positive_int(options, "tx_depth", default=1024),
            sample_rate_hz=sample_rate_hz,
        )
    if device_type == "ws2812":
        return WS2812Device(
            channel=config.channel,
            name=config.name,
            tx_depth=_optional_positive_int(options, "tx_depth", default=192),
            width=_optional_positive_int(options, "width", default=8),
            height=_optional_positive_int(options, "height", default=8),
            color_order=str(options.get("color_order", "GRB")),
            serpentine=bool(options.get("serpentine", False)),
        )
    if device_type == "filo":
        return FILOStackDevice(
            channel=config.channel,
            name=config.name,
            depth=_optional_positive_int(options, "depth", default=32),
        )
    raise ValueError(f"Unknown peripheral device type {device_type!r}")


def _byte(value: int) -> int:
    return int(value) & 0xFF


def _validate_channel(value: int) -> int:
    channel = int(value)
    if not 0 <= channel <= 0xFF:
        raise ValueError(f"Channel {value!r} is outside 8-bit range")
    return channel


def _validate_capacity(value: int | None, name: str) -> int | None:
    if value is None:
        return None
    capacity = int(value)
    if capacity < 0:
        raise ValueError(f"{name} must be non-negative or None")
    return capacity


def _validate_positive_int(value: int, name: str) -> int:
    parsed = int(value)
    if parsed <= 0:
        raise ValueError(f"{name} must be positive")
    return parsed


def _optional_positive_int(options: dict[str, Any], name: str, *, default: int) -> int:
    value = options.get(name, default)
    return _validate_positive_int(value, name)


def _validate_color_order(value: str) -> str:
    order = str(value).upper()
    if len(order) != 3 or set(order) != {"R", "G", "B"}:
        raise ValueError("color_order must be a permutation of RGB")
    return order
