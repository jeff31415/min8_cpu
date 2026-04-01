"""Reference Min8-Pro instruction interpreter."""

from __future__ import annotations

from dataclasses import dataclass, field

from .exceptions import IllegalInstruction, MachineHalted, WouldBlockOnIO
from .io import FIFOIO, IOBlock
from .isa import DecodedInstruction, decode_opcode, register_name


@dataclass(frozen=True)
class RegisterWrite:
    index: int
    before: int
    after: int

    @property
    def name(self) -> str:
        return register_name(self.index)


@dataclass(frozen=True)
class MemoryWrite:
    address: int
    before: int
    after: int


@dataclass(frozen=True)
class IOTransfer:
    direction: str
    channel: int
    value: int | None = None


@dataclass(frozen=True)
class StepResult:
    status: str
    pc_before: int
    opcode: int
    instruction_text: str
    next_pc: int
    register_writes: tuple[RegisterWrite, ...] = ()
    memory_writes: tuple[MemoryWrite, ...] = ()
    z_before: int = 0
    z_after: int = 0
    c_before: int = 0
    c_after: int = 0
    iosel_before: int = 0
    iosel_after: int = 0
    ext16_before: int = 0
    ext16_after: int = 0
    r0sel_before: int = 0
    r0sel_after: int = 0
    r7sel_before: int = 0
    r7sel_after: int = 0
    io_transfer: IOTransfer | None = None
    blocked_on: IOBlock | None = None

    @property
    def retired(self) -> bool:
        return self.status in {"retired", "halted"}


@dataclass
class PendingInstruction:
    pc_before: int
    opcode: int
    decoded: DecodedInstruction


@dataclass
class CPUState:
    registers: list[int] = field(default_factory=lambda: [0] * 8)
    memory: bytearray = field(default_factory=lambda: bytearray(65536))
    pc: int = 0
    z: int = 0
    c: int = 0
    iosel: int = 0
    ext16: int = 0
    r0_sel: int = 0
    r7_sel: int = 0
    halted: bool = False
    pending: PendingInstruction | None = None
    retired_count: int = 0


class Min8ProCPU:
    """Reference instruction-level simulator for the Min8-Pro ISA."""

    def __init__(self, *, io_backend: FIFOIO | None = None) -> None:
        self.io = io_backend or FIFOIO()
        self.state = CPUState()

    def reset(self, *, clear_memory: bool = False) -> None:
        self.state.registers[:] = [0] * 8
        self.state.pc = 0
        self.state.z = 0
        self.state.c = 0
        self.state.iosel = 0
        self.state.ext16 = 0
        self.state.r0_sel = 0
        self.state.r7_sel = 0
        self.state.halted = False
        self.state.pending = None
        self.state.retired_count = 0
        if clear_memory:
            self.state.memory[:] = bytes(65536)

    def load_image(self, image: bytes | bytearray | list[int], *, start: int = 0) -> None:
        data = bytes(image)
        if len(data) > 65536:
            raise ValueError("Image is larger than Min8-Pro address space")
        base = start & 0xFFFF
        for offset, value in enumerate(data):
            self.state.memory[(base + offset) & 0xFFFF] = value

    def step(self) -> StepResult:
        if self.state.halted:
            raise MachineHalted("CPU is halted; reset before stepping again")

        if self.state.pending is None:
            pc_before = self.state.pc & 0xFFFF
            fetch_address = self._current_fetch_address()
            opcode = self.state.memory[fetch_address]
            self._increment_pc_for_fetch()
            decoded = decode_opcode(opcode, pc=pc_before)
            pending = PendingInstruction(pc_before=pc_before, opcode=opcode, decoded=decoded)
        else:
            pending = self.state.pending

        result = self._execute_pending(pending)
        if result.retired:
            self.state.pending = None
            self.state.retired_count += 1
        else:
            self.state.pending = pending
        return result

    def run(self, *, max_steps: int | None = None) -> list[StepResult]:
        results: list[StepResult] = []
        retired = 0
        while max_steps is None or retired < max_steps:
            result = self.step()
            results.append(result)
            if result.retired:
                retired += 1
            if result.status != "retired":
                break
        return results

    def _execute_pending(self, pending: PendingInstruction) -> StepResult:
        instruction = pending.decoded
        z_before = self.state.z
        c_before = self.state.c
        iosel_before = self.state.iosel
        ext16_before = self.state.ext16
        r0sel_before = self.state.r0_sel
        r7sel_before = self.state.r7_sel

        register_writes: list[RegisterWrite] = []
        memory_writes: list[MemoryWrite] = []
        io_transfer: IOTransfer | None = None

        if instruction.family == "mov":
            assert instruction.dest is not None
            assert instruction.src is not None
            self._write_register_byte(instruction.dest, self._read_register_byte(instruction.src), register_writes)
            status = "retired"

        elif instruction.family == "mem_ctrl":
            assert instruction.register is not None
            reg = instruction.register
            if instruction.mnemonic == "ST":
                self._store(self._address_r7(), self._read_register_byte(reg), memory_writes)
            elif instruction.mnemonic == "LD":
                self._write_register_byte(reg, self.state.memory[self._address_r7()], register_writes)
            elif instruction.mnemonic == "JMP":
                self.state.pc = self._jump_target(reg)
            elif instruction.mnemonic == "JZ":
                if self.state.z:
                    self.state.pc = self._jump_target(reg)
            elif instruction.mnemonic == "JC":
                if self.state.c:
                    self.state.pc = self._jump_target(reg)
            elif instruction.mnemonic == "JNZ":
                if not self.state.z:
                    self.state.pc = self._jump_target(reg)
            elif instruction.mnemonic == "ST+":
                self._store(self._address_r7(), self._read_register_byte(reg), memory_writes)
                self._increment_r7(register_writes)
            elif instruction.mnemonic == "LD+":
                self._write_register_byte(reg, self.state.memory[self._address_r7()], register_writes)
                self._increment_r7(register_writes)
            else:
                raise AssertionError(f"Unhandled mem/control mnemonic {instruction.mnemonic}")
            status = "retired"

        elif instruction.family == "ldi":
            assert instruction.imm4 is not None
            assert instruction.ldi_target is not None
            current = self._read_register_byte(instruction.ldi_target)
            if instruction.ldi_high:
                value = ((instruction.imm4 & 0x0F) << 4) | (current & 0x0F)
            else:
                value = instruction.imm4 & 0x0F
            self._write_register_byte(instruction.ldi_target, value, register_writes)
            status = "retired"

        elif instruction.family == "alu":
            value, carry = self._execute_alu(instruction)
            self._write_register_byte(0, value, register_writes)
            self.state.z = int(value == 0)
            self.state.c = carry
            status = "retired"

        elif instruction.family == "selector":
            if not self.state.ext16:
                raise IllegalInstruction(
                    opcode=pending.opcode,
                    pc=pending.pc_before,
                    message="Selector instruction requires EXT16",
                )
            if instruction.mnemonic == "R0L":
                self.state.r0_sel = 0
            elif instruction.mnemonic == "R0H":
                self.state.r0_sel = 1
            elif instruction.mnemonic == "R7L":
                self.state.r7_sel = 0
            elif instruction.mnemonic == "R7H":
                self.state.r7_sel = 1
            else:
                raise AssertionError(f"Unhandled selector mnemonic {instruction.mnemonic}")
            status = "retired"

        elif instruction.family == "io":
            assert instruction.register is not None
            reg = instruction.register
            channel = self.state.iosel
            value = self._read_register_byte(reg)
            try:
                if instruction.mnemonic == "SETIO":
                    self.state.iosel = value
                elif instruction.mnemonic == "GETIO":
                    self._write_register_byte(reg, self.state.iosel, register_writes)
                elif instruction.mnemonic == "IN":
                    if channel == 0xFF:
                        raise IllegalInstruction(
                            opcode=pending.opcode,
                            pc=pending.pc_before,
                            message="IN on system control port is illegal",
                        )
                    read_value = self.io.read(channel)
                    self._write_register_byte(reg, read_value, register_writes)
                    io_transfer = IOTransfer("in", channel, read_value)
                elif instruction.mnemonic == "OUT":
                    if channel == 0xFF:
                        self._handle_system_out(value, pending)
                        io_transfer = IOTransfer("system", channel, value)
                    else:
                        self.io.write(channel, value)
                        io_transfer = IOTransfer("out", channel, value)
                else:
                    raise AssertionError(f"Unhandled I/O mnemonic {instruction.mnemonic}")
            except WouldBlockOnIO as exc:
                return StepResult(
                    status="blocked",
                    pc_before=pending.pc_before,
                    opcode=pending.opcode,
                    instruction_text=instruction.instruction_text,
                    next_pc=self.state.pc,
                    z_before=z_before,
                    z_after=self.state.z,
                    c_before=c_before,
                    c_after=self.state.c,
                    iosel_before=iosel_before,
                    iosel_after=self.state.iosel,
                    ext16_before=ext16_before,
                    ext16_after=self.state.ext16,
                    r0sel_before=r0sel_before,
                    r0sel_after=self.state.r0_sel,
                    r7sel_before=r7sel_before,
                    r7sel_after=self.state.r7_sel,
                    blocked_on=IOBlock(exc.direction, exc.channel),
                )
            status = "retired"

        elif instruction.family == "control":
            if instruction.mnemonic != "HALT":
                raise AssertionError(f"Unhandled control mnemonic {instruction.mnemonic}")
            self.state.halted = True
            status = "halted"

        else:
            raise AssertionError(f"Unhandled instruction family {instruction.family}")

        return StepResult(
            status=status,
            pc_before=pending.pc_before,
            opcode=pending.opcode,
            instruction_text=instruction.instruction_text,
            next_pc=self.state.pc,
            register_writes=tuple(register_writes),
            memory_writes=tuple(memory_writes),
            z_before=z_before,
            z_after=self.state.z,
            c_before=c_before,
            c_after=self.state.c,
            iosel_before=iosel_before,
            iosel_after=self.state.iosel,
            ext16_before=ext16_before,
            ext16_after=self.state.ext16,
            r0sel_before=r0sel_before,
            r0sel_after=self.state.r0_sel,
            r7sel_before=r7sel_before,
            r7sel_after=self.state.r7_sel,
            io_transfer=io_transfer,
        )

    def _current_fetch_address(self) -> int:
        if self.state.ext16:
            return self.state.pc & 0xFFFF
        return self.state.pc & 0x00FF

    def _increment_pc_for_fetch(self) -> None:
        if self.state.ext16:
            self.state.pc = (self.state.pc + 1) & 0xFFFF
        else:
            self.state.pc = (self.state.pc + 1) & 0x00FF

    def _selector_for_register(self, index: int) -> int:
        if index == 0:
            return self.state.r0_sel if self.state.ext16 else 0
        if index == 7:
            return self.state.r7_sel if self.state.ext16 else 0
        return 0

    def _read_register_byte(self, index: int) -> int:
        value = self.state.registers[index]
        if index in {0, 7}:
            if self._selector_for_register(index):
                return (value >> 8) & 0xFF
            return value & 0xFF
        return value & 0xFF

    def _read_register_full(self, index: int) -> int:
        value = self.state.registers[index]
        if index in {0, 7}:
            return value & 0xFFFF
        return value & 0x00FF

    def _write_register_byte(self, index: int, value: int, writes: list[RegisterWrite]) -> None:
        before = self.state.registers[index]
        byte_value = value & 0xFF
        if index in {0, 7}:
            if self._selector_for_register(index):
                after = ((byte_value << 8) | (before & 0x00FF)) & 0xFFFF
            else:
                after = ((before & 0xFF00) | byte_value) & 0xFFFF
        else:
            after = byte_value
        self.state.registers[index] = after
        writes.append(RegisterWrite(index=index, before=before, after=after))

    def _write_register_full(self, index: int, value: int, writes: list[RegisterWrite]) -> None:
        before = self.state.registers[index]
        if index in {0, 7}:
            after = value & 0xFFFF
        else:
            after = value & 0xFF
        self.state.registers[index] = after
        writes.append(RegisterWrite(index=index, before=before, after=after))

    def _address_r7(self) -> int:
        if self.state.ext16:
            return self.state.registers[7] & 0xFFFF
        return self.state.registers[7] & 0x00FF

    def _increment_r7(self, writes: list[RegisterWrite]) -> None:
        before = self.state.registers[7]
        if self.state.ext16:
            after = (before + 1) & 0xFFFF
        else:
            after = (before & 0xFF00) | ((before + 1) & 0x00FF)
        self.state.registers[7] = after
        writes.append(RegisterWrite(index=7, before=before, after=after))

    def _jump_target(self, index: int) -> int:
        if self.state.ext16 and index in {0, 7}:
            return self._read_register_full(index)
        low_target = self._read_register_byte(index)
        if self.state.ext16:
            return ((self.state.pc & 0xFF00) | low_target) & 0xFFFF
        return low_target

    def _handle_system_out(self, value: int, pending: PendingInstruction) -> None:
        if value == 0x01:
            self.state.ext16 = 1
            return
        raise IllegalInstruction(
            opcode=pending.opcode,
            pc=pending.pc_before,
            message=f"Unsupported system control value 0x{value:02X}",
        )

    def _store(self, address: int, value: int, writes: list[MemoryWrite]) -> None:
        masked_address = address & 0xFFFF
        masked_value = value & 0xFF
        before = self.state.memory[masked_address]
        self.state.memory[masked_address] = masked_value
        writes.append(MemoryWrite(address=masked_address, before=before, after=masked_value))

    def _execute_alu(self, instruction: DecodedInstruction) -> tuple[int, int]:
        r1 = self.state.registers[1] & 0xFF
        r2 = self.state.registers[2] & 0xFF
        carry_in = self.state.c & 0x01
        mnemonic = instruction.mnemonic
        bit_mask = 1 << (r2 & 0x07)

        if mnemonic == "ADD":
            total = r1 + r2
            return total & 0xFF, int(total > 0xFF)
        if mnemonic == "SUB":
            return (r1 - r2) & 0xFF, int(r1 < r2)
        if mnemonic == "AND":
            return r1 & r2, 0
        if mnemonic == "OR":
            return r1 | r2, 0
        if mnemonic == "XOR":
            return r1 ^ r2, 0
        if mnemonic == "NOT":
            return (~r1) & 0xFF, 0
        if mnemonic == "SHL":
            return (r1 << 1) & 0xFF, (r1 >> 7) & 0x01
        if mnemonic == "SHR":
            return (r1 >> 1) & 0xFF, r1 & 0x01
        if mnemonic == "INC":
            return (r1 + 1) & 0xFF, int(r1 == 0xFF)
        if mnemonic == "DEC":
            return (r1 - 1) & 0xFF, int(r1 == 0x00)
        if mnemonic == "SHR2":
            return (r1 >> 2) & 0xFF, (r1 >> 1) & 0x01
        if mnemonic == "SHR3":
            return (r1 >> 3) & 0xFF, (r1 >> 2) & 0x01
        if mnemonic == "SHL2":
            return (r1 << 2) & 0xFF, (r1 >> 6) & 0x01
        if mnemonic == "SHL3":
            return (r1 << 3) & 0xFF, (r1 >> 5) & 0x01
        if mnemonic == "BSET":
            return r1 | bit_mask, 0
        if mnemonic == "BCLR":
            return r1 & (~bit_mask & 0xFF), 0
        if mnemonic == "BTGL":
            return r1 ^ bit_mask, 0
        if mnemonic == "BTST":
            return r1 & bit_mask, 0
        if mnemonic == "MASK3":
            return r1 & 0x07, 0
        if mnemonic == "MASK4":
            return r1 & 0x0F, 0
        if mnemonic == "ADC":
            total = r1 + r2 + carry_in
            return total & 0xFF, int(total > 0xFF)
        if mnemonic == "SBB":
            subtrahend = r2 + carry_in
            return (r1 - subtrahend) & 0xFF, int(r1 < subtrahend)
        raise AssertionError(f"Unhandled ALU mnemonic {mnemonic}")


Min8CPU = Min8ProCPU
