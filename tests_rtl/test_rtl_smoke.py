from __future__ import annotations

import cocotb
from cocotb.clock import Clock
from cocotb.triggers import RisingEdge


S_FETCH = 0


def reg_value(regs_flat: int, index: int) -> int:
    return (regs_flat >> (index * 8)) & 0xFF


async def preload_program(dut, program: list[int]) -> None:
    dut.tb_mem_we.value = 0
    for address, value in enumerate(program):
        dut.tb_mem_addr.value = address
        dut.tb_mem_wdata.value = value
        dut.tb_mem_we.value = 1
        await RisingEdge(dut.clk)
    dut.tb_mem_we.value = 0


async def wait_for_event(dut, *, max_cycles: int = 128) -> str:
    for _ in range(max_cycles):
        await RisingEdge(dut.clk)
        if dut.dbg_retire.value:
            return "retire"
        if dut.dbg_blocked.value:
            return "blocked"
        if dut.dbg_halted.value:
            return "halted"
        if dut.dbg_illegal.value:
            return "illegal"
    raise AssertionError("timed out waiting for RTL architectural event")


@cocotb.test()
async def test_reset_state(dut) -> None:
    cocotb.start_soon(Clock(dut.clk, 10, unit="ns").start())

    dut.rst.value = 1
    dut.rx_valid.value = 0
    dut.tx_ready.value = 1
    dut.tb_mem_we.value = 0
    await RisingEdge(dut.clk)

    assert int(dut.dbg_pc.value) == 0
    assert int(dut.dbg_z.value) == 0
    assert int(dut.dbg_c.value) == 0
    assert int(dut.dbg_iosel.value) == 0
    assert int(dut.dbg_state.value) == S_FETCH
    assert int(dut.dbg_regs_flat.value) == 0


@cocotb.test()
async def test_add_program_retires_and_halts(dut) -> None:
    cocotb.start_soon(Clock(dut.clk, 10, unit="ns").start())

    dut.rst.value = 1
    dut.rx_valid.value = 0
    dut.tx_ready.value = 1
    await preload_program(dut, [0x83, 0x08, 0x84, 0x10, 0xC0, 0x7F])

    dut.rst.value = 0

    halted_seen = False
    for _ in range(16):
        event = await wait_for_event(dut)
        if event == "halted":
            halted_seen = True
            break

    assert halted_seen
    regs_flat = int(dut.dbg_regs_flat.value)
    assert reg_value(regs_flat, 0) == 0x07
    assert int(dut.dbg_z.value) == 0
    assert int(dut.dbg_c.value) == 0


@cocotb.test()
async def test_halt_program_stops_in_halt_state(dut) -> None:
    cocotb.start_soon(Clock(dut.clk, 10, unit="ns").start())

    dut.rst.value = 1
    dut.rx_valid.value = 0
    dut.tx_ready.value = 1
    await preload_program(dut, [0x7F])

    dut.rst.value = 0

    event = await wait_for_event(dut, max_cycles=4)

    assert event == "halted"
    assert int(dut.halted.value) == 1
