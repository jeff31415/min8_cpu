from __future__ import annotations

from collections import defaultdict, deque
from dataclasses import asdict, dataclass
from pathlib import Path
from typing import Any, Callable

import cocotb
from cocotb.clock import Clock
from cocotb.triggers import NextTimeStep, ReadOnly, RisingEdge

from min8.asm import assemble_source
from min8.cpu import Min8CPU, StepResult
from min8.exceptions import IllegalInstruction, WouldBlockOnIO

from .randomized import write_failure_artifact


CLOCK_PERIOD_NS = 10
S_FETCH = 0
S_IOWAIT = 3
S_HALT = 4
S_FAULT = 5


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

    def snapshot(self) -> dict[str, Any]:
        return {
            "reference": {
                "rx": {f"0x{channel:02X}": list(values) for channel, values in self.reference.rx_snapshot().items()},
                "tx": {f"0x{channel:02X}": list(values) for channel, values in self.reference.tx_snapshot().items()},
                "tx_ready": self.reference.tx_ready,
            },
            "rtl": {
                "rx": {f"0x{channel:02X}": list(values) for channel, values in self.dut.rx_snapshot().items()},
                "tx": {f"0x{channel:02X}": list(values) for channel, values in self.dut.tx_snapshot().items()},
                "tx_ready": self.dut.tx_ready,
            },
        }


@dataclass(frozen=True)
class CPUSnapshot:
    registers: tuple[int, ...]
    memory: tuple[int, ...]
    pc: int
    z: int
    c: int
    iosel: int
    halted: bool
    pending_pc: int | None
    pending_opcode: int | None
    pending_instruction: str | None


@dataclass(frozen=True)
class RTLSnapshot:
    state: int
    pc_before: int
    opcode: int
    registers: tuple[int, ...]
    memory: tuple[int, ...]
    pc: int
    z: int
    c: int
    iosel: int
    halted: bool
    illegal_instr: bool
    faulted: bool
    dbg_retire: bool
    dbg_blocked: bool
    dbg_halted: bool
    dbg_illegal: bool
    mem_write_en: bool
    mem_write_addr: int
    mem_write_data: int
    io_valid: bool
    io_dir: int
    io_channel: int
    io_data: int


@dataclass(frozen=True)
class TraceEntry:
    event_index: int
    rtl_event: str
    result_status: str
    pc_before: int
    opcode: int
    instruction_text: str
    next_pc: int
    register_writes: tuple[dict[str, Any], ...]
    memory_writes: tuple[dict[str, Any], ...]
    io_transfer: dict[str, Any] | None
    blocked_on: dict[str, Any] | None
    rtl_state: int
    rtl_pc: int
    rtl_z: int
    rtl_c: int
    rtl_iosel: int
    halted: bool


@dataclass(frozen=True)
class LockstepResult:
    cpu: Min8CPU
    io: LockstepIOHarness
    image: bytes
    events: tuple[str, ...]
    trace: tuple[TraceEntry, ...]
    outcome: str
    completed_events: int
    case_name: str | None = None
    cycle_first_seen_event_index: int | None = None
    cycle_repeat_event_index: int | None = None


class LockstepFailure(AssertionError):
    def __init__(
        self,
        message: str,
        *,
        rtl_event: str | None = None,
        step_result: StepResult | None = None,
        reference_before: CPUSnapshot | None = None,
        reference_after: CPUSnapshot | None = None,
        rtl_snapshot: RTLSnapshot | None = None,
    ) -> None:
        super().__init__(message)
        self.rtl_event = rtl_event
        self.step_result = step_result
        self.reference_before = reference_before
        self.reference_after = reference_after
        self.rtl_snapshot = rtl_snapshot


def _rtl_registers(dut) -> tuple[int, ...]:
    regs_flat = int(dut.dbg_regs_flat.value)
    return tuple((regs_flat >> (index * 8)) & 0xFF for index in range(8))


def _rtl_memory(dut) -> tuple[int, ...]:
    return tuple(int(dut.u_mem.mem[index].value) & 0xFF for index in range(256))


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


def _serialize_step_result(result: StepResult | None) -> dict[str, Any] | None:
    if result is None:
        return None
    data = asdict(result)
    data["register_writes"] = list(data["register_writes"])
    data["memory_writes"] = list(data["memory_writes"])
    return data


def _capture_cpu_snapshot(cpu: Min8CPU) -> CPUSnapshot:
    pending = cpu.state.pending
    return CPUSnapshot(
        registers=tuple(cpu.state.registers),
        memory=tuple(cpu.state.memory),
        pc=cpu.state.pc,
        z=cpu.state.z,
        c=cpu.state.c,
        iosel=cpu.state.iosel,
        halted=bool(cpu.state.halted),
        pending_pc=None if pending is None else pending.pc_before,
        pending_opcode=None if pending is None else pending.opcode,
        pending_instruction=None if pending is None else pending.decoded.instruction_text,
    )


def _capture_rtl_snapshot(dut) -> RTLSnapshot:
    return RTLSnapshot(
        state=int(dut.dbg_state.value),
        pc_before=int(dut.dbg_pc_before.value),
        opcode=int(dut.dbg_opcode.value),
        registers=_rtl_registers(dut),
        memory=_rtl_memory(dut),
        pc=int(dut.dbg_pc.value),
        z=int(dut.dbg_z.value),
        c=int(dut.dbg_c.value),
        iosel=int(dut.dbg_iosel.value),
        halted=bool(int(dut.halted.value)),
        illegal_instr=bool(int(dut.illegal_instr.value)),
        faulted=bool(int(dut.faulted.value)),
        dbg_retire=bool(int(dut.dbg_retire.value)),
        dbg_blocked=bool(int(dut.dbg_blocked.value)),
        dbg_halted=bool(int(dut.dbg_halted.value)),
        dbg_illegal=bool(int(dut.dbg_illegal.value)),
        mem_write_en=bool(int(dut.dbg_mem_write_en.value)),
        mem_write_addr=int(dut.dbg_mem_write_addr.value),
        mem_write_data=int(dut.dbg_mem_write_data.value),
        io_valid=bool(int(dut.dbg_io_valid.value)),
        io_dir=int(dut.dbg_io_dir.value),
        io_channel=int(dut.dbg_io_channel.value),
        io_data=int(dut.dbg_io_data.value),
    )


def make_reference_state_key(cpu: Min8CPU, io: LockstepIOHarness) -> tuple[Any, ...]:
    return (
        _capture_cpu_snapshot(cpu),
        tuple(sorted(io.reference.rx_snapshot().items())),
        tuple(sorted(io.reference.tx_snapshot().items())),
        io.reference.tx_ready,
    )


def _make_trace_entry(event_index: int, rtl_event: str, result: StepResult, rtl_snapshot: RTLSnapshot) -> TraceEntry:
    return TraceEntry(
        event_index=event_index,
        rtl_event=rtl_event,
        result_status=result.status,
        pc_before=result.pc_before,
        opcode=result.opcode,
        instruction_text=result.instruction_text,
        next_pc=result.next_pc,
        register_writes=tuple(asdict(write) for write in result.register_writes),
        memory_writes=tuple(asdict(write) for write in result.memory_writes),
        io_transfer=None if result.io_transfer is None else asdict(result.io_transfer),
        blocked_on=None if result.blocked_on is None else asdict(result.blocked_on),
        rtl_state=rtl_snapshot.state,
        rtl_pc=rtl_snapshot.pc,
        rtl_z=rtl_snapshot.z,
        rtl_c=rtl_snapshot.c,
        rtl_iosel=rtl_snapshot.iosel,
        halted=rtl_snapshot.halted,
    )


def _make_illegal_trace_entry(event_index: int, exc: IllegalInstruction, rtl_snapshot: RTLSnapshot) -> TraceEntry:
    return TraceEntry(
        event_index=event_index,
        rtl_event="illegal",
        result_status="illegal",
        pc_before=exc.pc,
        opcode=exc.opcode,
        instruction_text=f"ILLEGAL 0x{exc.opcode:02X}",
        next_pc=rtl_snapshot.pc,
        register_writes=(),
        memory_writes=(),
        io_transfer=None,
        blocked_on=None,
        rtl_state=rtl_snapshot.state,
        rtl_pc=rtl_snapshot.pc,
        rtl_z=rtl_snapshot.z,
        rtl_c=rtl_snapshot.c,
        rtl_iosel=rtl_snapshot.iosel,
        halted=rtl_snapshot.halted,
    )


def compare_against_reference(
    reference_after: CPUSnapshot,
    rtl_snapshot: RTLSnapshot,
    result: StepResult,
    rtl_event: str,
) -> None:
    expected_event = _event_from_status(result.status)
    if rtl_event != expected_event:
        raise LockstepFailure(
            f"event mismatch: expected {expected_event}, got {rtl_event}",
            rtl_event=rtl_event,
            step_result=result,
            reference_after=reference_after,
            rtl_snapshot=rtl_snapshot,
        )

    if rtl_snapshot.pc_before != result.pc_before:
        raise LockstepFailure(
            f"pc_before mismatch: rtl=0x{rtl_snapshot.pc_before:02X} ref=0x{result.pc_before:02X}",
            rtl_event=rtl_event,
            step_result=result,
            reference_after=reference_after,
            rtl_snapshot=rtl_snapshot,
        )
    if rtl_snapshot.opcode != result.opcode:
        raise LockstepFailure(
            f"opcode mismatch: rtl=0x{rtl_snapshot.opcode:02X} ref=0x{result.opcode:02X}",
            rtl_event=rtl_event,
            step_result=result,
            reference_after=reference_after,
            rtl_snapshot=rtl_snapshot,
        )
    if rtl_snapshot.pc != reference_after.pc:
        raise LockstepFailure(
            f"pc mismatch: rtl=0x{rtl_snapshot.pc:02X} ref=0x{reference_after.pc:02X}",
            rtl_event=rtl_event,
            step_result=result,
            reference_after=reference_after,
            rtl_snapshot=rtl_snapshot,
        )
    if rtl_snapshot.registers != reference_after.registers:
        raise LockstepFailure(
            f"register mismatch: rtl={list(rtl_snapshot.registers)} ref={list(reference_after.registers)}",
            rtl_event=rtl_event,
            step_result=result,
            reference_after=reference_after,
            rtl_snapshot=rtl_snapshot,
        )
    if rtl_snapshot.memory != reference_after.memory:
        raise LockstepFailure(
            "memory image mismatch between RTL and reference model",
            rtl_event=rtl_event,
            step_result=result,
            reference_after=reference_after,
            rtl_snapshot=rtl_snapshot,
        )
    if rtl_snapshot.z != reference_after.z or rtl_snapshot.c != reference_after.c:
        raise LockstepFailure(
            f"flag mismatch: rtl ZC={(rtl_snapshot.z, rtl_snapshot.c)} ref ZC={(reference_after.z, reference_after.c)}",
            rtl_event=rtl_event,
            step_result=result,
            reference_after=reference_after,
            rtl_snapshot=rtl_snapshot,
        )
    if rtl_snapshot.iosel != reference_after.iosel:
        raise LockstepFailure(
            f"IOSEL mismatch: rtl=0x{rtl_snapshot.iosel:02X} ref=0x{reference_after.iosel:02X}",
            rtl_event=rtl_event,
            step_result=result,
            reference_after=reference_after,
            rtl_snapshot=rtl_snapshot,
        )
    if rtl_snapshot.halted != reference_after.halted:
        raise LockstepFailure(
            f"halted mismatch: rtl={int(rtl_snapshot.halted)} ref={int(reference_after.halted)}",
            rtl_event=rtl_event,
            step_result=result,
            reference_after=reference_after,
            rtl_snapshot=rtl_snapshot,
        )
    if rtl_snapshot.illegal_instr or rtl_snapshot.faulted:
        raise LockstepFailure(
            f"unexpected fault state: illegal={int(rtl_snapshot.illegal_instr)} faulted={int(rtl_snapshot.faulted)}",
            rtl_event=rtl_event,
            step_result=result,
            reference_after=reference_after,
            rtl_snapshot=rtl_snapshot,
        )
    if rtl_snapshot.state != _expected_state_code(rtl_event):
        raise LockstepFailure(
            f"state mismatch: rtl={rtl_snapshot.state} expected={_expected_state_code(rtl_event)}",
            rtl_event=rtl_event,
            step_result=result,
            reference_after=reference_after,
            rtl_snapshot=rtl_snapshot,
        )

    expected_mem_write = result.memory_writes[0] if result.memory_writes else None
    if expected_mem_write is None:
        if rtl_snapshot.mem_write_en:
            raise LockstepFailure(
                "unexpected RTL memory write pulse",
                rtl_event=rtl_event,
                step_result=result,
                reference_after=reference_after,
                rtl_snapshot=rtl_snapshot,
            )
    else:
        if not rtl_snapshot.mem_write_en:
            raise LockstepFailure(
                "missing RTL memory write pulse",
                rtl_event=rtl_event,
                step_result=result,
                reference_after=reference_after,
                rtl_snapshot=rtl_snapshot,
            )
        if rtl_snapshot.mem_write_addr != expected_mem_write.address:
            raise LockstepFailure(
                f"memory write address mismatch: rtl=0x{rtl_snapshot.mem_write_addr:02X} ref=0x{expected_mem_write.address:02X}",
                rtl_event=rtl_event,
                step_result=result,
                reference_after=reference_after,
                rtl_snapshot=rtl_snapshot,
            )
        if rtl_snapshot.mem_write_data != expected_mem_write.after:
            raise LockstepFailure(
                f"memory write data mismatch: rtl=0x{rtl_snapshot.mem_write_data:02X} ref=0x{expected_mem_write.after:02X}",
                rtl_event=rtl_event,
                step_result=result,
                reference_after=reference_after,
                rtl_snapshot=rtl_snapshot,
            )

    expected_io = result.io_transfer
    if expected_io is None:
        if rtl_snapshot.io_valid:
            raise LockstepFailure(
                "unexpected RTL I/O transfer pulse",
                rtl_event=rtl_event,
                step_result=result,
                reference_after=reference_after,
                rtl_snapshot=rtl_snapshot,
            )
    else:
        if not rtl_snapshot.io_valid:
            raise LockstepFailure(
                "missing RTL I/O transfer pulse",
                rtl_event=rtl_event,
                step_result=result,
                reference_after=reference_after,
                rtl_snapshot=rtl_snapshot,
            )
        expected_dir = 0 if expected_io.direction == "in" else 1
        if rtl_snapshot.io_dir != expected_dir:
            raise LockstepFailure(
                f"I/O direction mismatch: rtl={rtl_snapshot.io_dir} ref={expected_dir}",
                rtl_event=rtl_event,
                step_result=result,
                reference_after=reference_after,
                rtl_snapshot=rtl_snapshot,
            )
        if rtl_snapshot.io_channel != expected_io.channel:
            raise LockstepFailure(
                f"I/O channel mismatch: rtl=0x{rtl_snapshot.io_channel:02X} ref=0x{expected_io.channel:02X}",
                rtl_event=rtl_event,
                step_result=result,
                reference_after=reference_after,
                rtl_snapshot=rtl_snapshot,
            )
        if rtl_snapshot.io_data != expected_io.value:
            raise LockstepFailure(
                f"I/O data mismatch: rtl=0x{rtl_snapshot.io_data:02X} ref=0x{expected_io.value:02X}",
                rtl_event=rtl_event,
                step_result=result,
                reference_after=reference_after,
                rtl_snapshot=rtl_snapshot,
            )

    expected_block = result.blocked_on
    if expected_block is not None:
        expected_dir = 0 if expected_block.direction == "in" else 1
        if rtl_snapshot.io_dir != expected_dir:
            raise LockstepFailure(
                f"blocked I/O direction mismatch: rtl={rtl_snapshot.io_dir} ref={expected_dir}",
                rtl_event=rtl_event,
                step_result=result,
                reference_after=reference_after,
                rtl_snapshot=rtl_snapshot,
            )
        if rtl_snapshot.io_channel != expected_block.channel:
            raise LockstepFailure(
                f"blocked I/O channel mismatch: rtl=0x{rtl_snapshot.io_channel:02X} ref=0x{expected_block.channel:02X}",
                rtl_event=rtl_event,
                step_result=result,
                reference_after=reference_after,
                rtl_snapshot=rtl_snapshot,
            )


def compare_illegal_against_reference(
    reference_after: CPUSnapshot,
    rtl_snapshot: RTLSnapshot,
    exc: IllegalInstruction,
) -> None:
    if rtl_snapshot.pc_before != exc.pc:
        raise LockstepFailure(
            f"illegal pc_before mismatch: rtl=0x{rtl_snapshot.pc_before:02X} ref=0x{exc.pc:02X}",
            rtl_event="illegal",
            reference_after=reference_after,
            rtl_snapshot=rtl_snapshot,
        )
    if rtl_snapshot.opcode != exc.opcode:
        raise LockstepFailure(
            f"illegal opcode mismatch: rtl=0x{rtl_snapshot.opcode:02X} ref=0x{exc.opcode:02X}",
            rtl_event="illegal",
            reference_after=reference_after,
            rtl_snapshot=rtl_snapshot,
        )
    if not rtl_snapshot.illegal_instr or not rtl_snapshot.faulted:
        raise LockstepFailure(
            f"illegal fault flags missing: illegal={int(rtl_snapshot.illegal_instr)} faulted={int(rtl_snapshot.faulted)}",
            rtl_event="illegal",
            reference_after=reference_after,
            rtl_snapshot=rtl_snapshot,
        )
    if rtl_snapshot.state != S_FAULT:
        raise LockstepFailure(
            f"illegal state mismatch: rtl={rtl_snapshot.state} expected={S_FAULT}",
            rtl_event="illegal",
            reference_after=reference_after,
            rtl_snapshot=rtl_snapshot,
        )
    if rtl_snapshot.pc != reference_after.pc:
        raise LockstepFailure(
            f"illegal pc mismatch: rtl=0x{rtl_snapshot.pc:02X} ref=0x{reference_after.pc:02X}",
            rtl_event="illegal",
            reference_after=reference_after,
            rtl_snapshot=rtl_snapshot,
        )
    if rtl_snapshot.registers != reference_after.registers:
        raise LockstepFailure(
            f"illegal register mismatch: rtl={list(rtl_snapshot.registers)} ref={list(reference_after.registers)}",
            rtl_event="illegal",
            reference_after=reference_after,
            rtl_snapshot=rtl_snapshot,
        )
    if rtl_snapshot.memory != reference_after.memory:
        raise LockstepFailure(
            "illegal memory image mismatch between RTL and reference model",
            rtl_event="illegal",
            reference_after=reference_after,
            rtl_snapshot=rtl_snapshot,
        )
    if rtl_snapshot.z != reference_after.z or rtl_snapshot.c != reference_after.c:
        raise LockstepFailure(
            f"illegal flag mismatch: rtl ZC={(rtl_snapshot.z, rtl_snapshot.c)} ref ZC={(reference_after.z, reference_after.c)}",
            rtl_event="illegal",
            reference_after=reference_after,
            rtl_snapshot=rtl_snapshot,
        )
    if rtl_snapshot.iosel != reference_after.iosel:
        raise LockstepFailure(
            f"illegal IOSEL mismatch: rtl=0x{rtl_snapshot.iosel:02X} ref=0x{reference_after.iosel:02X}",
            rtl_event="illegal",
            reference_after=reference_after,
            rtl_snapshot=rtl_snapshot,
        )
    if rtl_snapshot.mem_write_en:
        raise LockstepFailure(
            "unexpected memory write on illegal instruction",
            rtl_event="illegal",
            reference_after=reference_after,
            rtl_snapshot=rtl_snapshot,
        )
    if rtl_snapshot.io_valid:
        raise LockstepFailure(
            "unexpected I/O transfer on illegal instruction",
            rtl_event="illegal",
            reference_after=reference_after,
            rtl_snapshot=rtl_snapshot,
        )


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


async def _ensure_clock_started(dut) -> None:
    clock_task = getattr(dut, "_min8_lockstep_clock_task", None)
    if clock_task is not None and not clock_task.done():
        return
    clock_task = cocotb.start_soon(Clock(dut.clk, CLOCK_PERIOD_NS, unit="ns").start())
    setattr(dut, "_min8_lockstep_clock_task", clock_task)
    await NextTimeStep()


def _resolve_failure_context(
    failure_context: dict[str, Any] | Callable[[], dict[str, Any]] | None,
) -> dict[str, Any] | None:
    if failure_context is None:
        return None
    if callable(failure_context):
        return failure_context()
    return failure_context


def _persist_failure_artifact(
    *,
    artifact_root: Path | None,
    case_name: str | None,
    image: bytes,
    trace: list[TraceEntry],
    io: LockstepIOHarness,
    exc: Exception,
    event_index: int | None,
    rtl_event: str | None,
    reference_before: CPUSnapshot | None,
    reference_after: CPUSnapshot | None,
    rtl_snapshot: RTLSnapshot | None,
    step_result: StepResult | None,
    failure_context: dict[str, Any] | Callable[[], dict[str, Any]] | None,
) -> Path | None:
    if artifact_root is None:
        return None

    extra_context = _resolve_failure_context(failure_context)
    case_label = case_name or "lockstep_failure"
    payload = {
        "error_type": type(exc).__name__,
        "error_message": str(exc),
        "event_index": event_index,
        "rtl_event": rtl_event,
        "step_result": _serialize_step_result(step_result),
        "reference_before": None if reference_before is None else asdict(reference_before),
        "reference_after": None if reference_after is None else asdict(reference_after),
        "rtl_snapshot": None if rtl_snapshot is None else asdict(rtl_snapshot),
        "io": io.snapshot(),
        "trace": [asdict(entry) for entry in trace],
        "context": extra_context,
    }
    return write_failure_artifact(artifact_root, case_name=case_label, image=image, payload=payload)


async def run_lockstep_image(
    dut,
    image: bytes,
    *,
    case_name: str | None = None,
    max_events: int = 64,
    setup_io=None,
    on_event=None,
    artifact_root: Path | None = None,
    failure_context: dict[str, Any] | Callable[[], dict[str, Any]] | None = None,
    cycle_state_key=None,
) -> LockstepResult:
    await _ensure_clock_started(dut)
    await NextTimeStep()

    io = LockstepIOHarness()
    if setup_io is not None:
        setup_io(io)

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
    trace: list[TraceEntry] = []
    event_index: int | None = None
    rtl_event: str | None = None
    reference_before: CPUSnapshot | None = None
    reference_after: CPUSnapshot | None = None
    rtl_snapshot: RTLSnapshot | None = None
    step_result: StepResult | None = None
    seen_cycle_states: dict[Any, int] = {}

    if cycle_state_key is not None:
        seen_cycle_states[cycle_state_key(cpu, io, -1)] = -1

    try:
        for event_index in range(max_events):
            rtl_event = await wait_for_event(dut, io)
            reference_before = _capture_cpu_snapshot(cpu)
            if rtl_event == "illegal":
                try:
                    cpu.step()
                except IllegalInstruction as exc:
                    reference_after = _capture_cpu_snapshot(cpu)
                    rtl_snapshot = _capture_rtl_snapshot(dut)
                    compare_illegal_against_reference(reference_after, rtl_snapshot, exc)
                    trace.append(_make_illegal_trace_entry(event_index, exc, rtl_snapshot))
                    io.assert_synced()
                    events.append(rtl_event)
                    return LockstepResult(
                        cpu=cpu,
                        io=io,
                        image=bytes(image),
                        events=tuple(events),
                        trace=tuple(trace),
                        outcome="illegal_match",
                        completed_events=len(events),
                        case_name=case_name,
                    )
                rtl_snapshot = _capture_rtl_snapshot(dut)
                raise LockstepFailure(
                    "RTL reported illegal instruction but reference did not",
                    rtl_event=rtl_event,
                    reference_before=reference_before,
                    rtl_snapshot=rtl_snapshot,
                )

            step_result = cpu.step()
            reference_after = _capture_cpu_snapshot(cpu)
            rtl_snapshot = _capture_rtl_snapshot(dut)
            compare_against_reference(reference_after, rtl_snapshot, step_result, rtl_event)
            trace.append(_make_trace_entry(event_index, rtl_event, step_result, rtl_snapshot))
            io.assert_synced()
            events.append(rtl_event)
            if on_event is not None:
                on_event(io, rtl_event, step_result, event_index)
            if rtl_event == "halted":
                return LockstepResult(
                    cpu=cpu,
                    io=io,
                    image=bytes(image),
                    events=tuple(events),
                    trace=tuple(trace),
                    outcome="halted_match",
                    completed_events=len(events),
                    case_name=case_name,
                )
            if cycle_state_key is not None:
                state_key = cycle_state_key(cpu, io, event_index)
                first_seen_event_index = seen_cycle_states.get(state_key)
                if first_seen_event_index is not None:
                    return LockstepResult(
                        cpu=cpu,
                        io=io,
                        image=bytes(image),
                        events=tuple(events),
                        trace=tuple(trace),
                        outcome="cycle_match",
                        completed_events=len(events),
                        case_name=case_name,
                        cycle_first_seen_event_index=first_seen_event_index,
                        cycle_repeat_event_index=event_index,
                    )
                seen_cycle_states[state_key] = event_index

        return LockstepResult(
            cpu=cpu,
            io=io,
            image=bytes(image),
            events=tuple(events),
            trace=tuple(trace),
            outcome="bounded_match",
            completed_events=len(events),
            case_name=case_name,
        )
    except Exception as exc:
        artifact_path = _persist_failure_artifact(
            artifact_root=artifact_root,
            case_name=case_name,
            image=bytes(image),
            trace=trace,
            io=io,
            exc=exc,
            event_index=event_index,
            rtl_event=rtl_event,
            reference_before=reference_before,
            reference_after=reference_after,
            rtl_snapshot=rtl_snapshot,
            step_result=step_result,
            failure_context=failure_context,
        )
        if artifact_path is None:
            raise
        raise AssertionError(f"{exc} (repro artifact: {artifact_path})") from exc


async def run_lockstep_program(
    dut,
    source: str,
    *,
    case_name: str | None = None,
    max_events: int = 64,
    setup_io=None,
    on_event=None,
    artifact_root: Path | None = None,
    failure_context: dict[str, Any] | Callable[[], dict[str, Any]] | None = None,
    cycle_state_key=None,
) -> LockstepResult:
    image = assemble_source(source).image
    return await run_lockstep_image(
        dut,
        image,
        case_name=case_name,
        max_events=max_events,
        setup_io=setup_io,
        on_event=on_event,
        artifact_root=artifact_root,
        failure_context=failure_context,
        cycle_state_key=cycle_state_key,
    )
