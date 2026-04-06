"""Optional host audio playback helpers for the Min8 GUI."""

from __future__ import annotations

import queue
import shutil
import subprocess
import threading


class _AplayStream:
    def __init__(self, *, aplay_path: str, sample_rate_hz: int) -> None:
        self.aplay_path = aplay_path
        self.sample_rate_hz = int(sample_rate_hz)
        self._queue: queue.Queue[bytes | None] = queue.Queue(maxsize=64)
        self._thread = threading.Thread(target=self._run, name=f"min8-aplay-{self.sample_rate_hz}", daemon=True)
        self._stop_requested = threading.Event()
        self._error: str | None = None
        self._dropped_chunks = 0
        self._thread.start()

    @property
    def error(self) -> str | None:
        return self._error

    @property
    def dropped_chunks(self) -> int:
        return self._dropped_chunks

    def enqueue(self, data: bytes) -> None:
        if not data or self._stop_requested.is_set() or self._error is not None:
            return
        try:
            self._queue.put_nowait(data)
        except queue.Full:
            self._dropped_chunks += 1

    def close(self) -> None:
        self._stop_requested.set()
        try:
            self._queue.put_nowait(None)
        except queue.Full:
            pass
        self._thread.join(timeout=1.0)

    def _run(self) -> None:
        process: subprocess.Popen[bytes] | None = None
        try:
            process = subprocess.Popen(
                [
                    self.aplay_path,
                    "-q",
                    "-t",
                    "raw",
                    "-f",
                    "U8",
                    "-r",
                    str(self.sample_rate_hz),
                    "-c",
                    "1",
                ],
                stdin=subprocess.PIPE,
                stdout=subprocess.DEVNULL,
                stderr=subprocess.DEVNULL,
                bufsize=0,
            )
            if process.stdin is None:
                self._error = "aplay stdin pipe was not created"
                return

            while not self._stop_requested.is_set():
                try:
                    chunk = self._queue.get(timeout=0.050)
                except queue.Empty:
                    continue
                if chunk is None:
                    break
                if process.poll() is not None:
                    self._error = f"aplay exited with code {process.returncode}"
                    break
                process.stdin.write(chunk)
        except OSError as exc:
            self._error = str(exc)
        finally:
            if process is not None:
                try:
                    if process.stdin is not None:
                        process.stdin.close()
                except OSError:
                    pass
                try:
                    process.wait(timeout=0.250)
                except subprocess.TimeoutExpired:
                    process.kill()
                    process.wait(timeout=0.250)


class HostAudioPlaybackManager:
    """Small runtime manager for optional host-side audio playback."""

    def __init__(self) -> None:
        self._aplay_path = shutil.which("aplay")
        self._streams: dict[int, _AplayStream] = {}

    @property
    def backend_name(self) -> str | None:
        return "aplay" if self._aplay_path is not None else None

    def ensure_stream(self, channel: int, sample_rate_hz: int) -> bool:
        if self._aplay_path is None:
            return False
        current = self._streams.get(channel)
        if current is not None and current.sample_rate_hz == sample_rate_hz and current.error is None:
            return True
        if current is not None:
            current.close()
        self._streams[channel] = _AplayStream(aplay_path=self._aplay_path, sample_rate_hz=sample_rate_hz)
        return self._streams[channel].error is None

    def disable_stream(self, channel: int) -> None:
        stream = self._streams.pop(channel, None)
        if stream is not None:
            stream.close()

    def push_samples(self, channel: int, sample_rate_hz: int, data: bytes) -> bool:
        if not data:
            return True
        if not self.ensure_stream(channel, sample_rate_hz):
            return False
        stream = self._streams.get(channel)
        if stream is None:
            return False
        stream.enqueue(data)
        return stream.error is None

    def describe(self, channel: int) -> str:
        if self._aplay_path is None:
            return "unavailable (missing aplay)"
        stream = self._streams.get(channel)
        if stream is None:
            return "off"
        if stream.error is not None:
            return f"error: {stream.error}"
        dropped = stream.dropped_chunks
        dropped_text = f", dropped={dropped}" if dropped else ""
        return f"aplay {stream.sample_rate_hz} Hz{dropped_text}"

    def close(self) -> None:
        for channel in list(self._streams):
            self.disable_stream(channel)
