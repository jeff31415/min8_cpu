"""ISA constants and decode helpers for Min8."""

from __future__ import annotations

from dataclasses import dataclass

from .exceptions import IllegalInstruction

REGISTER_NAMES = tuple(f"R{index}" for index in range(8))
REGISTER_INDEX = {name: index for index, name in enumerate(REGISTER_NAMES)}

ALU_MNEMONICS = {
    0x00: "ADD",
    0x01: "SUB",
    0x02: "AND",
    0x03: "OR",
    0x04: "XOR",
    0x05: "NOT",
    0x06: "SHL",
    0x07: "SHR",
    0x08: "INC",
    0x09: "DEC",
    0x0A: "SHR2",
    0x0B: "SHR3",
    0x0C: "SHL2",
    0x0D: "SHL3",
    0x0E: "BSET",
    0x0F: "BCLR",
    0x10: "BTGL",
    0x11: "BTST",
    0x12: "MASK3",
    0x13: "MASK4",
    0x14: "ADC",
    0x15: "SBB",
}

MEM_CTRL_MNEMONICS = {
    0b000: "ST",
    0b001: "LD",
    0b010: "JMP",
    0b011: "JZ",
    0b100: "JC",
    0b101: "JNZ",
    0b110: "ST+",
    0b111: "LD+",
}

ALU_OPCODE_BY_MNEMONIC = {mnemonic: opcode for opcode, mnemonic in ALU_MNEMONICS.items()}

MEM_CTRL_OPCODE_BASE = {
    "ST": 0x40,
    "LD": 0x48,
    "JMP": 0x50,
    "JZ": 0x58,
    "JC": 0x60,
    "JNZ": 0x68,
    "ST+": 0x70,
    "LD+": 0x78,
}

IO_OPCODE_BASE = {
    "SETIO": 0xE0,
    "GETIO": 0xE8,
    "IN": 0xF0,
    "OUT": 0xF8,
}

LDI_OPCODE_BASE = {
    "LDI_L_R0": 0x80,
    "LDI_L_R7": 0x90,
    "LDI_H_R0": 0xA0,
    "LDI_H_R7": 0xB0,
}


@dataclass(frozen=True)
class DecodedInstruction:
    opcode: int
    family: str
    mnemonic: str
    register: int | None = None
    dest: int | None = None
    src: int | None = None
    imm4: int | None = None
    ldi_target: int | None = None
    ldi_high: bool | None = None
    alu_subopcode: int | None = None

    @property
    def instruction_text(self) -> str:
        if self.family == "mov":
            return f"{self.mnemonic} {register_name(self.dest)}, {register_name(self.src)}"
        if self.family in {"mem_ctrl", "io"} and self.register is not None:
            return f"{self.mnemonic} {register_name(self.register)}"
        if self.family == "ldi":
            return f"{self.mnemonic} 0x{self.imm4:X}"
        return self.mnemonic


def register_name(index: int | None) -> str:
    if index is None or not 0 <= index < len(REGISTER_NAMES):
        raise ValueError(f"Invalid register index: {index!r}")
    return REGISTER_NAMES[index]


def decode_opcode(opcode: int, *, pc: int | None = None) -> DecodedInstruction:
    opcode &= 0xFF

    top2 = opcode >> 6
    if top2 == 0b00:
        return DecodedInstruction(
            opcode=opcode,
            family="mov",
            mnemonic="MOV",
            dest=(opcode >> 3) & 0x07,
            src=opcode & 0x07,
        )

    if top2 == 0b01:
        subopcode = (opcode >> 3) & 0x07
        register = opcode & 0x07
        if opcode == 0x7F:
            return DecodedInstruction(opcode=opcode, family="control", mnemonic="HALT")
        mnemonic = MEM_CTRL_MNEMONICS[subopcode]
        return DecodedInstruction(
            opcode=opcode,
            family="mem_ctrl",
            mnemonic=mnemonic,
            register=register,
        )

    if top2 == 0b10:
        imm4 = opcode & 0x0F
        ldi_high = bool((opcode >> 5) & 0x01)
        ldi_target = 7 if ((opcode >> 4) & 0x01) else 0
        mnemonic = f"LDI_{'H' if ldi_high else 'L'}_{register_name(ldi_target)}"
        return DecodedInstruction(
            opcode=opcode,
            family="ldi",
            mnemonic=mnemonic,
            imm4=imm4,
            ldi_target=ldi_target,
            ldi_high=ldi_high,
        )

    top3 = opcode >> 5
    if top3 == 0b110:
        alu_subopcode = opcode & 0x1F
        mnemonic = ALU_MNEMONICS.get(alu_subopcode)
        if mnemonic is None:
            raise IllegalInstruction(
                opcode=opcode,
                pc=pc or 0,
                message="Reserved ALU opcode",
            )
        return DecodedInstruction(
            opcode=opcode,
            family="alu",
            mnemonic=mnemonic,
            alu_subopcode=alu_subopcode,
        )

    io_class = (opcode >> 3) & 0x03
    register = opcode & 0x07
    if io_class == 0b00:
        mnemonic = "SETIO"
    elif io_class == 0b01:
        mnemonic = "GETIO"
    elif io_class == 0b10:
        mnemonic = "IN"
    else:
        mnemonic = "OUT"
    return DecodedInstruction(
        opcode=opcode,
        family="io",
        mnemonic=mnemonic,
        register=register,
    )
