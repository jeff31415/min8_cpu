"""Program-level Min8-Pro integration tests using standalone assembly fixtures."""

from __future__ import annotations

import unittest

from tests_pro.support import assemble_fixture, run_fixture


class ProgramTests(unittest.TestCase):
    def test_linear_fetch_cross_page_program(self) -> None:
        _result, cpu = run_fixture("linear_fetch_cross_page.asm")

        self.assertEqual(cpu.state.ext16, 1)
        self.assertEqual(cpu.state.registers[3] & 0xFF, 0xAA)
        self.assertEqual(cpu.state.pc, 0x0102)

    def test_ext16_store_crosses_page_program(self) -> None:
        _result, cpu = run_fixture("ext16_store_cross_page.asm")

        self.assertEqual(cpu.state.memory[0x01FF], 0x11)
        self.assertEqual(cpu.state.memory[0x0200], 0x22)
        self.assertEqual(cpu.state.registers[7], 0x0201)

    def test_long_jump_taken_program(self) -> None:
        result, cpu = run_fixture("long_jump_taken.asm")

        self.assertEqual(result.symbols["target"], 0x0120)
        self.assertEqual(cpu.state.registers[5] & 0xFF, 0x5A)
        self.assertEqual(cpu.state.registers[4] & 0xFF, 0x01)
        self.assertEqual(cpu.state.registers[6] & 0xFF, 0x20)

    def test_long_jump_not_taken_program_still_clobbers_scratch(self) -> None:
        result, cpu = run_fixture("long_jump_not_taken.asm")

        self.assertEqual(result.symbols["target"], 0x0120)
        self.assertEqual(cpu.state.registers[5] & 0xFF, 0x11)
        self.assertEqual(cpu.state.registers[4] & 0xFF, 0x01)
        self.assertEqual(cpu.state.registers[6] & 0xFF, 0x20)

    def test_selector_roundtrip_program(self) -> None:
        _result, cpu = run_fixture("selector_roundtrip.asm")

        self.assertEqual(cpu.state.registers[3] & 0xFF, 0x12)
        self.assertEqual(cpu.state.registers[4] & 0xFF, 0x34)
        self.assertEqual(cpu.state.r0_sel, 0)

    def test_high_memory_self_modifying_program(self) -> None:
        _result, cpu = run_fixture("high_mem_self_modify.asm")

        self.assertEqual(cpu.state.memory[0x0120], 0x7F)
        self.assertTrue(cpu.state.halted)

    def test_fixture_symbol_layouts_remain_stable(self) -> None:
        result = assemble_fixture("linear_fetch_cross_page.asm")
        self.assertEqual(result.symbols["near"], 0x00FE)


if __name__ == "__main__":
    unittest.main()
