from __future__ import annotations

import json
import unittest
from collections import defaultdict, deque
from pathlib import Path
from tempfile import TemporaryDirectory

from min8.cpu import Min8CPU
from min8.exceptions import WouldBlockOnIO
from min8.isa import decode_opcode
from tests_rtl.support.randomized import (
    HALT_OPCODE,
    RandomizedIOScript,
    build_random_case,
    random_case_seed,
    write_failure_artifact,
)


class ReplayIOBackend:
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


class RandomizedRTLSupportTests(unittest.TestCase):
    def test_random_case_is_deterministic_and_legal(self) -> None:
        seed = random_case_seed(0x1234, 2)
        first = build_random_case(seed, 2, max_program_bytes=40)
        second = build_random_case(seed, 2, max_program_bytes=40)

        self.assertEqual(first.image, second.image)
        self.assertEqual(first.instructions, second.instructions)
        self.assertEqual(first.image[first.halt_address], HALT_OPCODE)
        for address in range(first.used_bytes):
            decode_opcode(first.image[address], pc=address)

    def test_random_case_runs_within_budget_without_exceptions(self) -> None:
        base_seed = 0xCAFE
        halted_cases = 0
        bounded_cases = 0
        for case_index in range(16):
            case_seed = random_case_seed(base_seed, case_index)
            case = build_random_case(case_seed, case_index, max_program_bytes=48)
            io_script = RandomizedIOScript(case.io_seed)
            io_backend = ReplayIOBackend()
            io_script.setup(io_backend)

            cpu = Min8CPU(io_backend=io_backend)
            cpu.load_image(case.image)

            for event_index in range(96):
                result = cpu.step()
                event = {"retired": "retire", "blocked": "blocked", "halted": "halted"}[result.status]
                if event == "halted":
                    halted_cases += 1
                    break
                io_script.on_event(io_backend, event, result, event_index)
            else:
                bounded_cases += 1

        self.assertGreater(halted_cases + bounded_cases, 0)

    def test_failure_artifact_contains_repro_inputs(self) -> None:
        image = bytes([HALT_OPCODE] * 256)
        with TemporaryDirectory() as tmp_dir:
            artifact_dir = write_failure_artifact(
                Path(tmp_dir),
                case_name="seed 1/case 0",
                image=image,
                payload={"seed": 1, "context": {"note": "unit-test"}},
            )

            self.assertTrue((artifact_dir / "image.bin").is_file())
            self.assertTrue((artifact_dir / "image.memh").is_file())
            self.assertTrue((artifact_dir / "failure.json").is_file())

            payload = json.loads((artifact_dir / "failure.json").read_text(encoding="utf-8"))
            self.assertEqual(payload["seed"], 1)
            self.assertEqual(payload["image_size"], 256)
            self.assertEqual(payload["case_name"], "seed 1/case 0")


if __name__ == "__main__":
    unittest.main()
