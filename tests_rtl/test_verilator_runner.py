from __future__ import annotations

import os
import shutil
import sys
import unittest
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
BUILD_DIR = ROOT / "build" / "rtl_smoke_verilator"
RTL_SOURCES = [
    ROOT / "rtl/min8_alu.v",
    ROOT / "rtl/min8_regfile.v",
    ROOT / "rtl/min8_mem_model.v",
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


class VerilatorSmokeRunner(unittest.TestCase):
    def test_verilator_rtl_suite(self) -> None:
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
            build_dir=str(BUILD_DIR),
            waves=False,
        )
        results_xml = runner.test(
            hdl_toplevel="min8_core_tb",
            test_module=["test_rtl_smoke", "test_rtl_lockstep"],
            waves=False,
            build_dir=str(BUILD_DIR),
            test_dir=str(BUILD_DIR),
        )
        num_tests, num_failed = get_results(results_xml)
        self.assertGreater(num_tests, 0)
        self.assertEqual(num_failed, 0, f"{num_failed} cocotb RTL tests failed")


if __name__ == "__main__":
    unittest.main()
