"""Tests for the Min8-Pro assembler."""

from __future__ import annotations

import tempfile
import unittest
from pathlib import Path

from min8_pro.asm import AssemblerError, assemble_source, main
from min8_pro.cpu import Min8ProCPU

from tests_pro.support import assemble_fixture


class AssemblerTests(unittest.TestCase):
    def test_basic_instruction_encoding(self) -> None:
        result = assemble_fixture("basic_program.asm")

        self.assertEqual(result.symbols["start"], 0x0000)
        self.assertEqual(result.image[:3], bytes([0x0A, 0xC0, 0x7F]))
        self.assertEqual(result.used_addresses, (0, 1, 2))

    def test_li_pseudo_supports_forward_label(self) -> None:
        result = assemble_fixture("forward_label_li.asm")

        self.assertEqual(result.symbols["target"], 0x0003)
        self.assertEqual(result.image[:4], bytes([0x83, 0x18, 0x7F, 0xAA]))

    def test_li16_fixed_expansion(self) -> None:
        result = assemble_source("LI16 R0, 0x1234\n")
        self.assertEqual(result.image[:7], bytes([0xDC, 0x84, 0xA3, 0xDD, 0x82, 0xA1, 0xDC]))

    def test_long_jump_pseudo_expands_with_explicit_scratch(self) -> None:
        result = assemble_source("LJMP R7, 0x1234\n")
        self.assertEqual(result.image[:8], bytes([0xDE, 0x94, 0xB3, 0xDF, 0x92, 0xB1, 0xDE, 0x57]))

    def test_li16_supports_forward_label(self) -> None:
        result = assemble_source(
            """
    LJMP R0, target
    HALT
.org 0x1234
target:
    HALT
"""
        )

        self.assertEqual(result.symbols["target"], 0x1234)
        self.assertEqual(result.image[:8], bytes([0xDC, 0x84, 0xA3, 0xDD, 0x82, 0xA1, 0xDC, 0x50]))

    def test_org_accepts_high_addresses(self) -> None:
        result = assemble_source(
            """
.org 0x1234
    HALT
"""
        )

        self.assertEqual(result.entry_address, 0x1234)
        self.assertEqual(result.image[0x1234], 0x7F)

    def test_li16_rejects_non_wide_register(self) -> None:
        with self.assertRaises(AssemblerError):
            assemble_source("LI16 R3, 0x1234\n")

    def test_long_jump_rejects_non_wide_scratch(self) -> None:
        with self.assertRaises(AssemblerError):
            assemble_source("LJZ R3, 0x1234\n")

    def test_cli_writes_full_image(self) -> None:
        with tempfile.TemporaryDirectory() as tmp_dir:
            tmp = Path(tmp_dir)
            source_path = tmp / "sample.asm"
            output_path = tmp / "sample.bin"
            source_path.write_text("HALT\n", encoding="utf-8")

            exit_code = main([str(source_path), "-o", str(output_path)])

            self.assertEqual(exit_code, 0)
            self.assertEqual(len(output_path.read_bytes()), 65536)

    def test_assembled_program_runs_on_simulator(self) -> None:
        result = assemble_fixture("ext16_store.asm")
        cpu = Min8ProCPU()
        cpu.load_image(result.image)

        run_results = cpu.run()

        self.assertEqual(run_results[-1].status, "halted")
        self.assertEqual(cpu.state.ext16, 1)
        self.assertEqual(cpu.state.memory[0x1234], 0x5A)


if __name__ == "__main__":
    unittest.main()
