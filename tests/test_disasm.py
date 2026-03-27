"""Tests for Min8 disassembly helpers."""

from __future__ import annotations

import unittest

from min8.disasm import disassemble_image, format_disassembly


class DisassemblyTests(unittest.TestCase):
    def test_disassembles_valid_opcode(self) -> None:
        lines = disassemble_image(bytes([0x0A, 0x7F]), addresses=[0, 1], symbols={"start": 0})

        self.assertEqual(lines[0].text, "MOV R1, R2")
        self.assertEqual(lines[0].symbol, "start")
        self.assertEqual(lines[1].text, "HALT")

    def test_reserved_alu_disassembles_as_illegal_byte(self) -> None:
        lines = disassemble_image(bytes([0xCA]), addresses=[0])

        self.assertTrue(lines[0].illegal)
        self.assertEqual(lines[0].text, ".byte 0xCA ; illegal")

    def test_format_disassembly(self) -> None:
        text = format_disassembly(disassemble_image(bytes([0x7F]), addresses=[0]))

        self.assertEqual(text, "00: 7F  HALT\n")


if __name__ == "__main__":
    unittest.main()
