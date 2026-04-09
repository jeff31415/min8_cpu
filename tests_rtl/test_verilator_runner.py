from __future__ import annotations

import os
import shutil
import sys
import unittest
from concurrent.futures import ProcessPoolExecutor
from pathlib import Path

try:
    from cocotb_tools.check_results import get_results
    from cocotb_tools.runner import get_runner
except ModuleNotFoundError as exc:  # pragma: no cover - exercised only without RTL deps
    get_results = None
    get_runner = None
    IMPORT_ERROR = exc
else:
    IMPORT_ERROR = None


ROOT = Path(__file__).resolve().parents[1]
LOCAL_OSS_CAD_BIN = ROOT / "oss-cad-suite" / "bin"
BUILD_ROOT = ROOT / "build" / "rtl_smoke_verilator"
RANDOM_ARTIFACT_ENV = "MIN8_RTL_RANDOM_ARTIFACT_DIR"
RANDOM_CASES_ENV = "MIN8_RTL_RANDOM_CASES"
RANDOM_CASE_OFFSET_ENV = "MIN8_RTL_RANDOM_CASE_OFFSET"
RANDOM_JOBS_ENV = "MIN8_RTL_RANDOM_JOBS"
DEFAULT_RANDOM_CASES = 12
RTL_SOURCES = [
    ROOT / "rtl/min8_alu.v",
    ROOT / "rtl/min8_regfile.v",
    ROOT / "rtl/min8_bram_wrap.v",
    ROOT / "rtl/min8_mem_model.v",
    ROOT / "rtl/min8_sync_fifo.v",
    ROOT / "rtl/min8_io_filo.v",
    ROOT / "rtl/min8_io_ps2.v",
    ROOT / "rtl/min8_io_audio.v",
    ROOT / "rtl/min8_io_ws2812.v",
    ROOT / "rtl/min8_io_peripheral_chain.v",
    ROOT / "rtl/min8_core.v",
    ROOT / "rtl/min8_core_tb.v",
]


def _prepend_once(path_entry: str) -> None:
    current = os.environ.get("PATH", "")
    parts = current.split(os.pathsep) if current else []
    if path_entry not in parts:
        os.environ["PATH"] = (
            path_entry if not current else f"{path_entry}{os.pathsep}{current}"
        )


def _prepare_environment() -> None:
    if LOCAL_OSS_CAD_BIN.is_dir():
        _prepend_once(str(LOCAL_OSS_CAD_BIN))
    if shutil.which("verilator") is None:
        raise FileNotFoundError("verilator not found in PATH")
    for entry in (str(ROOT), str(ROOT / "tests_rtl")):
        if entry not in sys.path:
            sys.path.insert(0, entry)


def _total_random_cases() -> int:
    return max(1, int(os.environ.get(RANDOM_CASES_ENV, str(DEFAULT_RANDOM_CASES)), 0))


def _random_job_count(total_cases: int) -> int:
    configured = os.environ.get(RANDOM_JOBS_ENV)
    if configured is not None:
        return max(1, min(total_cases, int(configured, 0)))
    return max(1, min(total_cases, os.cpu_count() or 1, 4))


def _split_cases(total_cases: int, shard_count: int) -> list[tuple[int, int]]:
    shard_count = max(1, min(total_cases, shard_count))
    base = total_cases // shard_count
    remainder = total_cases % shard_count
    offset = 0
    shards: list[tuple[int, int]] = []
    for shard_index in range(shard_count):
        count = base + (1 if shard_index < remainder else 0)
        if count <= 0:
            continue
        shards.append((offset, count))
        offset += count
    return shards


def _run_random_shard(
    build_dir: Path,
    latch_opcode: int,
    shard_index: int,
    case_offset: int,
    case_count: int,
) -> tuple[int, int]:
    _prepare_environment()
    runner = get_runner("verilator")
    shard_dir = build_dir / "random_shards" / f"shard_{shard_index:02d}"
    shard_build_dir = shard_dir / "build"
    shard_test_dir = shard_dir / "test"
    shard_test_dir.mkdir(parents=True, exist_ok=True)
    runner.build(
        sources=RTL_SOURCES,
        hdl_toplevel="min8_core_tb",
        always=True,
        build_dir=str(shard_build_dir),
        build_args=[f"-GCORE_LATCH_OPCODE={latch_opcode}"],
        waves=False,
    )
    env_updates = {
        RANDOM_ARTIFACT_ENV: str(build_dir / "random_failures" / f"shard_{shard_index:02d}"),
        RANDOM_CASES_ENV: str(case_count),
        RANDOM_CASE_OFFSET_ENV: str(case_offset),
    }
    previous_env = {key: os.environ.get(key) for key in env_updates}
    os.environ.update(env_updates)
    try:
        results_xml = runner.test(
            hdl_toplevel="min8_core_tb",
            test_module=["test_rtl_random"],
            waves=False,
            build_dir=str(shard_build_dir),
            test_dir=str(shard_test_dir),
            results_xml=str(shard_test_dir / "results.xml"),
            extra_env=env_updates,
        )
    finally:
        for key, value in previous_env.items():
            if value is None:
                os.environ.pop(key, None)
            else:
                os.environ[key] = value
    return get_results(results_xml)


class VerilatorSmokeRunner(unittest.TestCase):
    def _run_suite(self, *, latch_opcode: int, build_dir: Path) -> None:
        if IMPORT_ERROR is not None:
            self.skipTest(f"cocotb is not installed: {IMPORT_ERROR}")
        try:
            _prepare_environment()
        except FileNotFoundError as exc:
            self.skipTest(str(exc))
        runner = get_runner("verilator")
        runner.build(
            sources=RTL_SOURCES,
            hdl_toplevel="min8_core_tb",
            always=True,
            build_dir=str(build_dir),
            build_args=[f"-GCORE_LATCH_OPCODE={latch_opcode}"],
            waves=False,
        )
        directed_dir = build_dir / "directed"
        directed_dir.mkdir(parents=True, exist_ok=True)
        directed_results_xml = runner.test(
            hdl_toplevel="min8_core_tb",
            test_module=["test_rtl_smoke", "test_rtl_peripherals", "test_rtl_lockstep"],
            waves=False,
            build_dir=str(build_dir),
            test_dir=str(directed_dir),
            results_xml=str(directed_dir / "results.xml"),
            extra_env={
                RANDOM_ARTIFACT_ENV: str(build_dir / "directed_failures"),
            },
        )
        num_tests, num_failed = get_results(directed_results_xml)
        total_random_cases = _total_random_cases()
        shard_specs = _split_cases(total_random_cases, _random_job_count(total_random_cases))

        with ProcessPoolExecutor(max_workers=len(shard_specs)) as executor:
            futures = [
                executor.submit(_run_random_shard, build_dir, latch_opcode, shard_index, case_offset, case_count)
                for shard_index, (case_offset, case_count) in enumerate(shard_specs)
            ]
            for future in futures:
                shard_tests, shard_failed = future.result()
                num_tests += shard_tests
                num_failed += shard_failed
        self.assertGreater(num_tests, 0)
        self.assertEqual(num_failed, 0, f"{num_failed} cocotb RTL tests failed")

    def test_verilator_rtl_suite_with_opcode_latch(self) -> None:
        self._run_suite(latch_opcode=1, build_dir=BUILD_ROOT / "with_latch")

    def test_verilator_rtl_suite_without_opcode_latch(self) -> None:
        self._run_suite(latch_opcode=0, build_dir=BUILD_ROOT / "without_latch")


if __name__ == "__main__":
    unittest.main()
