"""Simulator exceptions for the Min8 ISA."""


class Min8Error(Exception):
    """Base class for Min8 simulator failures."""


class IllegalInstruction(Min8Error):
    """Raised when the CPU encounters a reserved or invalid opcode."""

    def __init__(self, opcode: int, pc: int, message: str | None = None) -> None:
        self.opcode = opcode & 0xFF
        self.pc = pc & 0xFF
        detail = message or "Illegal instruction"
        super().__init__(f"{detail}: opcode=0x{self.opcode:02X} at pc=0x{self.pc:02X}")


class MachineHalted(Min8Error):
    """Raised when stepping a CPU that has already executed HALT."""


class WouldBlockOnIO(Min8Error):
    """Internal signal used by I/O backends to model architectural blocking."""

    def __init__(self, direction: str, channel: int) -> None:
        self.direction = direction
        self.channel = channel & 0xFF
        super().__init__(f"I/O would block on {direction} channel 0x{self.channel:02X}")
