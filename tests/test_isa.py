"""Tests for Min8 ISA decode helpers."""

from __future__ import annotations

import unittest

from min8.exceptions import IllegalInstruction
from min8.isa import decode_opcode


class DecodeTests(unittest.TestCase):
    def test_mov_decode(self) -> None:
        instruction = decode_opcode(0x1C)
        self.assertEqual(instruction.mnemonic, "MOV")
        self.assertEqual(instruction.dest, 3)
        self.assertEqual(instruction.src, 4)
        self.assertEqual(instruction.instruction_text, "MOV R3, R4")

    def test_halt_decode(self) -> None:
        instruction = decode_opcode(0x7F)
        self.assertEqual(instruction.mnemonic, "HALT")
        self.assertEqual(instruction.instruction_text, "HALT")

    def test_ldi_decode(self) -> None:
        instruction = decode_opcode(0xB5)
        self.assertEqual(instruction.mnemonic, "LDI_H_R7")
        self.assertEqual(instruction.imm4, 0x5)
        self.assertEqual(instruction.instruction_text, "LDI_H_R7 0x5")

    def test_reserved_alu_decode_raises(self) -> None:
        with self.assertRaises(IllegalInstruction):
            decode_opcode(0xCA, pc=0x44)


if __name__ == "__main__":
    unittest.main()
