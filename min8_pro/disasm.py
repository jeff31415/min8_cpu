"""Disassembler helpers for the Min8-Pro ISA."""

from __future__ import annotations

from dataclasses import dataclass

from .exceptions import IllegalInstruction
from .isa import decode_opcode


@dataclass(frozen=True)
class DisassemblyLine:
    address: int
    opcode: int
    text: str
    symbol: str | None = None
    illegal: bool = False


def disassemble_image(
    image: bytes | bytearray | list[int],
    *,
    addresses: list[int] | tuple[int, ...] | range | None = None,
    symbols: dict[str, int] | None = None,
) -> tuple[DisassemblyLine, ...]:
    memory = bytes(image)
    if len(memory) > 65536:
        raise ValueError("image is larger than Min8-Pro address space")

    if addresses is None:
        target_addresses = range(len(memory))
    else:
        target_addresses = addresses

    address_to_symbol: dict[int, list[str]] = {}
    if symbols:
        for name, address in symbols.items():
            address_to_symbol.setdefault(address & 0xFFFF, []).append(name)

    lines: list[DisassemblyLine] = []
    seen: set[int] = set()
    for raw_address in target_addresses:
        address = raw_address & 0xFFFF
        if address in seen or address >= len(memory):
            continue
        seen.add(address)
        opcode = memory[address]
        symbol_names = address_to_symbol.get(address)
        symbol = ", ".join(sorted(symbol_names)) if symbol_names else None
        try:
            decoded = decode_opcode(opcode, pc=address)
            text = decoded.instruction_text
            illegal = False
        except IllegalInstruction:
            text = f".byte 0x{opcode:02X} ; illegal"
            illegal = True
        lines.append(
            DisassemblyLine(
                address=address,
                opcode=opcode,
                text=text,
                symbol=symbol,
                illegal=illegal,
            )
        )
    return tuple(sorted(lines, key=lambda line: line.address))


def format_disassembly(lines: tuple[DisassemblyLine, ...] | list[DisassemblyLine]) -> str:
    rows: list[str] = []
    for line in lines:
        suffix = f"    ; {line.symbol}" if line.symbol else ""
        rows.append(f"{line.address:04X}: {line.opcode:02X}  {line.text}{suffix}")
    return "\n".join(rows) + ("\n" if rows else "")
