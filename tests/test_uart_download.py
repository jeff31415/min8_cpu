from __future__ import annotations

import tempfile
import unittest
from pathlib import Path

from min8.uart_download import _load_image, _validate_downloadable


class UARTDownloadTests(unittest.TestCase):
    def test_load_asm_expands_to_full_image(self) -> None:
        image = _load_image(Path("examples/uart_echo.asm"))
        self.assertEqual(len(image), 256)

    def test_load_bin_pads_to_256_bytes(self) -> None:
        with tempfile.TemporaryDirectory() as tmpdir:
            path = Path(tmpdir) / "demo.bin"
            path.write_bytes(b"\x12\x34\x56")
            image = _load_image(path)

        self.assertEqual(len(image), 256)
        self.assertEqual(image[:4], b"\x12\x34\x56\x00")

    def test_validate_downloadable_rejects_trailer_bytes(self) -> None:
        image = bytearray(256)
        image[0xFC] = 0xAA
        with self.assertRaises(SystemExit):
            _validate_downloadable(bytes(image))


if __name__ == "__main__":
    unittest.main()
