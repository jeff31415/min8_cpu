"""Behavioral tests for the Min8-Pro reference simulator."""

from __future__ import annotations

import unittest

from min8_pro.cpu import Min8ProCPU
from min8_pro.exceptions import IllegalInstruction, MachineHalted
from min8_pro.io import FIFOIO


class Min8ProCPUTests(unittest.TestCase):
    def make_cpu(self, *, tx_capacity: int | None = None) -> Min8ProCPU:
        return Min8ProCPU(io_backend=FIFOIO(tx_capacity=tx_capacity))

    def test_reset_state_matches_spec(self) -> None:
        cpu = self.make_cpu()
        self.assertEqual(cpu.state.pc, 0)
        self.assertEqual(cpu.state.z, 0)
        self.assertEqual(cpu.state.c, 0)
        self.assertEqual(cpu.state.iosel, 0)
        self.assertEqual(cpu.state.ext16, 0)
        self.assertEqual(cpu.state.r0_sel, 0)
        self.assertEqual(cpu.state.r7_sel, 0)
        self.assertEqual(cpu.state.registers, [0] * 8)
        self.assertEqual(len(cpu.state.memory), 65536)

    def test_selector_is_illegal_before_ext16(self) -> None:
        cpu = self.make_cpu()
        cpu.load_image([0xDC])  # R0L
        with self.assertRaises(IllegalInstruction):
            cpu.step()

    def test_selector_preserves_flags(self) -> None:
        cpu = self.make_cpu()
        cpu.state.ext16 = 1
        cpu.state.z = 1
        cpu.state.c = 1
        cpu.load_image([0xDD])  # R0H

        cpu.step()

        self.assertEqual((cpu.state.z, cpu.state.c), (1, 1))

    def test_selector_does_not_write_r0(self) -> None:
        cpu = self.make_cpu()
        cpu.state.ext16 = 1
        cpu.state.registers[0] = 0x1234
        cpu.load_image([0xDD])  # R0H

        cpu.step()

        self.assertEqual(cpu.state.registers[0], 0x1234)
        self.assertEqual(cpu.state.r0_sel, 1)

    def test_system_port_enables_ext16(self) -> None:
        cpu = self.make_cpu()
        cpu.state.iosel = 0xFF
        cpu.state.registers[3] = 0x01
        cpu.load_image([0xFB])  # OUT R3

        result = cpu.step()

        self.assertEqual(result.status, "retired")
        self.assertEqual(cpu.state.ext16, 1)
        self.assertEqual(result.io_transfer.direction, "system")

    def test_getio_writes_selected_high_byte_of_r0(self) -> None:
        cpu = self.make_cpu()
        cpu.state.ext16 = 1
        cpu.state.r0_sel = 1
        cpu.state.registers[0] = 0x1234
        cpu.state.iosel = 0xAB
        cpu.load_image([0xE8])  # GETIO R0

        cpu.step()

        self.assertEqual(cpu.state.registers[0], 0xAB34)

    def test_setio_reads_selected_high_byte_of_r7(self) -> None:
        cpu = self.make_cpu()
        cpu.state.ext16 = 1
        cpu.state.r7_sel = 1
        cpu.state.registers[7] = 0x5634
        cpu.load_image([0xE7])  # SETIO R7

        cpu.step()

        self.assertEqual(cpu.state.iosel, 0x56)

    def test_repeated_enable_is_a_noop(self) -> None:
        cpu = self.make_cpu()
        cpu.state.ext16 = 1
        cpu.state.iosel = 0xFF
        cpu.state.registers[3] = 0x01
        cpu.load_image([0xFB])  # OUT R3

        cpu.step()

        self.assertEqual(cpu.state.ext16, 1)

    def test_invalid_system_write_is_illegal(self) -> None:
        cpu = self.make_cpu()
        cpu.state.iosel = 0xFF
        cpu.state.registers[3] = 0x02
        cpu.load_image([0xFB])  # OUT R3

        with self.assertRaises(IllegalInstruction):
            cpu.step()

    def test_in_on_system_port_is_illegal(self) -> None:
        cpu = self.make_cpu()
        cpu.state.iosel = 0xFF
        cpu.load_image([0xF3])  # IN R3

        with self.assertRaises(IllegalInstruction):
            cpu.step()

    def test_selector_and_ldi_build_full_r0(self) -> None:
        cpu = self.make_cpu()
        cpu.state.ext16 = 1
        cpu.load_image([0xDD, 0x8C, 0xA3, 0xDC])  # R0H; LDI_L/H R0; R0L

        cpu.step()
        cpu.step()
        cpu.step()
        cpu.step()

        self.assertEqual(cpu.state.registers[0], 0x3C00)
        self.assertEqual(cpu.state.r0_sel, 0)

    def test_ldi_into_selected_high_byte_preserves_low_byte(self) -> None:
        cpu = self.make_cpu()
        cpu.state.ext16 = 1
        cpu.state.r7_sel = 1
        cpu.state.registers[7] = 0x1234
        cpu.load_image([0x95, 0xB6])  # LDI_L_R7 5 ; LDI_H_R7 6

        cpu.step()
        cpu.step()

        self.assertEqual(cpu.state.registers[7], 0x6534)

    def test_legacy_post_increment_wraps_low_byte_only(self) -> None:
        cpu = self.make_cpu()
        cpu.state.registers[3] = 0x44
        cpu.state.registers[7] = 0x12FF
        cpu.load_image([0x73])  # ST+ R3

        cpu.step()

        self.assertEqual(cpu.state.memory[0x00FF], 0x44)
        self.assertEqual(cpu.state.registers[7], 0x1200)

    def test_ext16_post_increment_uses_full_r7(self) -> None:
        cpu = self.make_cpu()
        cpu.state.ext16 = 1
        cpu.state.registers[3] = 0x55
        cpu.state.registers[7] = 0x12FF
        cpu.load_image([0x73])  # ST+ R3

        cpu.step()

        self.assertEqual(cpu.state.memory[0x12FF], 0x55)
        self.assertEqual(cpu.state.registers[7], 0x1300)

    def test_ld_r7_writes_selected_byte_only(self) -> None:
        cpu = self.make_cpu()
        cpu.state.ext16 = 1
        cpu.state.r7_sel = 1
        cpu.state.registers[7] = 0x1234
        cpu.state.memory[0x1234] = 0xAB
        cpu.load_image([0x4F])  # LD R7

        cpu.step()

        self.assertEqual(cpu.state.registers[7], 0xAB34)

    def test_st_r7_uses_full_address_but_selected_byte_data(self) -> None:
        cpu = self.make_cpu()
        cpu.state.ext16 = 1
        cpu.state.r7_sel = 1
        cpu.state.registers[7] = 0x1234
        cpu.load_image([0x47])  # ST R7

        cpu.step()

        self.assertEqual(cpu.state.memory[0x1234], 0x12)

    def test_st_plus_r7_high_selected_stores_high_byte_and_increments_full_pointer(self) -> None:
        cpu = self.make_cpu()
        cpu.state.ext16 = 1
        cpu.state.r7_sel = 1
        cpu.state.registers[7] = 0x1234
        cpu.load_image([0x77])  # ST+ R7

        cpu.step()

        self.assertEqual(cpu.state.memory[0x1234], 0x12)
        self.assertEqual(cpu.state.registers[7], 0x1235)

    def test_long_jump_on_r0_ignores_selector(self) -> None:
        cpu = self.make_cpu()
        cpu.state.ext16 = 1
        cpu.state.r0_sel = 1
        cpu.state.registers[0] = 0x1234
        cpu.load_image([0x50])  # JMP R0

        cpu.step()

        self.assertEqual(cpu.state.pc, 0x1234)

    def test_long_conditional_jump_on_r7_uses_full_register(self) -> None:
        cpu = self.make_cpu()
        cpu.state.ext16 = 1
        cpu.state.z = 1
        cpu.state.r7_sel = 1
        cpu.state.registers[7] = 0x2345
        cpu.load_image([0x5F])  # JZ R7

        cpu.step()

        self.assertEqual(cpu.state.pc, 0x2345)

    def test_short_jump_in_ext16_preserves_page(self) -> None:
        cpu = self.make_cpu()
        cpu.state.ext16 = 1
        cpu.state.pc = 0x1200
        cpu.state.registers[3] = 0x34
        cpu.load_image([0x53], start=0x1200)  # JMP R3

        cpu.step()

        self.assertEqual(cpu.state.pc, 0x1234)

    def test_pc_crosses_page_linearly_in_ext16(self) -> None:
        cpu = self.make_cpu()
        cpu.state.ext16 = 1
        cpu.state.pc = 0x00FF
        cpu.state.memory[0x00FF] = 0x00
        cpu.state.memory[0x0100] = 0x7F

        first = cpu.step()
        second = cpu.step()

        self.assertEqual(first.next_pc, 0x0100)
        self.assertEqual(second.pc_before, 0x0100)
        self.assertEqual(second.status, "halted")

    def test_out_blocks_when_non_system_tx_fifo_is_full(self) -> None:
        cpu = self.make_cpu(tx_capacity=1)
        cpu.state.ext16 = 1
        cpu.state.iosel = 0x07
        cpu.state.registers[4] = 0x11
        cpu.load_image([0xFC])  # OUT R4
        cpu.io.write(0x07, 0x99)

        blocked = cpu.step()

        self.assertEqual(blocked.status, "blocked")
        self.assertEqual(blocked.blocked_on.direction, "out")

    def test_halt_stops_machine(self) -> None:
        cpu = self.make_cpu()
        cpu.load_image([0x7F])  # HALT

        result = cpu.step()

        self.assertEqual(result.status, "halted")
        self.assertTrue(cpu.state.halted)

        with self.assertRaises(MachineHalted):
            cpu.step()


if __name__ == "__main__":
    unittest.main()
