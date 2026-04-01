"""Simulator exceptions for the Min8-Pro ISA."""


class Min8ProError(Exception):
    """Base class for Min8-Pro simulator failures."""


class IllegalInstruction(Min8ProError):
    """Raised when the CPU encounters a reserved or invalid opcode."""

    def __init__(self, opcode: int, pc: int, message: str | None = None) -> None:
        self.opcode = opcode & 0xFF
        self.pc = pc & 0xFFFF
        detail = message or "Illegal instruction"
        super().__init__(f"{detail}: opcode=0x{self.opcode:02X} at pc=0x{self.pc:04X}")


class MachineHalted(Min8ProError):
    """Raised when stepping a CPU that has already executed HALT."""


class WouldBlockOnIO(Min8ProError):
    """Internal signal used by I/O backends to model architectural blocking."""

    def __init__(self, direction: str, channel: int) -> None:
        self.direction = direction
        self.channel = channel & 0xFF
        super().__init__(f"I/O would block on {direction} channel 0x{self.channel:02X}")
