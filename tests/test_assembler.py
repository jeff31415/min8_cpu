"""Tests for the Min8 assembler."""

from __future__ import annotations

import tempfile
import unittest
from pathlib import Path

from min8.asm import AssemblerError, assemble_source, main
from min8.cpu import Min8CPU


class AssemblerTests(unittest.TestCase):
    def test_basic_instruction_encoding(self) -> None:
        result = assemble_source(
            """
start:
    MOV R1, R2
    ADD
    HALT
"""
        )

        self.assertEqual(result.symbols["start"], 0x00)
        self.assertEqual(result.image[:3], bytes([0x0A, 0xC0, 0x7F]))
        self.assertEqual(result.used_addresses, (0, 1, 2))

    def test_li_pseudo_supports_forward_label(self) -> None:
        result = assemble_source(
            """
    LI R3, target
    HALT
target:
    .byte 0xAA
"""
        )

        self.assertEqual(result.symbols["target"], 0x03)
        self.assertEqual(result.image[:4], bytes([0x83, 0x18, 0x7F, 0xAA]))

    def test_org_equ_fill_and_setioi(self) -> None:
        result = assemble_source(
            """
.equ CH, 3
.org 0x10
SETIOI CH
.fill 2, 0xFF
"""
        )

        self.assertEqual(result.entry_address, 0x10)
        self.assertEqual(result.image[0x10:0x14], bytes([0x83, 0xE0, 0xFF, 0xFF]))

    def test_nop_and_char_literal_byte(self) -> None:
        result = assemble_source(
            """
NOP
.byte 'A'
"""
        )

        self.assertEqual(result.image[:2], bytes([0x00, 0x41]))

    def test_invalid_ld_plus_r7_is_rejected(self) -> None:
        with self.assertRaises(AssemblerError):
            assemble_source("LD+ R7\n")

    def test_overlap_is_rejected(self) -> None:
        with self.assertRaises(AssemblerError):
            assemble_source(
                """
.byte 1
.org 0
.byte 2
"""
            )

    def test_undefined_symbol_is_rejected(self) -> None:
        with self.assertRaises(AssemblerError):
            assemble_source("LI R0, missing_label\n")

    def test_assembler_output_runs_on_simulator(self) -> None:
        result = assemble_source(
            """
    LI R3, 0x44
    LI R7, 0x20
    ST+ R3
    HALT
"""
        )
        cpu = Min8CPU()
        cpu.load_image(result.image)

        run_results = cpu.run()

        self.assertEqual(
            [item.status for item in run_results],
            ["retired", "retired", "retired", "retired", "retired", "retired", "halted"],
        )
        self.assertEqual(cpu.state.memory[0x20], 0x44)
        self.assertEqual(cpu.state.registers[7], 0x21)

    def test_cli_writes_memh_and_symbols(self) -> None:
        with tempfile.TemporaryDirectory() as tmp_dir:
            tmp = Path(tmp_dir)
            source_path = tmp / "sample.min8"
            memh_path = tmp / "sample.memh"
            sym_path = tmp / "sample.sym.json"
            lst_path = tmp / "sample.lst"
            source_path.write_text("HALT\n", encoding="utf-8")

            exit_code = main(
                [
                    str(source_path),
                    "--format",
                    "memh",
                    "-o",
                    str(memh_path),
                    "--symbols",
                    str(sym_path),
                    "--listing",
                    str(lst_path),
                ]
            )

            self.assertEqual(exit_code, 0)
            self.assertTrue(memh_path.read_text(encoding="utf-8").startswith("7F\n"))
            self.assertEqual(sym_path.read_text(encoding="utf-8"), "{}\n")
            self.assertIn("HALT", lst_path.read_text(encoding="utf-8"))

    def test_cli_defaults_to_bin_next_to_source(self) -> None:
        with tempfile.TemporaryDirectory() as tmp_dir:
            tmp = Path(tmp_dir)
            source_path = tmp / "sample.asm"
            output_path = tmp / "sample.bin"
            source_path.write_text("HALT\n", encoding="utf-8")

            exit_code = main([str(source_path)])

            self.assertEqual(exit_code, 0)
            self.assertEqual(output_path.read_bytes()[:1], b"\x7f")

    def test_small_immediate_uses_shorter_li_expansion(self) -> None:
        result = assemble_source(
            """
    LI R0, 0x0F
    LI R3, 0x0E
    SETIOI 0x03
"""
        )

        self.assertEqual(result.image[:5], bytes([0x8F, 0x8E, 0x18, 0x83, 0xE0]))

    def test_small_immediate_shrink_can_fit_at_end_of_image(self) -> None:
        result = assemble_source(
            """
.equ SMALL, 0x0E
.org 0xFD
    LI R3, SMALL
    HALT
"""
        )

        self.assertEqual(result.image[0xFD:0x100], bytes([0x8E, 0x18, 0x7F]))
        self.assertEqual(result.used_addresses, (0xFD, 0xFE, 0xFF))

    def test_small_setioi_shrink_can_fit_at_end_of_image(self) -> None:
        result = assemble_source(
            """
.equ CH, 3
.org 0xFD
    SETIOI CH
    HALT
"""
        )

        self.assertEqual(result.image[0xFD:0x100], bytes([0x83, 0xE0, 0x7F]))
        self.assertEqual(result.used_addresses, (0xFD, 0xFE, 0xFF))

    def test_explicit_binary_alu_pseudo_elides_redundant_moves(self) -> None:
        result = assemble_source(
            """
    ADD R0, R1, R5
    ADD R4, R1, R2
    ADD R3, R2, R1
"""
        )

        self.assertEqual(result.image[:6], bytes([0x15, 0xC0, 0xC0, 0x20, 0xC0, 0x18]))

    def test_explicit_non_commutative_alu_pseudo_uses_temp_for_r1_r2_swap(self) -> None:
        result = assemble_source("SUB R3, R2, R1\n")

        self.assertEqual(result.image[:5], bytes([0x01, 0x0A, 0x10, 0xC1, 0x18]))

    def test_explicit_unary_alu_pseudo_elides_redundant_moves(self) -> None:
        result = assemble_source(
            """
    MASK4 R6, R1
    SHL R5, R4
"""
        )

        self.assertEqual(result.image[:5], bytes([0xD3, 0x30, 0x0C, 0xC6, 0x28]))

    def test_explicit_alu_pseudo_runs_on_simulator(self) -> None:
        result = assemble_source(
            """
    LI R4, 5
    LI R5, 7
    ADD R6, R4, R5
    SUB R3, R6, R4
    MASK4 R2, R3
    HALT
"""
        )
        cpu = Min8CPU()
        cpu.load_image(result.image)

        run_results = cpu.run()

        self.assertEqual(run_results[-1].status, "halted")
        self.assertEqual(cpu.state.registers[6], 12)
        self.assertEqual(cpu.state.registers[3], 7)
        self.assertEqual(cpu.state.registers[2], 7)

    def test_graphics_extension_mnemonics_encode(self) -> None:
        result = assemble_source(
            """
    SHR2
    BTST
    MASK4
    ADC
    SBB
"""
        )

        self.assertEqual(result.image[:5], bytes([0xCA, 0xD1, 0xD3, 0xD4, 0xD5]))


if __name__ == "__main__":
    unittest.main()
