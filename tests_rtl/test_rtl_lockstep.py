from __future__ import annotations

import cocotb

from tests_rtl.support.lockstep import LockstepIOHarness, run_lockstep_program


ARITHMETIC_PROGRAM = """
    LI R1, 0xFE
    LI R2, 0x03
    ADD
    MOV R4, R0
    LI R1, 0xFF
    LI R2, 0x00
    ADC
    MOV R5, R0
    LI R1, 0x10
    LI R2, 0x0F
    SBB
    MOV R6, R0
    HALT
"""


MEMORY_AND_BRANCH_PROGRAM = """
    LI R7, 0xF0
    LI R3, 0x44
    ST+ R3
    LI R3, 0x99
    ST+ R3
    LI R7, 0xF0
    LD R4
    LI R7, 0xF1
    LD+ R5
    LI R1, 0x44
    LI R2, 0x44
    SUB
    LI R6, taken
    JZ R6
    HALT
taken:
    LI R1, 0x07
    LI R2, 0x03
    SHL2
    HALT
"""


BLOCKING_IN_PROGRAM = """
    SETIOI 0x03
    IN R3
    OUT R3
    GETIO R4
    HALT
"""


BLOCKING_OUT_PROGRAM = """
    SETIOI 0x07
    LI R5, 0x2A
    OUT R5
    HALT
"""


@cocotb.test()
async def test_lockstep_arithmetic_program(dut) -> None:
    result = await run_lockstep_program(dut, ARITHMETIC_PROGRAM)

    assert result.cpu.state.registers[4] == 0x01
    assert result.cpu.state.registers[5] == 0x00
    assert result.cpu.state.registers[6] == 0x00
    assert result.cpu.state.c == 0


@cocotb.test()
async def test_lockstep_memory_and_branch_program(dut) -> None:
    result = await run_lockstep_program(dut, MEMORY_AND_BRANCH_PROGRAM)

    assert result.cpu.state.memory[0xF0] == 0x44
    assert result.cpu.state.memory[0xF1] == 0x99
    assert result.cpu.state.registers[4] == 0x44
    assert result.cpu.state.registers[5] == 0x99
    assert result.cpu.state.registers[7] == 0xF2
    assert result.cpu.state.registers[0] == 0x1C


def _setup_blocking_in(io: LockstepIOHarness) -> None:
    io.set_tx_ready(True)


def _resume_blocking_in(io: LockstepIOHarness, rtl_event: str, _result, event_index: int) -> None:
    if rtl_event == "blocked":
        io.queue_rx(0x03, 0x5A)


@cocotb.test()
async def test_lockstep_blocking_in_program(dut) -> None:
    result = await run_lockstep_program(
        dut,
        BLOCKING_IN_PROGRAM,
        setup_io=_setup_blocking_in,
        on_event=_resume_blocking_in,
    )

    assert result.events.count("blocked") == 1
    assert result.cpu.state.registers[3] == 0x5A
    assert result.cpu.state.registers[4] == 0x03
    assert result.io.reference.tx_snapshot() == {0x03: (0x5A,)}


def _setup_blocking_out(io: LockstepIOHarness) -> None:
    io.set_tx_ready(False)


def _resume_blocking_out(io: LockstepIOHarness, rtl_event: str, _result, event_index: int) -> None:
    if rtl_event == "blocked":
        io.set_tx_ready(True)


@cocotb.test()
async def test_lockstep_blocking_out_program(dut) -> None:
    result = await run_lockstep_program(
        dut,
        BLOCKING_OUT_PROGRAM,
        setup_io=_setup_blocking_out,
        on_event=_resume_blocking_out,
    )

    assert result.events.count("blocked") == 1
    assert result.io.reference.tx_snapshot() == {0x07: (0x2A,)}
