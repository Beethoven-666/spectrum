"""In-memory ``MockSerialPort`` for tests and offline development.

The interface mirrors the subset of ``serial.Serial`` that ``Device`` actually
uses (``write``, ``read``, ``close``, ``in_waiting``, ``timeout``), so tests
can construct ``Device(MockSerialPort(...))`` without touching real hardware.

Scenarios are scripted by:

* Pre-queueing canned responses with ``queue_response(bytes_)`` — the next
  ``write(...)`` will trigger those bytes to be made available on the read
  side; or
* Registering a handler with ``on_command(cmd_type, lambda data: response)``.

This is intentionally minimal: it is a test double, not a full serial sim.
"""

from __future__ import annotations

import threading
import time
from collections import deque
from typing import Callable, Deque, Dict, Optional


class MockSerialPort:
    """A duck-typed stand-in for ``serial.Serial`` that the SDK can drive."""

    def __init__(self, *, timeout: Optional[float] = 1.0) -> None:
        self.timeout = timeout
        self._read_buffer = bytearray()
        self._write_log: Deque[bytes] = deque()
        self._handlers: Dict[int, Callable[[bytes], Optional[bytes]]] = {}
        self._queued_responses: Deque[bytes] = deque()
        self._closed = False
        self._lock = threading.Lock()
        self._cond = threading.Condition(self._lock)

    # ---- writing -----------------------------------------------------------

    def write(self, data: bytes) -> int:
        if self._closed:
            raise IOError("port is closed")
        with self._cond:
            buf = bytes(data)
            self._write_log.append(buf)
            self._process_command(buf)
            self._cond.notify_all()
            return len(buf)

    def _process_command(self, frame: bytes) -> None:
        # Try handler-based dispatch first; fall back to queued bytes.
        try:
            from .protocol import HEADER_CMD, parse_frame  # local import to avoid cycle

            if frame[:2] != HEADER_CMD:
                # Not a command frame; nothing to dispatch.
                pass
            else:
                cmd_type = frame[5]
                handler = self._handlers.get(cmd_type)
                if handler is not None:
                    valid_data = frame[6:-3]
                    resp = handler(bytes(valid_data))
                    if resp is not None:
                        self._read_buffer.extend(resp)
                    return
        except Exception:
            # Ignore parse errors during dispatch — tests may inject malformed
            # frames on purpose. Fall through to queued responses.
            pass

        if self._queued_responses:
            self._read_buffer.extend(self._queued_responses.popleft())

    # ---- reading -----------------------------------------------------------

    def read(self, size: int = 1) -> bytes:
        if self._closed:
            raise IOError("port is closed")
        deadline = None if self.timeout is None else time.monotonic() + self.timeout
        with self._cond:
            while len(self._read_buffer) < size:
                remaining = None if deadline is None else deadline - time.monotonic()
                if remaining is not None and remaining <= 0:
                    break
                self._cond.wait(timeout=remaining)
                if self._closed:
                    return b""
            chunk = bytes(self._read_buffer[:size])
            del self._read_buffer[:size]
            return chunk

    @property
    def in_waiting(self) -> int:
        with self._lock:
            return len(self._read_buffer)

    # ---- lifecycle ---------------------------------------------------------

    def close(self) -> None:
        with self._cond:
            self._closed = True
            self._cond.notify_all()

    @property
    def is_open(self) -> bool:
        return not self._closed

    # ---- test-helper API ---------------------------------------------------

    def queue_response(self, data: bytes) -> None:
        """Make ``data`` the response to the next ``write(...)``."""
        with self._cond:
            self._queued_responses.append(bytes(data))

    def push_bytes(self, data: bytes) -> None:
        """Push raw bytes onto the read buffer immediately (no write needed)."""
        with self._cond:
            self._read_buffer.extend(data)
            self._cond.notify_all()

    def on_command(
        self, cmd_type: int, handler: Callable[[bytes], Optional[bytes]]
    ) -> None:
        """Register a callback that produces a response for one command code.

        The callback receives the raw ``validData`` bytes of the command and
        returns the response frame (full bytes, header through footer) or
        ``None`` for "no response" (e.g. CMD 0x04 stop-capture).
        """
        self._handlers[cmd_type] = handler

    @property
    def writes(self) -> Deque[bytes]:
        """All frames written by the SDK, in order. Useful for assertions."""
        return self._write_log
