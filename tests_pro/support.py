"""Shared helpers for Min8-Pro tests."""

from __future__ import annotations

from pathlib import Path

from min8_pro.asm import AssemblyResult, assemble_source
from min8_pro.cpu import Min8ProCPU

PROGRAMS_DIR = Path(__file__).with_name("programs")


def fixture_source(name: str) -> str:
    return (PROGRAMS_DIR / name).read_text(encoding="utf-8")


def assemble_fixture(name: str) -> AssemblyResult:
    return assemble_source(fixture_source(name), source_name=name)


def run_fixture(name: str) -> tuple[AssemblyResult, Min8ProCPU]:
    result = assemble_fixture(name)
    cpu = Min8ProCPU()
    cpu.load_image(result.image)
    cpu.run()
    return result, cpu
