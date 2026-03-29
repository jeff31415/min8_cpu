"""Send a Min8 image to the UART bootloader."""

from __future__ import annotations

import argparse
import os
import sys
import termios
from pathlib import Path

from .asm import assemble_file

BOOTLOAD_BYTES = 0xFC


def _load_image(path: Path) -> bytes:
    suffix = path.suffix.lower()
    if suffix == ".asm":
        return assemble_file(path).image
    if suffix == ".bin":
        data = path.read_bytes()
        if len(data) > 256:
            raise SystemExit(f"{path}: binary is {len(data)} bytes, expected at most 256")
        return data.ljust(256, b"\x00")
    if suffix in {".memh", ".hex"}:
        values: list[int] = []
        for line in path.read_text(encoding="utf-8").splitlines():
            stripped = line.split("//", 1)[0].split(";", 1)[0].strip()
            if not stripped:
                continue
            values.append(int(stripped, 16) & 0xFF)
        if len(values) > 256:
            raise SystemExit(f"{path}: memh contains {len(values)} bytes, expected at most 256")
        return bytes(values).ljust(256, b"\x00")
    raise SystemExit(f"{path}: unsupported input type, use .asm, .bin, or .memh")


def _validate_downloadable(image: bytes) -> bytes:
    trailer = image[BOOTLOAD_BYTES:]
    if any(trailer):
        raise SystemExit(
            "image uses addresses 0xFC..0xFF, but the UART bootloader only replaces 0x00..0xFB"
        )
    return image[:BOOTLOAD_BYTES]


def _open_serial(path: str, baud: int) -> int:
    fd = os.open(path, os.O_RDWR | os.O_NOCTTY | os.O_SYNC)
    attrs = termios.tcgetattr(fd)
    attrs[0] = 0
    attrs[1] = 0
    attrs[2] = termios.CS8 | termios.CREAD | termios.CLOCAL
    attrs[3] = 0
    attrs[6][termios.VMIN] = 0
    attrs[6][termios.VTIME] = 0

    baud_attr = getattr(termios, f"B{baud}", None)
    if baud_attr is None:
        os.close(fd)
        raise SystemExit(f"unsupported baud rate {baud}")
    attrs[4] = baud_attr
    attrs[5] = baud_attr
    termios.tcsetattr(fd, termios.TCSANOW, attrs)
    termios.tcflush(fd, termios.TCIOFLUSH)
    return fd


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="Send a Min8 image to the UART bootloader")
    parser.add_argument("source", help="input .asm, .bin, or .memh image")
    parser.add_argument("--port", required=True, help="serial device, for example /dev/ttyUSB0")
    parser.add_argument("--baud", type=int, default=115200, help="UART baud rate")
    args = parser.parse_args(argv)

    image = _load_image(Path(args.source))
    payload = _validate_downloadable(image)

    fd = _open_serial(args.port, args.baud)
    try:
        written = os.write(fd, payload)
        if written != len(payload):
            raise SystemExit(f"short write: sent {written} of {len(payload)} bytes")
        termios.tcdrain(fd)
    finally:
        os.close(fd)

    print(f"sent {len(payload)} bytes to {args.port} at {args.baud} baud")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
