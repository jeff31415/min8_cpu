"""Tests for the Min8 interactive session layer."""

from __future__ import annotations

import tempfile
import unittest
from pathlib import Path

from min8.exceptions import MachineHalted
from min8.session import Min8Session


class SessionTests(unittest.TestCase):
    def test_load_assembly_file_and_reset(self) -> None:
        session = Min8Session()
        with tempfile.TemporaryDirectory() as tmp_dir:
            source_path = Path(tmp_dir) / "demo.asm"
            source_path.write_text("HALT\n", encoding="utf-8")

            session.load_assembly_file(source_path)
            session.step()
            self.assertTrue(session.cpu.state.halted)

            session.reset()
            self.assertFalse(session.cpu.state.halted)
            self.assertEqual(session.cpu.state.memory[0], 0x7F)
            self.assertEqual(session.current_address, 0x00)

    def test_run_batch_stops_on_block_and_rx_resume(self) -> None:
        session = Min8Session()
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

    def test_current_address_tracks_halt_instruction(self) -> None:
        session = Min8Session()
        session.load_source("HALT\n")
        session.step()

        self.assertEqual(session.current_address, 0x00)
        with self.assertRaises(MachineHalted):
            session.step()

    def test_breakpoint_stops_before_execution(self) -> None:
        session = Min8Session()
        session.load_source(
            """
    NOP
    HALT
"""
        )
        session.set_breakpoint(0x01)

        results = session.run_batch(max_steps=10)

        self.assertEqual([result.status for result in results], ["retired"])
        self.assertEqual(session.last_stop_reason, "breakpoint")
        self.assertEqual(session.current_address, 0x01)

    def test_edit_state_and_memory_track_highlights(self) -> None:
        session = Min8Session()
        session.load_source("HALT\n")

        session.edit_state("R3", 0x44)
        self.assertEqual(session.cpu.state.registers[3], 0x44)
        self.assertEqual(session.last_register_changes, {3})

        session.edit_state("PC", 0x20)
        self.assertEqual(session.cpu.state.pc, 0x20)
        self.assertEqual(session.last_special_changes, {"PC"})

        session.edit_memory(0x10, 0xAA)
        self.assertEqual(session.cpu.state.memory[0x10], 0xAA)
        self.assertEqual(session.last_memory_changes, {0x10})

    def test_source_and_disassembly_mappings_exist(self) -> None:
        session = Min8Session()
        session.load_source(
            """
start:
    NOP
    HALT
"""
        )

        self.assertEqual(session.source_line_for_address(0x00), 3)
        self.assertEqual(session.source_address_for_line(4), 0x01)
        self.assertEqual(session.disassembly_line_for_address(0x00), 1)


if __name__ == "__main__":
    unittest.main()
