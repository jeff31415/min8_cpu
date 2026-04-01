"""I/O backends for the Min8 reference simulator."""

from __future__ import annotations

from collections import defaultdict, deque
from dataclasses import dataclass

from .exceptions import WouldBlockOnIO


@dataclass(frozen=True)
class IOBlock:
    direction: str
    channel: int


class FIFOIO:
    """Channel-indexed FIFO backend that matches the ISA I/O model."""

    def __init__(self, *, tx_capacity: int | None = None) -> None:
        if tx_capacity is not None and tx_capacity < 0:
            raise ValueError("tx_capacity must be non-negative or None")
        self.tx_capacity = tx_capacity
        self._rx: dict[int, deque[int]] = defaultdict(deque)
        self._tx: dict[int, deque[int]] = defaultdict(deque)

    def can_read(self, channel: int) -> bool:
        return bool(self._rx[channel & 0xFF])

    def can_write(self, channel: int) -> bool:
        if self.tx_capacity is None:
            return True
        return len(self._tx[channel & 0xFF]) < self.tx_capacity

    def read(self, channel: int) -> int:
        channel &= 0xFF
        if not self.can_read(channel):
            raise WouldBlockOnIO("in", channel)
        return self._rx[channel].popleft()

    def write(self, channel: int, value: int) -> None:
        channel &= 0xFF
        if not self.can_write(channel):
            raise WouldBlockOnIO("out", channel)
        self._tx[channel].append(value & 0xFF)

    def queue_rx(self, channel: int, *values: int) -> None:
        channel &= 0xFF
        fifo = self._rx[channel]
        for value in values:
            fifo.append(value & 0xFF)

    def drain_tx(self, channel: int) -> list[int]:
        channel &= 0xFF
        fifo = self._tx[channel]
        values = list(fifo)
        fifo.clear()
        return values

    def rx_depth(self, channel: int) -> int:
        return len(self._rx[channel & 0xFF])

    def tx_depth(self, channel: int) -> int:
        return len(self._tx[channel & 0xFF])
