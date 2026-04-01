"""Tests for Min8-Pro disassembly helpers."""

from __future__ import annotations

import unittest

from min8_pro.disasm import disassemble_image, format_disassembly


class DisassemblyTests(unittest.TestCase):
    def test_disassembles_selector_opcode(self) -> None:
        lines = disassemble_image(bytes([0xDC]), addresses=[0])
        self.assertEqual(lines[0].text, "R0L")

    def test_formats_four_digit_addresses(self) -> None:
        image = bytearray(0x1235)
        image[0x1234] = 0x7F
        text = format_disassembly(disassemble_image(image, addresses=[0x1234]))
        self.assertIn("1234: 7F  HALT", text)


if __name__ == "__main__":
    unittest.main()
