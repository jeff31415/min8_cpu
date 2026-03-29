"""Assembler for the Min8 ISA."""

from __future__ import annotations

import argparse
import ast
import json
import re
import sys
from dataclasses import dataclass
from pathlib import Path

from .isa import (
    ALU_OPCODE_BY_MNEMONIC,
    IO_OPCODE_BASE,
    LDI_OPCODE_BASE,
    MEM_CTRL_OPCODE_BASE,
    REGISTER_INDEX,
)

SYMBOL_RE = re.compile(r"[A-Za-z_.$][A-Za-z0-9_.$]*")
LABEL_PREFIX_RE = re.compile(r"\s*([A-Za-z_.$][A-Za-z0-9_.$]*):")

COMMUTATIVE_BINARY_ALU = {"ADD", "AND", "OR", "XOR", "ADC"}
BINARY_PSEUDO_ALU = {"ADD", "SUB", "AND", "OR", "XOR", "BSET", "BCLR", "BTGL", "BTST", "ADC", "SBB"}
UNARY_PSEUDO_ALU = {"NOT", "SHL", "SHR", "INC", "DEC", "SHR2", "SHR3", "SHL2", "SHL3", "MASK3", "MASK4"}


class AssemblerError(Exception):
    """Raised when Min8 assembly cannot be parsed or encoded."""

    def __init__(self, line: int, message: str, *, column: int | None = None) -> None:
        self.line = line
        self.column = column
        location = f"line {line}"
        if column is not None:
            location += f", column {column}"
        super().__init__(f"{location}: {message}")


@dataclass(frozen=True)
class ParsedLine:
    line_number: int
    source_text: str
    labels: tuple[str, ...]
    kind: str
    name: str | None
    args: tuple[str, ...]


@dataclass(frozen=True)
class ListingLine:
    line_number: int
    address: int | None
    bytes_out: tuple[int, ...]
    source_text: str


@dataclass(frozen=True)
class AssemblyResult:
    image: bytes
    symbols: dict[str, int]
    used_addresses: tuple[int, ...]
    entry_address: int
    listing: tuple[ListingLine, ...]


def assemble_source(source: str, *, source_name: str = "<string>") -> AssemblyResult:
    parsed_lines = _parse_source(source)
    symbols = _resolve_symbols(parsed_lines)
    image = bytearray(256)
    occupied = [False] * 256
    listing: list[ListingLine] = []
    location = 0

    for parsed in parsed_lines:
        if parsed.kind == "empty":
            listing.append(ListingLine(parsed.line_number, None, (), parsed.source_text))
            continue
        if parsed.kind == "directive" and parsed.name == ".EQU":
            listing.append(ListingLine(parsed.line_number, None, (), parsed.source_text))
            continue
        if parsed.kind == "directive" and parsed.name == ".ORG":
            location = _eval_address(parsed.args[0], symbols, parsed.line_number)
            listing.append(ListingLine(parsed.line_number, None, (), parsed.source_text))
            continue

        emitted: list[int]
        address = location
        if parsed.kind == "directive" and parsed.name == ".BYTE":
            emitted = [_eval_byte(expr, symbols, parsed.line_number) for expr in parsed.args]
        elif parsed.kind == "directive" and parsed.name == ".FILL":
            count = _eval_fill_count(parsed.args[0], symbols, parsed.line_number)
            value = _eval_byte(parsed.args[1], symbols, parsed.line_number) if len(parsed.args) == 2 else 0
            emitted = [value] * count
        else:
            emitted = _encode_instruction(parsed, symbols)

        if emitted:
            _emit_bytes(
                image=image,
                occupied=occupied,
                address=address,
                values=emitted,
                line_number=parsed.line_number,
            )
            location += len(emitted)
            if location > 256:
                raise AssemblerError(parsed.line_number, "program exceeds 256-byte address space")
            listing.append(ListingLine(parsed.line_number, address, tuple(emitted), parsed.source_text))
        else:
            listing.append(ListingLine(parsed.line_number, None, (), parsed.source_text))

    used_addresses = tuple(index for index, used in enumerate(occupied) if used)
    entry_address = used_addresses[0] if used_addresses else 0
    return AssemblyResult(
        image=bytes(image),
        symbols=symbols,
        used_addresses=used_addresses,
        entry_address=entry_address,
        listing=tuple(listing),
    )


def assemble_file(path: str | Path) -> AssemblyResult:
    source_path = Path(path)
    return assemble_source(source_path.read_text(encoding="utf-8"), source_name=str(source_path))


def format_listing(result: AssemblyResult) -> str:
    lines: list[str] = []
    for entry in result.listing:
        if entry.address is None:
            lines.append(f"      {'':<11} {entry.source_text}")
            continue
        bytes_text = " ".join(f"{value:02X}" for value in entry.bytes_out)
        lines.append(f"{entry.address:02X}:  {bytes_text:<11} {entry.source_text}")
    return "\n".join(lines) + ("\n" if lines else "")


def format_memh(image: bytes) -> str:
    return "\n".join(f"{value:02X}" for value in image) + "\n"


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="Assemble Min8 source code")
    parser.add_argument("source", help="input assembly source file")
    parser.add_argument("-o", "--output", help="output file path")
    parser.add_argument(
        "--format",
        choices=("bin", "memh"),
        default="bin",
        help="output encoding for the image",
    )
    parser.add_argument("--listing", help="write a listing file")
    parser.add_argument("--symbols", help="write a symbol table as JSON")
    args = parser.parse_args(argv)

    source_path = Path(args.source)
    try:
        result = assemble_file(source_path)
    except (OSError, AssemblerError) as exc:
        print(exc, file=sys.stderr)
        return 1

    output_path = Path(args.output) if args.output else _default_output_path(source_path, args.format)
    if args.format == "bin":
        output_path.write_bytes(result.image)
    else:
        output_path.write_text(format_memh(result.image), encoding="utf-8")

    if args.listing:
        Path(args.listing).write_text(format_listing(result), encoding="utf-8")
    if args.symbols:
        Path(args.symbols).write_text(json.dumps(result.symbols, indent=2, sort_keys=True) + "\n", encoding="utf-8")
    print(f"Wrote {args.format} image to {output_path}")
    return 0


def _default_output_path(source_path: Path, output_format: str) -> Path:
    suffix = ".bin" if output_format == "bin" else ".memh"
    return source_path.with_suffix(suffix)


def _parse_source(source: str) -> list[ParsedLine]:
    parsed_lines: list[ParsedLine] = []
    for line_number, raw_line in enumerate(source.splitlines(), start=1):
        source_text = raw_line.rstrip("\n")
        code = source_text.split(";", 1)[0]
        labels: list[str] = []

        while True:
            match = LABEL_PREFIX_RE.match(code)
            if match is None:
                break
            labels.append(match.group(1))
            code = code[match.end() :]

        code = code.strip()
        if not code:
            parsed_lines.append(
                ParsedLine(
                    line_number=line_number,
                    source_text=source_text,
                    labels=tuple(labels),
                    kind="empty",
                    name=None,
                    args=(),
                )
            )
            continue

        parts = code.split(None, 1)
        name = parts[0].upper()
        arg_text = parts[1] if len(parts) == 2 else ""
        args = tuple(arg.strip() for arg in arg_text.split(",") if arg.strip())

        kind = "directive" if name.startswith(".") else "instruction"
        parsed_lines.append(
            ParsedLine(
                line_number=line_number,
                source_text=source_text,
                labels=tuple(labels),
                kind=kind,
                name=name,
                args=args,
            )
        )
    return parsed_lines


def _resolve_symbols(parsed_lines: list[ParsedLine]) -> dict[str, int]:
    size_hints = {
        index: _conservative_instruction_size(parsed)
        for index, parsed in enumerate(parsed_lines)
        if parsed.kind == "instruction"
    }

    for _ in range(len(parsed_lines) + 1):
        symbols = _layout_with_sizes(parsed_lines, size_hints, allow_overflow=True)
        next_hints = {
            index: _instruction_size(parsed, symbols)
            for index, parsed in enumerate(parsed_lines)
            if parsed.kind == "instruction"
        }
        if next_hints == size_hints:
            return symbols
        size_hints = next_hints

    raise AssemblerError(1, "assembler layout failed to converge")


def _layout_with_sizes(
    parsed_lines: list[ParsedLine],
    size_hints: dict[int, int],
    *,
    allow_overflow: bool = False,
) -> dict[str, int]:
    symbols: dict[str, int] = {}
    location = 0

    for index, parsed in enumerate(parsed_lines):
        for label in parsed.labels:
            _define_symbol(symbols, label, location, parsed.line_number, wrap=not allow_overflow)

        if parsed.kind == "empty":
            continue

        if parsed.kind == "directive":
            assert parsed.name is not None
            if parsed.name == ".ORG":
                _require_arg_count(parsed, 1)
                location = _eval_address(parsed.args[0], symbols, parsed.line_number)
            elif parsed.name == ".BYTE":
                if not parsed.args:
                    raise AssemblerError(parsed.line_number, ".byte requires at least one expression")
                location = _advance_location(location, len(parsed.args), parsed.line_number)
            elif parsed.name == ".FILL":
                if len(parsed.args) not in {1, 2}:
                    raise AssemblerError(parsed.line_number, ".fill expects count or count,value")
                count = _eval_fill_count(parsed.args[0], symbols, parsed.line_number)
                location = _advance_location(location, count, parsed.line_number)
            elif parsed.name == ".EQU":
                if parsed.labels:
                    raise AssemblerError(parsed.line_number, "labels cannot appear on the same line as .equ")
                if len(parsed.args) != 2:
                    raise AssemblerError(parsed.line_number, ".equ expects name, expression")
                name = parsed.args[0]
                if not SYMBOL_RE.fullmatch(name):
                    raise AssemblerError(parsed.line_number, f"invalid symbol name {name!r}")
                value = _eval_address(parsed.args[1], symbols, parsed.line_number)
                _define_symbol(symbols, name, value, parsed.line_number, wrap=not allow_overflow)
            else:
                raise AssemblerError(parsed.line_number, f"unknown directive {parsed.name}")
            continue

        if allow_overflow:
            location += size_hints[index]
        else:
            location = _advance_location(location, size_hints[index], parsed.line_number)

    return symbols


def _conservative_instruction_size(parsed: ParsedLine) -> int:
    assert parsed.name is not None
    if parsed.name == "LI":
        _require_arg_count(parsed, 2)
        register = _parse_register(parsed.args[0], parsed.line_number)
        return 2 if register in {0, 7} else 3
    if parsed.name == "SETIOI":
        _require_arg_count(parsed, 1)
        return 3
    if parsed.name in BINARY_PSEUDO_ALU and len(parsed.args) == 3:
        return _alu_pseudo_size(parsed)
    if parsed.name in UNARY_PSEUDO_ALU and len(parsed.args) == 2:
        return _alu_pseudo_size(parsed)
    return 1


def _instruction_size(parsed: ParsedLine, symbols: dict[str, int]) -> int:
    assert parsed.name is not None
    if parsed.name == "LI":
        _require_arg_count(parsed, 2)
        register = _parse_register(parsed.args[0], parsed.line_number)
        value = _eval_byte(parsed.args[1], symbols, parsed.line_number)
        return 1 if register in {0, 7} and value < 0x10 else _conservative_instruction_size(parsed) - int(value < 0x10)
    if parsed.name == "SETIOI":
        _require_arg_count(parsed, 1)
        value = _eval_expr(parsed.args[0], symbols, parsed.line_number)
        if not 0 <= value <= 0xFF:
            return _conservative_instruction_size(parsed)
        return 2 if value < 0x10 else 3
    if parsed.name in BINARY_PSEUDO_ALU and len(parsed.args) == 3:
        return _alu_pseudo_size(parsed)
    if parsed.name in UNARY_PSEUDO_ALU and len(parsed.args) == 2:
        return _alu_pseudo_size(parsed)
    return 1


def _encode_instruction(parsed: ParsedLine, symbols: dict[str, int]) -> list[int]:
    assert parsed.name is not None
    name = parsed.name

    if name == "NOP":
        _require_arg_count(parsed, 0)
        return [0x00]

    if name == "MOV":
        _require_arg_count(parsed, 2)
        dest = _parse_register(parsed.args[0], parsed.line_number)
        src = _parse_register(parsed.args[1], parsed.line_number)
        return [((dest & 0x07) << 3) | (src & 0x07)]

    if name in MEM_CTRL_OPCODE_BASE:
        _require_arg_count(parsed, 1)
        register = _parse_register(parsed.args[0], parsed.line_number)
        if name == "LD+" and register == 7:
            raise AssemblerError(parsed.line_number, "LD+ R7 is invalid because 0x7F is HALT")
        return [MEM_CTRL_OPCODE_BASE[name] | register]

    if name == "HALT":
        _require_arg_count(parsed, 0)
        return [0x7F]

    if name in LDI_OPCODE_BASE:
        _require_arg_count(parsed, 1)
        imm4 = _eval_nibble(parsed.args[0], symbols, parsed.line_number)
        return [LDI_OPCODE_BASE[name] | imm4]

    if name in ALU_OPCODE_BY_MNEMONIC:
        if len(parsed.args) == 0:
            return [0xC0 | ALU_OPCODE_BY_MNEMONIC[name]]
        return _encode_alu_pseudo(parsed)

    if name in IO_OPCODE_BASE:
        _require_arg_count(parsed, 1)
        register = _parse_register(parsed.args[0], parsed.line_number)
        return [IO_OPCODE_BASE[name] | register]

    if name == "LI":
        _require_arg_count(parsed, 2)
        register = _parse_register(parsed.args[0], parsed.line_number)
        value = _eval_byte(parsed.args[1], symbols, parsed.line_number)
        return _encode_li(register, value)

    if name == "SETIOI":
        _require_arg_count(parsed, 1)
        value = _eval_byte(parsed.args[0], symbols, parsed.line_number)
        return _encode_li(0, value) + [IO_OPCODE_BASE["SETIO"]]

    raise AssemblerError(parsed.line_number, f"unknown instruction {name}")


def _encode_li(register: int, value: int) -> list[int]:
    value &= 0xFF
    low = value & 0x0F
    high = (value >> 4) & 0x0F
    small_immediate = value < 0x10
    if register == 0:
        opcodes = [LDI_OPCODE_BASE["LDI_L_R0"] | low]
        if not small_immediate:
            opcodes.append(LDI_OPCODE_BASE["LDI_H_R0"] | high)
        return opcodes
    if register == 7:
        opcodes = [LDI_OPCODE_BASE["LDI_L_R7"] | low]
        if not small_immediate:
            opcodes.append(LDI_OPCODE_BASE["LDI_H_R7"] | high)
        return opcodes
    opcodes = [LDI_OPCODE_BASE["LDI_L_R0"] | low]
    if not small_immediate:
        opcodes.append(LDI_OPCODE_BASE["LDI_H_R0"] | high)
    opcodes.append(register << 3)
    return opcodes


def _alu_pseudo_size(parsed: ParsedLine) -> int:
    return len(_encode_alu_pseudo(parsed))


def _encode_alu_pseudo(parsed: ParsedLine) -> list[int]:
    assert parsed.name is not None
    mnemonic = parsed.name

    if mnemonic in BINARY_PSEUDO_ALU and len(parsed.args) == 3:
        dest = _parse_register(parsed.args[0], parsed.line_number)
        src_a = _parse_register(parsed.args[1], parsed.line_number)
        src_b = _parse_register(parsed.args[2], parsed.line_number)
        return _encode_binary_alu_pseudo(mnemonic, dest, src_a, src_b)

    if mnemonic in UNARY_PSEUDO_ALU and len(parsed.args) == 2:
        dest = _parse_register(parsed.args[0], parsed.line_number)
        src = _parse_register(parsed.args[1], parsed.line_number)
        return _encode_unary_alu_pseudo(mnemonic, dest, src)

    expected = 3 if mnemonic in BINARY_PSEUDO_ALU else 2
    raise AssemblerError(parsed.line_number, f"{mnemonic} expects {expected} operand(s)")


def _encode_binary_alu_pseudo(mnemonic: str, dest: int, src_a: int, src_b: int) -> list[int]:
    candidates = [_plan_r1_r2_moves(src_a, src_b)]
    if mnemonic in COMMUTATIVE_BINARY_ALU and src_a != src_b:
        candidates.append(_plan_r1_r2_moves(src_b, src_a))

    prelude = min(candidates, key=len)
    encoded = [_encode_mov_opcode(move_dest, move_src) for move_dest, move_src in prelude]
    encoded.append(0xC0 | ALU_OPCODE_BY_MNEMONIC[mnemonic])
    if dest != 0:
        encoded.append(_encode_mov_opcode(dest, 0))
    return encoded


def _encode_unary_alu_pseudo(mnemonic: str, dest: int, src: int) -> list[int]:
    encoded: list[int] = []
    if src != 1:
        encoded.append(_encode_mov_opcode(1, src))
    encoded.append(0xC0 | ALU_OPCODE_BY_MNEMONIC[mnemonic])
    if dest != 0:
        encoded.append(_encode_mov_opcode(dest, 0))
    return encoded


def _plan_r1_r2_moves(src_a: int, src_b: int) -> list[tuple[int, int]]:
    pending: dict[int, int] = {}
    if src_a != 1:
        pending[1] = src_a
    if src_b != 2:
        pending[2] = src_b

    moves: list[tuple[int, int]] = []
    while pending:
        progress = False
        sources_in_use = tuple(pending.values())
        for target, source in list(pending.items()):
            if target not in [other_source for other_target, other_source in pending.items() if other_target != target]:
                moves.append((target, source))
                pending.pop(target)
                progress = True
                break

        if progress:
            continue

        if pending == {1: 2, 2: 1}:
            moves.extend([(0, 1), (1, 2), (2, 0)])
            pending.clear()
            continue

        raise AssertionError(f"unexpected register shuffle for ALU pseudo-op: {pending!r}, sources={sources_in_use!r}")

    return moves


def _encode_mov_opcode(dest: int, src: int) -> int:
    return ((dest & 0x07) << 3) | (src & 0x07)


def _emit_bytes(
    *,
    image: bytearray,
    occupied: list[bool],
    address: int,
    values: list[int],
    line_number: int,
) -> None:
    if address < 0 or address > 255:
        raise AssemblerError(line_number, f"address 0x{address & 0xFF:02X} is out of range")
    if address + len(values) > 256:
        raise AssemblerError(line_number, "program exceeds 256-byte address space")
    for offset, value in enumerate(values):
        target = address + offset
        if occupied[target]:
            raise AssemblerError(line_number, f"address 0x{target:02X} is written more than once")
        image[target] = value & 0xFF
        occupied[target] = True


def _advance_location(location: int, amount: int, line_number: int) -> int:
    next_location = location + amount
    if not 0 <= next_location <= 256:
        raise AssemblerError(line_number, "program exceeds 256-byte address space")
    return next_location


def _require_arg_count(parsed: ParsedLine, expected: int) -> None:
    if len(parsed.args) != expected:
        raise AssemblerError(parsed.line_number, f"{parsed.name} expects {expected} operand(s)")


def _parse_register(token: str, line_number: int) -> int:
    key = token.upper()
    if key not in REGISTER_INDEX:
        raise AssemblerError(line_number, f"unknown register {token!r}")
    return REGISTER_INDEX[key]


def _define_symbol(symbols: dict[str, int], name: str, value: int, line_number: int, *, wrap: bool = True) -> None:
    if name in symbols:
        raise AssemblerError(line_number, f"duplicate symbol {name!r}")
    symbols[name] = value & 0xFF if wrap else value


def _eval_address(expr: str, symbols: dict[str, int], line_number: int) -> int:
    value = _eval_expr(expr, symbols, line_number)
    if not 0 <= value <= 0xFF:
        raise AssemblerError(line_number, f"value {value} does not fit in 8 bits")
    return value


def _eval_byte(expr: str, symbols: dict[str, int], line_number: int) -> int:
    return _eval_address(expr, symbols, line_number)


def _eval_nibble(expr: str, symbols: dict[str, int], line_number: int) -> int:
    value = _eval_expr(expr, symbols, line_number)
    if not 0 <= value <= 0x0F:
        raise AssemblerError(line_number, f"value {value} does not fit in 4 bits")
    return value


def _eval_fill_count(expr: str, symbols: dict[str, int], line_number: int) -> int:
    value = _eval_expr(expr, symbols, line_number)
    if value < 0:
        raise AssemblerError(line_number, ".fill count must be non-negative")
    return value


def _eval_expr(expr: str, symbols: dict[str, int], line_number: int) -> int:
    try:
        node = ast.parse(expr, mode="eval")
    except SyntaxError as exc:
        raise AssemblerError(line_number, f"invalid expression {expr!r}") from exc
    return _eval_ast(node.body, symbols, line_number)


def _eval_ast(node: ast.AST, symbols: dict[str, int], line_number: int) -> int:
    if isinstance(node, ast.Constant):
        if isinstance(node.value, bool):
            return int(node.value)
        if isinstance(node.value, int):
            return node.value
        if isinstance(node.value, str) and len(node.value) == 1:
            return ord(node.value)
        raise AssemblerError(line_number, f"unsupported literal {node.value!r}")

    if isinstance(node, ast.Name):
        if node.id not in symbols:
            raise AssemblerError(line_number, f"undefined symbol {node.id!r}")
        return symbols[node.id]

    if isinstance(node, ast.UnaryOp):
        operand = _eval_ast(node.operand, symbols, line_number)
        if isinstance(node.op, ast.UAdd):
            return operand
        if isinstance(node.op, ast.USub):
            return -operand
        if isinstance(node.op, ast.Invert):
            return ~operand
        raise AssemblerError(line_number, "unsupported unary operator")

    if isinstance(node, ast.BinOp):
        left = _eval_ast(node.left, symbols, line_number)
        right = _eval_ast(node.right, symbols, line_number)
        if isinstance(node.op, ast.Add):
            return left + right
        if isinstance(node.op, ast.Sub):
            return left - right
        if isinstance(node.op, ast.Mult):
            return left * right
        if isinstance(node.op, ast.FloorDiv):
            return left // right
        if isinstance(node.op, ast.Mod):
            return left % right
        if isinstance(node.op, ast.LShift):
            return left << right
        if isinstance(node.op, ast.RShift):
            return left >> right
        if isinstance(node.op, ast.BitOr):
            return left | right
        if isinstance(node.op, ast.BitAnd):
            return left & right
        if isinstance(node.op, ast.BitXor):
            return left ^ right
        raise AssemblerError(line_number, "unsupported binary operator")

    raise AssemblerError(line_number, "unsupported expression")


if __name__ == "__main__":
    raise SystemExit(main())
