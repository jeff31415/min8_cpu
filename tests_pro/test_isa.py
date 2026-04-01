"""Tests for Min8-Pro ISA decode helpers."""

from __future__ import annotations

import unittest

from min8_pro.exceptions import IllegalInstruction
from min8_pro.isa import decode_opcode


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

    def test_selector_decode(self) -> None:
        instruction = decode_opcode(0xDF)
        self.assertEqual(instruction.family, "selector")
        self.assertEqual(instruction.mnemonic, "R7H")
        self.assertEqual(instruction.instruction_text, "R7H")

    def test_reserved_selector_space_raises(self) -> None:
        with self.assertRaises(IllegalInstruction):
            decode_opcode(0xDB, pc=0x1234)


if __name__ == "__main__":
    unittest.main()
