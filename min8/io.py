"""I/O backends for the Min8 reference simulator."""

from __future__ import annotations

from min8_shared.peripherals import (
    IOBlock,
    AudioOutputDevice,
    FIFOChannelDevice,
    FILOStackDevice,
    PS2KeyboardDevice,
    PeripheralConfigEntry,
    PeripheralDevice,
    PeripheralHubBase,
    PeripheralHubConfig,
    WS2812Device,
    make_device_from_config,
)

from .exceptions import WouldBlockOnIO


class FIFOIO(PeripheralHubBase):
    """Channel-indexed FIFO backend that matches the ISA I/O model."""

    def __init__(self, *, tx_capacity: int | None = None) -> None:
        super().__init__(would_block_exc_type=WouldBlockOnIO, tx_capacity=tx_capacity)


class PeripheralHub(FIFOIO):
    """Extended backend that can host richer per-channel peripherals."""


__all__ = [
    "AudioOutputDevice",
    "FIFOChannelDevice",
    "FIFOIO",
    "FILOStackDevice",
    "IOBlock",
    "PS2KeyboardDevice",
    "PeripheralConfigEntry",
    "PeripheralDevice",
    "PeripheralHub",
    "PeripheralHubConfig",
    "WS2812Device",
    "make_device_from_config",
]
