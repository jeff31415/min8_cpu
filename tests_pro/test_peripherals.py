"""Min8-Pro smoke tests for the shared peripheral backend."""

from __future__ import annotations

import unittest

from min8_pro.session import Min8ProSession


class Min8ProPeripheralTests(unittest.TestCase):
    def test_ps2_empty_read_returns_zero_without_blocking(self) -> None:
        session = Min8ProSession()
        session.load_peripheral_config(
            {
                "version": 1,
                "devices": [
                    {
                        "type": "ps2",
                        "name": "keyboard0",
                        "channel": 0x10,
                        "rx_depth": 4,
                        "tx_depth": 4,
                    }
                ],
            }
        )
        session.load_source(
            """
    SETIOI 0x10
    IN R3
    HALT
"""
        )

        results = session.run_batch(max_steps=10)

        self.assertEqual(results[-1].status, "halted")
        self.assertEqual([result.status for result in results[:-1]], ["retired"] * (len(results) - 1))
        self.assertEqual(session.cpu.state.registers[3], 0x00)


if __name__ == "__main__":
    unittest.main()
