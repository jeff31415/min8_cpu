"""Behavioral tests for the Min8 reference simulator."""

from __future__ import annotations

import unittest

from min8.cpu import Min8CPU
from min8.exceptions import IllegalInstruction, MachineHalted
from min8.io import FIFOIO


class Min8CPUTests(unittest.TestCase):
    def make_cpu(self, *, tx_capacity: int | None = None) -> Min8CPU:
        return Min8CPU(io_backend=FIFOIO(tx_capacity=tx_capacity))

    def test_reset_state_matches_spec(self) -> None:
        cpu = self.make_cpu()
        self.assertEqual(cpu.state.pc, 0)
        self.assertEqual(cpu.state.z, 0)
        self.assertEqual(cpu.state.c, 0)
        self.assertEqual(cpu.state.iosel, 0)
        self.assertEqual(cpu.state.registers, [0] * 8)
        self.assertEqual(list(cpu.state.memory), [0] * 256)

    def test_mov_copies_register_without_touching_flags(self) -> None:
        cpu = self.make_cpu()
        cpu.state.registers[4] = 0xA5
        cpu.state.z = 1
        cpu.state.c = 1
        cpu.load_image([0x1C])  # MOV R3, R4

        result = cpu.step()

        self.assertEqual(result.instruction_text, "MOV R3, R4")
        self.assertEqual(cpu.state.registers[3], 0xA5)
        self.assertEqual((cpu.state.z, cpu.state.c), (1, 1))
        self.assertEqual(result.status, "retired")

    def test_ldi_low_then_high_builds_byte(self) -> None:
        cpu = self.make_cpu()
        cpu.load_image([0x8C, 0xA3])  # LDI_L_R0 0xC; LDI_H_R0 0x3

        cpu.step()
        cpu.step()

        self.assertEqual(cpu.state.registers[0], 0x3C)

    def test_alu_add_updates_r0_and_flags(self) -> None:
        cpu = self.make_cpu()
        cpu.state.registers[1] = 0xFF
        cpu.state.registers[2] = 0x01
        cpu.load_image([0xC0])  # ADD

        result = cpu.step()

        self.assertEqual(result.instruction_text, "ADD")
        self.assertEqual(cpu.state.registers[0], 0x00)
        self.assertEqual((cpu.state.z, cpu.state.c), (1, 1))

    def test_sub_and_dec_use_borrow_convention(self) -> None:
        cpu = self.make_cpu()
        cpu.state.registers[1] = 0x00
        cpu.state.registers[2] = 0x01
        cpu.load_image([0xC1, 0xC9])  # SUB; DEC

        cpu.step()
        self.assertEqual(cpu.state.registers[0], 0xFF)
        self.assertEqual((cpu.state.z, cpu.state.c), (0, 1))

        cpu.state.registers[1] = 0x00
        cpu.step()
        self.assertEqual(cpu.state.registers[0], 0xFF)
        self.assertEqual((cpu.state.z, cpu.state.c), (0, 1))

    def test_shift_extensions_update_result_and_carry(self) -> None:
        cpu = self.make_cpu()
        cpu.state.registers[1] = 0xB2
        cpu.load_image([0xCA, 0xCD])  # SHR2; SHL3

        first = cpu.step()
        self.assertEqual(first.instruction_text, "SHR2")
        self.assertEqual(cpu.state.registers[0], 0x2C)
        self.assertEqual((cpu.state.z, cpu.state.c), (0, 1))

        cpu.state.registers[1] = 0x27
        second = cpu.step()
        self.assertEqual(second.instruction_text, "SHL3")
        self.assertEqual(cpu.state.registers[0], 0x38)
        self.assertEqual((cpu.state.z, cpu.state.c), (0, 1))

    def test_bit_extensions_use_r2_low_bits(self) -> None:
        cpu = self.make_cpu()
        cpu.state.registers[2] = 0x1C
        cpu.load_image([0xCE, 0xCF, 0xD0, 0xD1])  # BSET; BCLR; BTGL; BTST

        cpu.state.registers[1] = 0x00
        cpu.step()
        self.assertEqual(cpu.state.registers[0], 0x10)
        self.assertEqual((cpu.state.z, cpu.state.c), (0, 0))

        cpu.state.registers[1] = 0x1F
        cpu.step()
        self.assertEqual(cpu.state.registers[0], 0x0F)
        self.assertEqual((cpu.state.z, cpu.state.c), (0, 0))

        cpu.state.registers[1] = 0x10
        cpu.step()
        self.assertEqual(cpu.state.registers[0], 0x00)
        self.assertEqual((cpu.state.z, cpu.state.c), (1, 0))

        cpu.state.registers[1] = 0x10
        cpu.step()
        self.assertEqual(cpu.state.registers[0], 0x10)
        self.assertEqual((cpu.state.z, cpu.state.c), (0, 0))

    def test_mask_extensions_limit_r1_and_clear_carry(self) -> None:
        cpu = self.make_cpu()
        cpu.load_image([0xD2, 0xD3])  # MASK3; MASK4

        cpu.state.registers[1] = 0xAB
        cpu.state.c = 1
        cpu.step()
        self.assertEqual(cpu.state.registers[0], 0x03)
        self.assertEqual((cpu.state.z, cpu.state.c), (0, 0))

        cpu.state.registers[1] = 0x10
        cpu.state.c = 1
        cpu.step()
        self.assertEqual(cpu.state.registers[0], 0x00)
        self.assertEqual((cpu.state.z, cpu.state.c), (1, 0))

    def test_adc_and_sbb_chain_with_carry_flag(self) -> None:
        cpu = self.make_cpu()
        cpu.load_image([0xD4, 0xD5])  # ADC; SBB

        cpu.state.registers[1] = 0xFF
        cpu.state.registers[2] = 0x00
        cpu.state.c = 1
        first = cpu.step()
        self.assertEqual(first.instruction_text, "ADC")
        self.assertEqual(cpu.state.registers[0], 0x00)
        self.assertEqual((cpu.state.z, cpu.state.c), (1, 1))

        cpu.state.registers[1] = 0x10
        cpu.state.registers[2] = 0x0F
        cpu.state.c = 1
        second = cpu.step()
        self.assertEqual(second.instruction_text, "SBB")
        self.assertEqual(cpu.state.registers[0], 0x00)
        self.assertEqual((cpu.state.z, cpu.state.c), (1, 0))

        cpu.state.pc = 0x01
        cpu.state.registers[1] = 0x10
        cpu.state.registers[2] = 0x10
        cpu.state.c = 1
        cpu.step()
        self.assertEqual(cpu.state.registers[0], 0xFF)
        self.assertEqual((cpu.state.z, cpu.state.c), (0, 1))

    def test_load_store_and_post_increment_wrap(self) -> None:
        cpu = self.make_cpu()
        cpu.state.registers[3] = 0x44
        cpu.state.registers[7] = 0xFF
        cpu.load_image([0x73, 0x4C])  # ST+ R3; LD R4

        first = cpu.step()

        self.assertEqual(cpu.state.memory[0xFF], 0x44)
        self.assertEqual(cpu.state.registers[7], 0x00)
        self.assertEqual(first.memory_writes[0].address, 0xFF)

        cpu.state.memory[0x00] = 0x99
        second = cpu.step()
        self.assertEqual(cpu.state.registers[4], 0x99)
        self.assertEqual(second.register_writes[-1].name, "R4")

    def test_st_plus_r7_is_legal(self) -> None:
        cpu = self.make_cpu()
        cpu.state.registers[7] = 0x20
        cpu.load_image([0x77])  # ST+ R7

        cpu.step()

        self.assertEqual(cpu.state.memory[0x20], 0x20)
        self.assertEqual(cpu.state.registers[7], 0x21)

    def test_jumps_use_post_fetch_pc_rule(self) -> None:
        cpu = self.make_cpu()
        cpu.state.registers[3] = 0x40
        cpu.load_image([0x53])  # JMP R3

        result = cpu.step()

        self.assertEqual(result.pc_before, 0x00)
        self.assertEqual(cpu.state.pc, 0x40)
        self.assertEqual(result.next_pc, 0x40)

    def test_jz_and_jnz_respect_flags(self) -> None:
        cpu = self.make_cpu()
        cpu.state.registers[2] = 0x12
        cpu.state.registers[3] = 0x34
        cpu.state.z = 1
        cpu.load_image([0x5A, 0x6B])  # JZ R2; JNZ R3

        cpu.step()
        self.assertEqual(cpu.state.pc, 0x12)

        cpu.state.pc = 1
        cpu.state.z = 1
        cpu.step()
        self.assertEqual(cpu.state.pc, 0x02)

    def test_non_alu_instructions_preserve_flags(self) -> None:
        cpu = self.make_cpu()
        cpu.state.z = 1
        cpu.state.c = 1
        cpu.load_image([0x49, 0xE1, 0xE9])  # LD R1; SETIO R1; GETIO R1
        cpu.state.registers[7] = 0x10
        cpu.state.memory[0x10] = 0xAB

        cpu.step()
        cpu.step()
        cpu.step()

        self.assertEqual((cpu.state.z, cpu.state.c), (1, 1))
        self.assertEqual(cpu.state.iosel, 0xAB)
        self.assertEqual(cpu.state.registers[1], 0xAB)

    def test_in_blocks_until_rx_data_arrives_and_retries_same_instruction(self) -> None:
        cpu = self.make_cpu()
        cpu.state.iosel = 0x03
        cpu.load_image([0xF3])  # IN R3

        blocked = cpu.step()

        self.assertEqual(blocked.status, "blocked")
        self.assertEqual(blocked.blocked_on.direction, "in")
        self.assertEqual(cpu.state.pc, 0x01)
        self.assertIsNotNone(cpu.state.pending)

        cpu.io.queue_rx(0x03, 0x5A)
        completed = cpu.step()

        self.assertEqual(completed.status, "retired")
        self.assertEqual(cpu.state.registers[3], 0x5A)
        self.assertIsNone(cpu.state.pending)
        self.assertEqual(cpu.state.pc, 0x01)

    def test_out_blocks_when_tx_fifo_is_full(self) -> None:
        cpu = self.make_cpu(tx_capacity=1)
        cpu.state.iosel = 0x07
        cpu.state.registers[4] = 0x11
        cpu.load_image([0xFC])  # OUT R4
        cpu.io.write(0x07, 0x99)

        blocked = cpu.step()

        self.assertEqual(blocked.status, "blocked")
        self.assertEqual(blocked.blocked_on.direction, "out")
        self.assertEqual(cpu.io.drain_tx(0x07), [0x99])

        completed = cpu.step()

        self.assertEqual(completed.io_transfer.value, 0x11)
        self.assertEqual(cpu.io.drain_tx(0x07), [0x11])

    def test_halt_stops_machine(self) -> None:
        cpu = self.make_cpu()
        cpu.load_image([0x7F])  # HALT

        result = cpu.step()

        self.assertEqual(result.status, "halted")
        self.assertTrue(cpu.state.halted)

        with self.assertRaises(MachineHalted):
            cpu.step()

    def test_reserved_alu_opcode_raises_illegal_instruction(self) -> None:
        cpu = self.make_cpu()
        cpu.load_image([0xD6])

        with self.assertRaises(IllegalInstruction):
            cpu.step()

    def test_self_modifying_code_is_visible_to_next_fetch(self) -> None:
        cpu = self.make_cpu()
        cpu.state.registers[3] = 0x7F
        cpu.state.registers[7] = 0x01
        cpu.load_image([0x73, 0x00])  # ST+ R3; placeholder NOP

        first = cpu.step()
        second = cpu.step()

        self.assertEqual(first.memory_writes[0].after, 0x7F)
        self.assertEqual(second.status, "halted")

    def test_pc_wraps_after_fetch(self) -> None:
        cpu = self.make_cpu()
        cpu.state.pc = 0xFF
        cpu.state.memory[0xFF] = 0x00  # NOP

        result = cpu.step()

        self.assertEqual(result.pc_before, 0xFF)
        self.assertEqual(result.next_pc, 0x00)
        self.assertEqual(cpu.state.pc, 0x00)

    def test_run_stops_on_block(self) -> None:
        cpu = self.make_cpu()
        cpu.state.iosel = 0x01
        cpu.load_image([0x00, 0xF0])  # NOP; IN R0

        results = cpu.run()

        self.assertEqual([result.status for result in results], ["retired", "blocked"])
        self.assertEqual(cpu.state.retired_count, 1)


if __name__ == "__main__":
    unittest.main()
