"""Tests for the Min8-Pro interactive session layer."""

from __future__ import annotations

import tempfile
import unittest
from pathlib import Path

from min8_pro.exceptions import MachineHalted
from min8_pro.session import Min8ProSession


class SessionTests(unittest.TestCase):
    def test_load_assembly_file_and_reset(self) -> None:
        session = Min8ProSession()
        with tempfile.TemporaryDirectory() as tmp_dir:
            source_path = Path(tmp_dir) / "demo.asm"
            source_path.write_text("HALT\n", encoding="utf-8")

            session.load_assembly_file(source_path)
            session.step()
            self.assertTrue(session.cpu.state.halted)

            session.reset()
            self.assertFalse(session.cpu.state.halted)
            self.assertEqual(session.cpu.state.memory[0], 0x7F)
            self.assertEqual(session.current_address, 0x0000)

    def test_load_image_file_pads_to_full_64k(self) -> None:
        session = Min8ProSession()
        with tempfile.TemporaryDirectory() as tmp_dir:
            image_path = Path(tmp_dir) / "demo.bin"
            image_path.write_bytes(bytes([0x7F]))

            session.load_image_file(image_path)

            self.assertEqual(len(session.cpu.state.memory), 65536)
            self.assertEqual(session.cpu.state.memory[0], 0x7F)
            self.assertEqual(session.cpu.state.memory[1], 0x00)

    def test_run_batch_stops_on_block_and_rx_resume(self) -> None:
        session = Min8ProSession()
        session.load_source(
            """
    SETIOI 0x01
    IN R3
    HALT
"""
        )

        results = session.run_batch(max_steps=10)
        self.assertEqual([result.status for result in results], ["retired", "retired", "blocked"])

        session.queue_rx(0x01, [0x55])
        resumed = session.run_batch(max_steps=10)
        self.assertEqual([result.status for result in resumed], ["retired", "halted"])
        self.assertEqual(session.cpu.state.registers[3], 0x55)
        self.assertEqual(session.last_stop_reason, "halted")

    def test_current_address_masks_hidden_legacy_high_bits(self) -> None:
        session = Min8ProSession()
        session.load_source(
            """
    .org 0x0034
    HALT
"""
        )
        session.edit_state("PC", 0x1234)

        session.step()

        self.assertEqual(session.current_address, 0x0034)
        with self.assertRaises(MachineHalted):
            session.step()

    def test_breakpoint_uses_full_16_bit_address_when_ext16_enabled(self) -> None:
        session = Min8ProSession()
        session.load_source(
            """
    .org 0x1234
    HALT
"""
        )
        session.edit_state("EXT16", 1)
        session.edit_state("PC", 0x1234)
        session.set_breakpoint(0x1234)

        results = session.run_batch(max_steps=10)

        self.assertEqual(results, [])
        self.assertEqual(session.last_stop_reason, "breakpoint")
        self.assertEqual(session.current_address, 0x1234)

    def test_edit_state_and_memory_track_wide_fields(self) -> None:
        session = Min8ProSession()
        session.load_source("HALT\n")

        session.edit_state("R0", 0xCAFE)
        self.assertEqual(session.cpu.state.registers[0], 0xCAFE)
        self.assertEqual(session.last_register_changes, {0})

        session.edit_state("PC", 0x3456)
        self.assertEqual(session.cpu.state.pc, 0x3456)
        self.assertEqual(session.last_special_changes, {"PC"})

        session.edit_state("EXT16", 1)
        self.assertEqual(session.cpu.state.ext16, 1)
        self.assertEqual(session.last_special_changes, {"EXT16"})

        session.edit_memory(0x1234, 0xAA)
        self.assertEqual(session.cpu.state.memory[0x1234], 0xAA)
        self.assertEqual(session.last_memory_changes, {0x1234})

    def test_source_and_disassembly_mappings_exist_for_high_addresses(self) -> None:
        session = Min8ProSession()
        session.load_source(
            """
    .org 0x1234
start:
    HALT
"""
        )

        self.assertEqual(session.source_line_for_address(0x1234), 4)
        self.assertEqual(session.source_address_for_line(4), 0x1234)
        self.assertEqual(session.disassembly_line_for_address(0x1234), 1)

    def test_memory_dump_uses_16_bit_rows(self) -> None:
        session = Min8ProSession()
        session.load_source("HALT\n")
        session.edit_memory(0x12F0, 0xAA)
        session.edit_memory(0x1300, 0x55)

        dump = session.memory_dump(base=0x12F0, rows=2)

        self.assertIn("12F0: AA", dump)
        self.assertIn("1300: 55", dump)


if __name__ == "__main__":
    unittest.main()
