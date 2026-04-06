"""Tests for the shared Min8 peripheral I/O library."""

from __future__ import annotations

import unittest

from min8.io import PeripheralHub
from min8.session import Min8Session
from min8_shared.peripherals import AudioOutputDevice, FILOStackDevice, PS2KeyboardDevice, WS2812Device


class PeripheralTests(unittest.TestCase):
    def test_ps2_empty_read_returns_zero_without_blocking_cpu(self) -> None:
        session = Min8Session()
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

    def test_ps2_overflow_drops_new_bytes(self) -> None:
        device = PS2KeyboardDevice(channel=0x10, rx_depth=2, tx_depth=2)

        device.inject_rx(0x1C, 0xF0, 0x1C)

        self.assertEqual(device.read(), 0x1C)
        self.assertEqual(device.read(), 0xF0)
        self.assertEqual(device.dropped_input_count, 1)

    def test_audio_tick_consumes_samples_and_tracks_underflow(self) -> None:
        device = AudioOutputDevice(channel=0x11, tx_depth=4)
        device.write(0x7F)
        device.write(0x81)

        device.tick(2 / 16_000)
        after_buffered = device.snapshot()
        device.tick(1 / 16_000)
        after_underflow = device.snapshot()

        self.assertEqual(after_buffered["recent_samples"], [0x7F, 0x81])
        self.assertEqual(after_buffered["tx_depth"], 0)
        self.assertEqual(after_buffered["underflow_count"], 0)
        self.assertEqual(after_underflow["recent_samples"], [0x7F, 0x81, 0x80])
        self.assertEqual(after_underflow["underflow_count"], 1)

    def test_audio_can_consume_one_sample_per_observed_output(self) -> None:
        device = AudioOutputDevice(channel=0x11, tx_depth=4)
        device.write(0x90)
        device.write(0xA0)

        device.consume_samples(1)
        snapshot = device.snapshot()

        self.assertEqual(snapshot["pending_samples"], [0xA0])
        self.assertEqual(snapshot["recent_samples"], [0x90])
        self.assertEqual(snapshot["samples_played"], 1)

    def test_audio_config_accepts_custom_sample_rate(self) -> None:
        hub = PeripheralHub()
        hub.load_config(
            {
                "version": 1,
                "devices": [
                    {
                        "type": "audio8",
                        "name": "audio0",
                        "channel": 0x11,
                        "tx_depth": 64,
                        "sample_rate_hz": 22050,
                    }
                ],
            }
        )

        device = hub.get_device(0x11)

        self.assertIsNotNone(device)
        self.assertEqual(device.snapshot()["sample_rate_hz"], 22050)
        self.assertEqual(hub.dump_config_dict()["devices"][0]["sample_rate_hz"], 22050)

    def test_audio_output_tap_captures_consumed_samples_when_enabled(self) -> None:
        device = AudioOutputDevice(channel=0x11, tx_depth=4)
        device.write(0x44)
        device.write(0x55)

        device.consume_samples(1)
        self.assertEqual(device.drain_output_tap(), b"")

        device.set_output_tap_enabled(True)
        device.consume_samples(2)

        self.assertEqual(device.drain_output_tap(), bytes([0x55, 0x80]))
        self.assertEqual(device.drain_output_tap(), b"")

    def test_ws2812_commits_full_frame_in_grb_order(self) -> None:
        device = WS2812Device(channel=0x12, width=2, height=1, tx_depth=8)
        for value in (10, 20, 30, 40, 50, 60):
            device.write(value)

        device.tick(6 / 100_000)
        snapshot = device.snapshot()

        self.assertEqual(snapshot["frame_count"], 1)
        self.assertEqual(snapshot["pixels"], ((20, 10, 30), (50, 40, 60)))

    def test_ws2812_can_consume_one_byte_per_observed_output(self) -> None:
        device = WS2812Device(channel=0x12, width=1, height=1, tx_depth=8)
        for value in (10, 20, 30):
            device.write(value)

        device.consume_bytes(1)
        after_first = device.snapshot()
        device.consume_bytes(2)
        after_frame = device.snapshot()

        self.assertEqual(after_first["tx_depth"], 2)
        self.assertEqual(after_first["staging_bytes"], 1)
        self.assertEqual(after_frame["frame_count"], 1)
        self.assertEqual(after_frame["pixels"], ((20, 10, 30),))

    def test_filo_device_reads_back_last_written_byte_first(self) -> None:
        device = FILOStackDevice(channel=0x13, depth=4)
        device.write(0x11)
        device.write(0x22)
        device.write(0x33)

        self.assertEqual(device.read(), 0x33)
        self.assertEqual(device.read(), 0x22)
        self.assertEqual(device.read(), 0x11)

    def test_config_roundtrip_restores_devices(self) -> None:
        hub = PeripheralHub()
        hub.load_config(
            {
                "version": 1,
                "devices": [
                    {
                        "type": "ps2",
                        "name": "keyboard0",
                        "channel": 0x10,
                        "rx_depth": 8,
                        "tx_depth": 4,
                    },
                    {
                        "type": "audio8",
                        "name": "audio0",
                        "channel": 0x11,
                        "tx_depth": 64,
                        "sample_rate_hz": 22050,
                    },
                    {
                        "type": "ws2812",
                        "name": "leds0",
                        "channel": 0x12,
                        "tx_depth": 48,
                        "width": 4,
                        "height": 4,
                        "color_order": "GRB",
                        "serpentine": True,
                    },
                    {
                        "type": "filo",
                        "name": "stack0",
                        "channel": 0x13,
                        "depth": 16,
                    },
                ],
            }
        )

        dumped = hub.dump_config_dict()
        restored = PeripheralHub()
        restored.load_config(dumped)

        self.assertEqual(dumped["version"], 1)
        self.assertEqual([device.name for device in restored.devices()], ["keyboard0", "audio0", "leds0", "stack0"])
        self.assertEqual(dumped, restored.dump_config_dict())


if __name__ == "__main__":
    unittest.main()
