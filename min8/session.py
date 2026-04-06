"""Debugger/session helpers shared by the CLI workflow and GUI."""

from __future__ import annotations

from dataclasses import dataclass, field
from pathlib import Path

from .asm import AssemblyResult, ListingLine, assemble_file, assemble_source
from .cpu import Min8CPU, StepResult
from .disasm import DisassemblyLine, disassemble_image, format_disassembly
from .exceptions import IllegalInstruction, MachineHalted
from .io import PeripheralHub, PeripheralHubConfig
from .isa import REGISTER_INDEX


@dataclass
class LoadedProgram:
    image: bytes
    description: str
    assembly: AssemblyResult | None = None
    source_text: str = ""
    source_path: Path | None = None
    disassembly_lines: tuple[DisassemblyLine, ...] = ()
    source_line_to_address: dict[int, int] = field(default_factory=dict)
    address_to_source_line: dict[int, int] = field(default_factory=dict)
    disassembly_line_to_address: dict[int, int] = field(default_factory=dict)
    address_to_disassembly_line: dict[int, int] = field(default_factory=dict)


class Min8Session:
    """High-level state manager for running Min8 programs interactively."""

    def __init__(self, *, tx_capacity: int | None = None) -> None:
        self.io = PeripheralHub(tx_capacity=tx_capacity)
        self.cpu = Min8CPU(io_backend=self.io)
        self.loaded_program: LoadedProgram | None = None
        self.last_result: StepResult | None = None
        self.last_error: Exception | None = None
        self.last_stop_reason: str | None = None
        self.last_stop_address: int | None = None
        self.breakpoints: set[int] = set()
        self.last_register_changes: set[int] = set()
        self.last_memory_changes: set[int] = set()
        self.last_special_changes: set[str] = set()

    def load_source(self, source_text: str, *, source_name: str = "<string>") -> AssemblyResult:
        assembly = assemble_source(source_text, source_name=source_name)
        self.loaded_program = self._build_loaded_program(
            image=assembly.image,
            description=source_name,
            assembly=assembly,
            source_text=source_text,
            source_path=None,
        )
        self.breakpoints.clear()
        self.reset()
        return assembly

    def load_assembly_file(self, path: str | Path) -> AssemblyResult:
        source_path = Path(path)
        source_text = source_path.read_text(encoding="utf-8")
        assembly = assemble_file(source_path)
        self.loaded_program = self._build_loaded_program(
            image=assembly.image,
            description=str(source_path),
            assembly=assembly,
            source_text=source_text,
            source_path=source_path,
        )
        self.breakpoints.clear()
        self.reset()
        return assembly

    def load_image_file(self, path: str | Path) -> None:
        image_path = Path(path)
        image = image_path.read_bytes()
        if len(image) > 256:
            raise ValueError("Binary image is larger than 256 bytes")
        padded = image + bytes(256 - len(image))
        self.loaded_program = self._build_loaded_program(
            image=padded,
            description=str(image_path),
            assembly=None,
            source_text="",
            source_path=image_path,
        )
        self.breakpoints.clear()
        self.reset()

    def reset(self) -> None:
        self.cpu.reset(clear_memory=True)
        self.io.reset_state()
        if self.loaded_program is not None:
            self.cpu.load_image(self.loaded_program.image)
        self.last_result = None
        self.last_error = None
        self.last_stop_reason = None
        self.last_stop_address = None
        self._clear_change_highlights()

    def step(self) -> StepResult:
        self.last_error = None
        self.last_stop_reason = None
        self.last_stop_address = None
        try:
            self.last_result = self.cpu.step()
            self._record_step_changes(self.last_result)
            return self.last_result
        except (IllegalInstruction, MachineHalted) as exc:
            self.last_error = exc
            self.last_stop_reason = "error"
            self.last_stop_address = self.current_address
            raise

    def run_batch(self, *, max_steps: int = 100) -> list[StepResult]:
        results: list[StepResult] = []
        self.last_error = None

        for _ in range(max_steps):
            if self.current_address in self.breakpoints:
                self.last_stop_reason = "breakpoint"
                self.last_stop_address = self.current_address
                return results

            result = self.step()
            results.append(result)
            if result.status == "blocked":
                self.last_stop_reason = "blocked"
                self.last_stop_address = self.current_address
                return results
            if result.status == "halted":
                self.last_stop_reason = "halted"
                self.last_stop_address = result.pc_before
                return results

        self.last_stop_reason = "max_steps"
        self.last_stop_address = self.current_address
        return results

    def queue_rx(self, channel: int, values: list[int]) -> None:
        self.io.queue_rx(channel, *values)

    def drain_tx(self, channel: int) -> list[int]:
        return self.io.drain_tx(channel)

    def tick_io(self, elapsed_s: float) -> None:
        self.io.tick(elapsed_s)

    def load_peripheral_config(self, config: PeripheralHubConfig | dict[str, object]) -> None:
        self.io.load_config(config)

    def dump_peripheral_config(self) -> PeripheralHubConfig:
        return self.io.dump_config()

    def set_breakpoint(self, address: int) -> None:
        self.breakpoints.add(address & 0xFF)

    def clear_breakpoint(self, address: int) -> None:
        self.breakpoints.discard(address & 0xFF)

    def toggle_breakpoint(self, address: int) -> bool:
        address &= 0xFF
        if address in self.breakpoints:
            self.breakpoints.remove(address)
            return False
        self.breakpoints.add(address)
        return True

    def clear_breakpoints(self) -> None:
        self.breakpoints.clear()

    def edit_state(self, target: str, value: int) -> None:
        normalized = target.upper()
        value &= 0xFF
        self.last_result = None
        self.last_error = None
        self.last_stop_reason = None
        self.last_stop_address = None
        self._clear_change_highlights()

        if normalized in REGISTER_INDEX:
            self.cpu.state.registers[REGISTER_INDEX[normalized]] = value
            self.last_register_changes.add(REGISTER_INDEX[normalized])
            return

        if normalized == "PC":
            self.cpu.state.pc = value
            self.last_special_changes.add("PC")
            return

        if normalized == "IOSEL":
            self.cpu.state.iosel = value
            self.last_special_changes.add("IOSEL")
            return

        if normalized in {"Z", "C"}:
            self.cpu.state.__dict__[normalized.lower()] = int(bool(value))
            self.last_special_changes.add(normalized)
            return

        raise ValueError(f"Unknown editable state field {target!r}")

    def edit_memory(self, address: int, value: int) -> None:
        self.last_result = None
        self.last_error = None
        self.last_stop_reason = None
        self.last_stop_address = None
        self._clear_change_highlights()
        address &= 0xFF
        self.cpu.state.memory[address] = value & 0xFF
        self.last_memory_changes.add(address)

    @property
    def current_address(self) -> int:
        pending = self.cpu.state.pending
        if pending is not None:
            return pending.pc_before
        if self.last_result is not None and self.last_result.status == "halted":
            return self.last_result.pc_before
        return self.cpu.state.pc

    @property
    def source_text(self) -> str:
        if self.loaded_program and self.loaded_program.source_text:
            return self.loaded_program.source_text
        return "; no assembly source loaded\n"

    @property
    def disassembly_text(self) -> str:
        if self.loaded_program:
            return format_disassembly(self.loaded_program.disassembly_lines)
        return format_disassembly(disassemble_image(self.cpu.state.memory))

    def source_line_for_address(self, address: int) -> int | None:
        if self.loaded_program is None:
            return None
        return self.loaded_program.address_to_source_line.get(address & 0xFF)

    def source_address_for_line(self, line_number: int) -> int | None:
        if self.loaded_program is None:
            return None
        return self.loaded_program.source_line_to_address.get(line_number)

    def disassembly_line_for_address(self, address: int) -> int | None:
        if self.loaded_program is None:
            return None
        return self.loaded_program.address_to_disassembly_line.get(address & 0xFF)

    def disassembly_address_for_line(self, line_number: int) -> int | None:
        if self.loaded_program is None:
            return None
        return self.loaded_program.disassembly_line_to_address.get(line_number)

    def memory_dump(self) -> str:
        lines: list[str] = []
        for row in range(0, 256, 16):
            chunk = self.cpu.state.memory[row : row + 16]
            lines.append(f"{row:02X}: " + " ".join(f"{value:02X}" for value in chunk))
        return "\n".join(lines) + "\n"

    def _build_loaded_program(
        self,
        *,
        image: bytes,
        description: str,
        assembly: AssemblyResult | None,
        source_text: str,
        source_path: Path | None,
    ) -> LoadedProgram:
        if assembly is not None and assembly.used_addresses:
            disassembly_lines = disassemble_image(image, addresses=assembly.used_addresses, symbols=assembly.symbols)
            source_line_to_address, address_to_source_line = self._build_source_maps(assembly.listing)
        else:
            disassembly_lines = disassemble_image(image, addresses=range(256))
            source_line_to_address = {}
            address_to_source_line = {}

        disassembly_line_to_address = {
            line_number: line.address for line_number, line in enumerate(disassembly_lines, start=1)
        }
        address_to_disassembly_line = {
            line.address: line_number for line_number, line in enumerate(disassembly_lines, start=1)
        }
        return LoadedProgram(
            image=image,
            description=description,
            assembly=assembly,
            source_text=source_text,
            source_path=source_path,
            disassembly_lines=disassembly_lines,
            source_line_to_address=source_line_to_address,
            address_to_source_line=address_to_source_line,
            disassembly_line_to_address=disassembly_line_to_address,
            address_to_disassembly_line=address_to_disassembly_line,
        )

    def _build_source_maps(self, listing: tuple[ListingLine, ...]) -> tuple[dict[int, int], dict[int, int]]:
        source_line_to_address: dict[int, int] = {}
        address_to_source_line: dict[int, int] = {}
        for entry in listing:
            if entry.address is None or not entry.bytes_out:
                continue
            source_line_to_address.setdefault(entry.line_number, entry.address)
            for offset in range(len(entry.bytes_out)):
                address_to_source_line[(entry.address + offset) & 0xFF] = entry.line_number
        return source_line_to_address, address_to_source_line

    def _clear_change_highlights(self) -> None:
        self.last_register_changes.clear()
        self.last_memory_changes.clear()
        self.last_special_changes.clear()

    def _record_step_changes(self, result: StepResult) -> None:
        self._clear_change_highlights()
        self.last_register_changes.update(write.index for write in result.register_writes)
        self.last_memory_changes.update(write.address for write in result.memory_writes)

        if result.z_before != result.z_after:
            self.last_special_changes.add("Z")
        if result.c_before != result.c_after:
            self.last_special_changes.add("C")
        if result.iosel_before != result.iosel_after:
            self.last_special_changes.add("IOSEL")
        if result.status == "blocked":
            self.last_special_changes.add("Pending")

        sequential_next = (result.pc_before + 1) & 0xFF
        if result.next_pc != sequential_next:
            self.last_special_changes.add("PC")
