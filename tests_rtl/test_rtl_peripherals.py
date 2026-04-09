from __future__ import annotations

import cocotb
from cocotb.clock import Clock
from cocotb.triggers import RisingEdge

from min8.asm import assemble_source


PS2_CHANNEL = 0x10
AUDIO_CHANNEL = 0x11
WS2812_CHANNEL = 0x12
FILO_CHANNEL = 0x13
GENERIC_TX_CHANNEL = 0x03

DEFAULT_FILO_DEPTH = 8
DEFAULT_AUDIO_FIFO_DEPTH = 8
DEFAULT_AUDIO_SAMPLE_TICK_DIVISOR = 6250
DEFAULT_AUDIO_MOD_TICK_DIVISOR = 10
DEFAULT_WS2812_FIFO_DEPTH = 16
DEFAULT_WS2812_T0H_CYCLES = 40
DEFAULT_WS2812_T0L_CYCLES = 85
DEFAULT_WS2812_T1H_CYCLES = 80
DEFAULT_WS2812_T1L_CYCLES = 45


def _assemble_used_image(source: str) -> list[int]:
    result = assemble_source(source)
    if not result.used_addresses:
        return []
    used_end = result.used_addresses[-1] + 1
    return list(result.image[:used_end])


def _reg_value(regs_flat: int, index: int) -> int:
    return (regs_flat >> (index * 8)) & 0xFF


async def _preload_program(dut, program: list[int]) -> None:
    dut.tb_mem_we.value = 0
    for address, value in enumerate(program):
        dut.tb_mem_addr.value = address
        dut.tb_mem_wdata.value = value
        dut.tb_mem_we.value = 1
        await RisingEdge(dut.clk)
    dut.tb_mem_we.value = 0


async def _wait_cycles(dut, cycles: int) -> None:
    for _ in range(cycles):
        await RisingEdge(dut.clk)


async def _wait_for_event(dut, *, max_cycles: int = 256) -> str:
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


async def _wait_for_signal_level(dut, signal, level: int, *, max_cycles: int = 4096) -> None:
    for _ in range(max_cycles):
        if int(signal.value) == level:
            return
        await RisingEdge(dut.clk)
    raise AssertionError(f"timed out waiting for {signal._name}={level}")


async def _measure_signal_run(dut, signal, level: int, *, max_cycles: int = 4096) -> int:
    if int(signal.value) != level:
        raise AssertionError(f"expected {signal._name}={level}, got {int(signal.value)}")
    count = 0
    while int(signal.value) == level:
        count += 1
        if count > max_cycles:
            raise AssertionError(f"timed out measuring {signal._name}={level}")
        await RisingEdge(dut.clk)
    return count


async def _measure_high_cycles(dut, cycles: int) -> int:
    high_count = 0
    for _ in range(cycles):
        if int(dut.dbg_audio_dsm_out.value):
            high_count += 1
        await RisingEdge(dut.clk)
    return high_count


async def _send_ps2_frame(dut, value: int) -> None:
    data_bits = [(value >> bit) & 1 for bit in range(8)]
    parity_bit = 0 if (sum(data_bits) & 1) else 1
    frame_bits = [0, *data_bits, parity_bit, 1]

    dut.ps2_data.value = 1
    dut.ps2_clk.value = 1
    await _wait_cycles(dut, 8)

    for bit in frame_bits:
        dut.ps2_data.value = bit
        await _wait_cycles(dut, 4)
        dut.ps2_clk.value = 0
        await _wait_cycles(dut, 8)
        dut.ps2_clk.value = 1
        await _wait_cycles(dut, 8)

    dut.ps2_data.value = 1
    await _wait_cycles(dut, 12)


async def _start_dut_with_source(dut, source: str) -> None:
    cocotb.start_soon(Clock(dut.clk, 10, unit="ns").start())

    dut.rst.value = 1
    dut.rx_data.value = 0
    dut.rx_valid.value = 0
    dut.tx_ready.value = 1
    dut.ps2_clk.value = 1
    dut.ps2_data.value = 1
    dut.tb_mem_we.value = 0

    await _preload_program(dut, _assemble_used_image(source))
    dut.rst.value = 0


def _collect_tx_byte_if_any(dut, sink: list[int]) -> None:
    if not int(dut.dbg_io_valid.value):
        return
    if int(dut.dbg_io_dir.value) != 1:
        return
    if (int(dut.dbg_io_channel.value) & 0xFF) != GENERIC_TX_CHANNEL:
        return
    sink.append(int(dut.dbg_io_data.value) & 0xFF)


@cocotb.test()
async def test_ps2_empty_read_returns_zero_without_blocking(dut) -> None:
    await _start_dut_with_source(
        dut,
        """
    SETIOI 0x10
    IN R3
    HALT
""",
    )

    blocked_seen = False
    halted_seen = False
    for _ in range(12):
        event = await _wait_for_event(dut)
        if event == "blocked":
            blocked_seen = True
            break
        if event == "halted":
            halted_seen = True
            break

    assert not blocked_seen
    assert halted_seen
    assert _reg_value(int(dut.dbg_regs_flat.value), 3) == 0x00
    assert int(dut.dbg_ps2_rx_level.value) == 0


@cocotb.test()
async def test_ps2_scancode_frame_is_decoded_and_echoed(dut) -> None:
    await _start_dut_with_source(
        dut,
        """
    LI R4, 0x10
    LI R5, 0x03
    LI R6, loop
    SETIO R4

loop:
    IN R3
    OR R0, R3, R3
    JZ R6
    SETIO R5
    OUT R3
    HALT
""",
    )

    cocotb.start_soon(_send_ps2_frame(dut, 0x1C))

    observed_tx: list[int] = []
    halted_seen = False
    for _ in range(128):
        event = await _wait_for_event(dut, max_cycles=512)
        _collect_tx_byte_if_any(dut, observed_tx)
        if event == "halted":
            halted_seen = True
            break

    assert halted_seen
    assert observed_tx == [0x1C]
    assert int(dut.dbg_ps2_dropped_count.value) == 0
    assert int(dut.dbg_ps2_frame_error_count.value) == 0


@cocotb.test()
async def test_ps2_out_pushes_command_fifo(dut) -> None:
    await _start_dut_with_source(
        dut,
        """
    SETIOI 0x10
    LI R1, 0xED
    OUT R1
    HALT
""",
    )

    halted_seen = False
    for _ in range(12):
        event = await _wait_for_event(dut)
        if event == "halted":
            halted_seen = True
            break

    assert halted_seen
    assert int(dut.dbg_ps2_cmd_level.value) == 1


@cocotb.test()
async def test_audio_fifo_consumption_and_delta_sigma_density(dut) -> None:
    await _start_dut_with_source(
        dut,
        """
    SETIOI 0x11
    LI R1, 0x10
    LI R2, 0xF0
    OUT R1
    OUT R2
    HALT
""",
    )

    halted_seen = False
    for _ in range(16):
        event = await _wait_for_event(dut)
        if event == "halted":
            halted_seen = True
            break
    assert halted_seen
    assert int(dut.dbg_audio_fifo_level.value) == 2

    await _wait_cycles(dut, DEFAULT_AUDIO_SAMPLE_TICK_DIVISOR + 8)
    assert int(dut.dbg_audio_current_sample.value) == 0x10
    assert int(dut.dbg_audio_fifo_level.value) == 1
    low_density = await _measure_high_cycles(dut, 500)

    await _wait_cycles(dut, DEFAULT_AUDIO_SAMPLE_TICK_DIVISOR)
    assert int(dut.dbg_audio_current_sample.value) == 0xF0
    assert int(dut.dbg_audio_fifo_level.value) == 0
    high_density = await _measure_high_cycles(dut, 500)

    await _wait_cycles(dut, DEFAULT_AUDIO_SAMPLE_TICK_DIVISOR)
    assert int(dut.dbg_audio_current_sample.value) == 0x80
    assert int(dut.dbg_audio_underflow_count.value) >= 1
    assert high_density > low_density + 150


@cocotb.test()
async def test_audio_full_write_blocks(dut) -> None:
    repeated_outs = "\n".join("    OUT R1" for _ in range(DEFAULT_AUDIO_FIFO_DEPTH + 1))
    program = f"""
    SETIOI 0x11
    LI R1, 0xAA
{repeated_outs}
    HALT
"""
    await _start_dut_with_source(dut, program)

    blocked_seen = False
    for _ in range(DEFAULT_AUDIO_FIFO_DEPTH + 12):
        event = await _wait_for_event(dut)
        if event == "blocked":
            blocked_seen = True
            break

    assert blocked_seen
    assert (int(dut.dbg_io_channel.value) & 0xFF) == AUDIO_CHANNEL
    assert int(dut.dbg_io_dir.value) == 1
    assert int(dut.dbg_audio_fifo_level.value) == DEFAULT_AUDIO_FIFO_DEPTH


@cocotb.test()
async def test_ws2812_first_bits_use_configured_timing(dut) -> None:
    await _start_dut_with_source(
        dut,
        """
    SETIOI 0x12
    LI R1, 0x80
    OUT R1
    HALT
""",
    )

    await _wait_for_signal_level(dut, dut.dbg_ws2812_out, 1, max_cycles=256)
    high_1 = await _measure_signal_run(dut, dut.dbg_ws2812_out, 1)
    low_1 = await _measure_signal_run(dut, dut.dbg_ws2812_out, 0)
    high_0 = await _measure_signal_run(dut, dut.dbg_ws2812_out, 1)
    low_0 = await _measure_signal_run(dut, dut.dbg_ws2812_out, 0)

    assert high_1 == DEFAULT_WS2812_T1H_CYCLES
    assert low_1 == DEFAULT_WS2812_T1L_CYCLES
    assert high_0 == DEFAULT_WS2812_T0H_CYCLES
    assert low_0 == DEFAULT_WS2812_T0L_CYCLES


@cocotb.test()
async def test_ws2812_full_write_blocks(dut) -> None:
    repeated_outs = "\n".join("    OUT R1" for _ in range(DEFAULT_WS2812_FIFO_DEPTH + 2))
    program = f"""
    SETIOI 0x12
    LI R1, 0xAA
{repeated_outs}
    HALT
"""
    await _start_dut_with_source(dut, program)

    blocked_seen = False
    for _ in range(DEFAULT_WS2812_FIFO_DEPTH + 12):
        event = await _wait_for_event(dut)
        if event == "blocked":
            blocked_seen = True
            break

    assert blocked_seen
    assert (int(dut.dbg_io_channel.value) & 0xFF) == WS2812_CHANNEL
    assert int(dut.dbg_io_dir.value) == 1
    assert int(dut.dbg_ws2812_fifo_level.value) == DEFAULT_WS2812_FIFO_DEPTH


@cocotb.test()
async def test_filo_program_emits_lifo_order(dut) -> None:
    await _start_dut_with_source(
        dut,
        """
    SETIOI 0x13
    LI R1, 0x11
    LI R2, 0x22
    LI R3, 0x33

    OUT R1
    OUT R2
    OUT R3

    IN R4
    IN R5
    IN R6

    SETIOI 0x03
    OUT R4
    OUT R5
    OUT R6
    HALT
""",
    )

    observed_tx: list[int] = []
    halted_seen = False
    for _ in range(32):
        event = await _wait_for_event(dut)
        _collect_tx_byte_if_any(dut, observed_tx)
        if event == "halted":
            halted_seen = True
            break

    assert halted_seen
    assert observed_tx == [0x33, 0x22, 0x11]
    assert int(dut.dbg_filo_level.value) == 0
    assert int(dut.dbg_filo_empty.value) == 1
    assert int(dut.dbg_filo_full.value) == 0


@cocotb.test()
async def test_filo_empty_read_blocks(dut) -> None:
    await _start_dut_with_source(
        dut,
        """
    SETIOI 0x13
    IN R1
    HALT
""",
    )

    blocked_seen = False
    for _ in range(8):
        event = await _wait_for_event(dut)
        if event == "blocked":
            blocked_seen = True
            break

    assert blocked_seen
    assert (int(dut.dbg_io_channel.value) & 0xFF) == FILO_CHANNEL
    assert int(dut.dbg_io_dir.value) == 0
    assert int(dut.dbg_filo_level.value) == 0
    assert int(dut.dbg_filo_empty.value) == 1


@cocotb.test()
async def test_filo_full_write_blocks(dut) -> None:
    repeated_outs = "\n".join("    OUT R1" for _ in range(DEFAULT_FILO_DEPTH + 1))
    program = f"""
    SETIOI 0x13
    LI R1, 0xAA
{repeated_outs}
    HALT
"""
    await _start_dut_with_source(dut, program)

    blocked_seen = False
    for _ in range(DEFAULT_FILO_DEPTH + 8):
        event = await _wait_for_event(dut)
        if event == "blocked":
            blocked_seen = True
            break

    assert blocked_seen
    assert (int(dut.dbg_io_channel.value) & 0xFF) == FILO_CHANNEL
    assert int(dut.dbg_io_dir.value) == 1
    assert int(dut.dbg_io_data.value) == 0xAA
    assert int(dut.dbg_filo_level.value) == DEFAULT_FILO_DEPTH
    assert int(dut.dbg_filo_empty.value) == 0
    assert int(dut.dbg_filo_full.value) == 1
