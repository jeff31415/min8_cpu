from __future__ import annotations

from collections import defaultdict, deque
from dataclasses import dataclass

import cocotb
from cocotb.clock import Clock
from cocotb.triggers import NextTimeStep, ReadOnly, RisingEdge

from min8.asm import assemble_source
from min8.cpu import Min8CPU, StepResult
from min8.exceptions import WouldBlockOnIO


CLOCK_PERIOD_NS = 10
S_FETCH = 0
S_IOWAIT = 3
S_HALT = 4


class ScriptedIOBackend:
    def __init__(self) -> None:
        self.rx: dict[int, deque[int]] = defaultdict(deque)
        self.tx: dict[int, list[int]] = defaultdict(list)
        self.tx_ready = True

    def queue_rx(self, channel: int, *values: int) -> None:
        fifo = self.rx[channel & 0xFF]
        for value in values:
            fifo.append(value & 0xFF)

    def set_tx_ready(self, ready: bool) -> None:
        self.tx_ready = bool(ready)

    def read(self, channel: int) -> int:
        channel &= 0xFF
        if not self.rx[channel]:
            raise WouldBlockOnIO("in", channel)
        return self.rx[channel].popleft()

    def write(self, channel: int, value: int) -> None:
        channel &= 0xFF
        if not self.tx_ready:
            raise WouldBlockOnIO("out", channel)
        self.tx[channel].append(value & 0xFF)

    def rx_snapshot(self) -> dict[int, tuple[int, ...]]:
        return {
            channel: tuple(values)
            for channel, values in sorted(self.rx.items())
            if values
        }

    def tx_snapshot(self) -> dict[int, tuple[int, ...]]:
        return {
            channel: tuple(values)
            for channel, values in sorted(self.tx.items())
            if values
        }


class DutIOModel:
    def __init__(self) -> None:
        self.rx: dict[int, deque[int]] = defaultdict(deque)
        self.tx: dict[int, list[int]] = defaultdict(list)
        self.tx_ready = True

    def queue_rx(self, channel: int, *values: int) -> None:
        fifo = self.rx[channel & 0xFF]
        for value in values:
            fifo.append(value & 0xFF)

    def set_tx_ready(self, ready: bool) -> None:
        self.tx_ready = bool(ready)

    def drive_inputs(self, dut) -> None:
        channel = int(dut.io_chan.value) & 0xFF
        fifo = self.rx[channel]
        dut.rx_valid.value = int(bool(fifo))
        dut.rx_data.value = fifo[0] if fifo else 0
        dut.tx_ready.value = int(self.tx_ready)

    def observe_transfer(self, dut) -> None:
        if not int(dut.dbg_io_valid.value):
            return
        channel = int(dut.dbg_io_channel.value) & 0xFF
        value = int(dut.dbg_io_data.value) & 0xFF
        if int(dut.dbg_io_dir.value) == 0:
            if not self.rx[channel]:
                raise AssertionError(f"RTL consumed missing RX byte on channel 0x{channel:02X}")
            expected = self.rx[channel].popleft()
            if expected != value:
                raise AssertionError(
                    f"RTL consumed RX byte 0x{value:02X}, expected 0x{expected:02X} on channel 0x{channel:02X}"
                )
        else:
            self.tx[channel].append(value)

    def rx_snapshot(self) -> dict[int, tuple[int, ...]]:
        return {
            channel: tuple(values)
            for channel, values in sorted(self.rx.items())
            if values
        }

    def tx_snapshot(self) -> dict[int, tuple[int, ...]]:
        return {
            channel: tuple(values)
            for channel, values in sorted(self.tx.items())
            if values
        }


class LockstepIOHarness:
    def __init__(self) -> None:
        self.reference = ScriptedIOBackend()
        self.dut = DutIOModel()

    def queue_rx(self, channel: int, *values: int) -> None:
        self.reference.queue_rx(channel, *values)
        self.dut.queue_rx(channel, *values)

    def set_tx_ready(self, ready: bool) -> None:
        self.reference.set_tx_ready(ready)
        self.dut.set_tx_ready(ready)

    def drive_dut(self, dut) -> None:
        self.dut.drive_inputs(dut)

    def observe_rtl_event(self, dut) -> None:
        self.dut.observe_transfer(dut)

    def assert_synced(self) -> None:
        if self.reference.rx_snapshot() != self.dut.rx_snapshot():
            raise AssertionError(
                f"RX queue mismatch: ref={self.reference.rx_snapshot()} rtl={self.dut.rx_snapshot()}"
            )
        if self.reference.tx_snapshot() != self.dut.tx_snapshot():
            raise AssertionError(
                f"TX log mismatch: ref={self.reference.tx_snapshot()} rtl={self.dut.tx_snapshot()}"
            )
        if self.reference.tx_ready != self.dut.tx_ready:
            raise AssertionError(
                f"tx_ready mismatch: ref={self.reference.tx_ready} rtl={self.dut.tx_ready}"
            )


@dataclass(frozen=True)
class LockstepResult:
    cpu: Min8CPU
    io: LockstepIOHarness
    events: tuple[str, ...]


def _rtl_registers(dut) -> list[int]:
    regs_flat = int(dut.dbg_regs_flat.value)
    return [(regs_flat >> (index * 8)) & 0xFF for index in range(8)]


def _rtl_memory(dut) -> list[int]:
    return [int(dut.u_mem.mem[index].value) & 0xFF for index in range(256)]


def _expected_state_code(event: str) -> int:
    if event == "blocked":
        return S_IOWAIT
    if event == "halted":
        return S_HALT
    return S_FETCH


def _event_from_status(status: str) -> str:
    return {
        "retired": "retire",
        "blocked": "blocked",
        "halted": "halted",
    }[status]


async def preload_program(dut, program: bytes) -> None:
    dut.tb_mem_we.value = 0
    for address, value in enumerate(program):
        dut.tb_mem_addr.value = address
        dut.tb_mem_wdata.value = value
        dut.tb_mem_we.value = 1
        await RisingEdge(dut.clk)
    dut.tb_mem_we.value = 0


async def wait_for_event(dut, io: LockstepIOHarness, *, max_cycles: int = 128) -> str:
    for _ in range(max_cycles):
        await NextTimeStep()
        io.drive_dut(dut)
        await RisingEdge(dut.clk)
        await ReadOnly()
        if int(dut.dbg_retire.value):
            io.observe_rtl_event(dut)
            return "retire"
        if int(dut.dbg_blocked.value):
            return "blocked"
        if int(dut.dbg_halted.value):
            return "halted"
        if int(dut.dbg_illegal.value):
            return "illegal"
    raise AssertionError("timed out waiting for RTL architectural event")


def compare_against_reference(dut, cpu: Min8CPU, result: StepResult, rtl_event: str) -> None:
    expected_event = _event_from_status(result.status)
    if rtl_event != expected_event:
        raise AssertionError(f"event mismatch: expected {expected_event}, got {rtl_event}")

    if int(dut.dbg_pc_before.value) != result.pc_before:
        raise AssertionError(
            f"pc_before mismatch: rtl=0x{int(dut.dbg_pc_before.value):02X} ref=0x{result.pc_before:02X}"
        )
    if int(dut.dbg_opcode.value) != result.opcode:
        raise AssertionError(
            f"opcode mismatch: rtl=0x{int(dut.dbg_opcode.value):02X} ref=0x{result.opcode:02X}"
        )
    if int(dut.dbg_pc.value) != cpu.state.pc:
        raise AssertionError(
            f"pc mismatch: rtl=0x{int(dut.dbg_pc.value):02X} ref=0x{cpu.state.pc:02X}"
        )
    if _rtl_registers(dut) != cpu.state.registers:
        raise AssertionError(f"register mismatch: rtl={_rtl_registers(dut)} ref={cpu.state.registers}")
    if _rtl_memory(dut) != list(cpu.state.memory):
        raise AssertionError("memory image mismatch between RTL and reference model")
    if int(dut.dbg_z.value) != cpu.state.z or int(dut.dbg_c.value) != cpu.state.c:
        raise AssertionError(
            f"flag mismatch: rtl ZC={(int(dut.dbg_z.value), int(dut.dbg_c.value))} ref ZC={(cpu.state.z, cpu.state.c)}"
        )
    if int(dut.dbg_iosel.value) != cpu.state.iosel:
        raise AssertionError(
            f"IOSEL mismatch: rtl=0x{int(dut.dbg_iosel.value):02X} ref=0x{cpu.state.iosel:02X}"
        )
    if int(dut.halted.value) != int(cpu.state.halted):
        raise AssertionError(
            f"halted mismatch: rtl={int(dut.halted.value)} ref={int(cpu.state.halted)}"
        )
    if int(dut.illegal_instr.value) != 0 or int(dut.faulted.value) != 0:
        raise AssertionError(
            f"unexpected fault state: illegal={int(dut.illegal_instr.value)} faulted={int(dut.faulted.value)}"
        )
    if int(dut.dbg_state.value) != _expected_state_code(rtl_event):
        raise AssertionError(
            f"state mismatch: rtl={int(dut.dbg_state.value)} expected={_expected_state_code(rtl_event)}"
        )

    expected_mem_write = result.memory_writes[0] if result.memory_writes else None
    if expected_mem_write is None:
        if int(dut.dbg_mem_write_en.value) != 0:
            raise AssertionError("unexpected RTL memory write pulse")
    else:
        if int(dut.dbg_mem_write_en.value) != 1:
            raise AssertionError("missing RTL memory write pulse")
        if int(dut.dbg_mem_write_addr.value) != expected_mem_write.address:
            raise AssertionError(
                f"memory write address mismatch: rtl=0x{int(dut.dbg_mem_write_addr.value):02X} ref=0x{expected_mem_write.address:02X}"
            )
        if int(dut.dbg_mem_write_data.value) != expected_mem_write.after:
            raise AssertionError(
                f"memory write data mismatch: rtl=0x{int(dut.dbg_mem_write_data.value):02X} ref=0x{expected_mem_write.after:02X}"
            )

    expected_io = result.io_transfer
    if expected_io is None:
        if int(dut.dbg_io_valid.value) != 0:
            raise AssertionError("unexpected RTL I/O transfer pulse")
    else:
        if int(dut.dbg_io_valid.value) != 1:
            raise AssertionError("missing RTL I/O transfer pulse")
        expected_dir = 0 if expected_io.direction == "in" else 1
        if int(dut.dbg_io_dir.value) != expected_dir:
            raise AssertionError(
                f"I/O direction mismatch: rtl={int(dut.dbg_io_dir.value)} ref={expected_dir}"
            )
        if int(dut.dbg_io_channel.value) != expected_io.channel:
            raise AssertionError(
                f"I/O channel mismatch: rtl=0x{int(dut.dbg_io_channel.value):02X} ref=0x{expected_io.channel:02X}"
            )
        if int(dut.dbg_io_data.value) != expected_io.value:
            raise AssertionError(
                f"I/O data mismatch: rtl=0x{int(dut.dbg_io_data.value):02X} ref=0x{expected_io.value:02X}"
            )

    expected_block = result.blocked_on
    if expected_block is not None:
        expected_dir = 0 if expected_block.direction == "in" else 1
        if int(dut.dbg_io_dir.value) != expected_dir:
            raise AssertionError(
                f"blocked I/O direction mismatch: rtl={int(dut.dbg_io_dir.value)} ref={expected_dir}"
            )
        if int(dut.dbg_io_channel.value) != expected_block.channel:
            raise AssertionError(
                f"blocked I/O channel mismatch: rtl=0x{int(dut.dbg_io_channel.value):02X} ref=0x{expected_block.channel:02X}"
            )


async def run_lockstep_program(
    dut,
    source: str,
    *,
    max_events: int = 64,
    setup_io=None,
    on_event=None,
) -> LockstepResult:
    cocotb.start_soon(Clock(dut.clk, CLOCK_PERIOD_NS, unit="ns").start())

    io = LockstepIOHarness()
    if setup_io is not None:
        setup_io(io)

    image = assemble_source(source).image

    dut.rst.value = 1
    dut.rx_valid.value = 0
    dut.rx_data.value = 0
    dut.tx_ready.value = 1
    dut.tb_mem_we.value = 0
    await preload_program(dut, image)
    io.drive_dut(dut)
    await RisingEdge(dut.clk)
    dut.rst.value = 0

    cpu = Min8CPU(io_backend=io.reference)
    cpu.load_image(image)

    events: list[str] = []
    for event_index in range(max_events):
        rtl_event = await wait_for_event(dut, io)
        if rtl_event == "illegal":
            raise AssertionError("unexpected illegal instruction during lockstep test")
        result = cpu.step()
        compare_against_reference(dut, cpu, result, rtl_event)
        io.assert_synced()
        events.append(rtl_event)
        if on_event is not None:
            on_event(io, rtl_event, result, event_index)
        if rtl_event == "halted":
            return LockstepResult(cpu=cpu, io=io, events=tuple(events))

    raise AssertionError("program did not halt within the event budget")
