"""High-level synchronous and asynchronous device wrappers.

``Device`` wraps a ``pyserial`` (or duck-typed) port and exposes the 20-command
API. ``AsyncDevice`` runs the same logic in a thread pool so it can be ``await``-ed
from asyncio code without a second serial implementation.
"""

from __future__ import annotations

import asyncio
import threading
import time
from typing import (
    AsyncIterator,
    Iterator,
    Optional,
    Sequence,
    Union,
)

from . import protocol as _p
from .errors import H1TimeoutError, ProtocolError
from .types import (
    CieMode,
    DeviceInfo,
    ExposureMode,
    SpectrumFrame,
    WavelengthRange,
    WorkingMode,
)

DEFAULT_BAUDRATE = 115200
DEFAULT_TIMEOUT_S = 1.0

# Allow stream() to share the chunked-read code path even though it never times
# out: 0 means "block forever until a frame arrives or stop is signalled".
_STREAM_FRAME_TIMEOUT_S = 0.0

# Type alias for "anything that quacks like serial.Serial".
SerialLike = object  # documented intent; we don't enforce at runtime


# ---------------------------------------------------------------------------
# Sync Device
# ---------------------------------------------------------------------------


class Device:
    """Synchronous H1 device wrapper.

    Construct with either a port path (``"/dev/tty.usbserial-...":``) or any
    object exposing ``write``, ``read``, ``close``, ``in_waiting``, ``timeout``.

    Thread-safety: every public method takes an internal lock so concurrent
    callers serialise their requests on the wire. Streaming is implemented as
    an iterator that owns the lock for the lifetime of the iteration.
    """

    def __init__(
        self,
        port: Union[str, "SerialLike"],
        baudrate: int = DEFAULT_BAUDRATE,
        timeout: float = DEFAULT_TIMEOUT_S,
    ) -> None:
        if isinstance(port, str):
            try:
                import serial  # pyserial
            except ImportError as exc:  # pragma: no cover - import-error path
                raise ImportError(
                    "pyserial is required to open a port by path; "
                    "install with `pip install pyserial`"
                ) from exc
            self._port = serial.Serial(port, baudrate=baudrate, timeout=timeout)
            self._owns_port = True
        else:
            self._port = port
            self._owns_port = False
            # Mirror requested timeout onto duck-typed ports if they accept it.
            try:
                self._port.timeout = timeout
            except (AttributeError, TypeError):
                pass

        self._default_timeout = timeout
        self._lock = threading.RLock()
        self._streaming = False
        self._reset_input_buffer()

    # ---- lifecycle --------------------------------------------------------

    def __enter__(self) -> "Device":
        return self

    def __exit__(self, *exc: object) -> None:
        self.close()

    def close(self) -> None:
        if self._owns_port:
            try:
                self._port.close()
            except Exception:  # noqa: BLE001 - best-effort close
                pass

    # ---- low-level wire helpers ------------------------------------------

    def _reset_input_buffer(self) -> None:
        reset = getattr(self._port, "reset_input_buffer", None)
        if not callable(reset):
            return
        try:
            reset()
        except Exception:  # noqa: BLE001 - best-effort serial hygiene
            pass

    def _write_frame(self, frame: bytes) -> None:
        self._port.write(frame)

    def _read_exact(self, n: int, timeout: float) -> bytes:
        """Read exactly ``n`` bytes within ``timeout`` seconds or raise."""
        deadline = time.monotonic() + timeout
        out = bytearray()
        while len(out) < n:
            remaining = deadline - time.monotonic()
            if remaining <= 0:
                raise H1TimeoutError(
                    f"timed out after {timeout:.3f}s waiting for {n} bytes "
                    f"(got {len(out)})"
                )
            # Honour the underlying port's timeout if it's lower so blocking
            # reads don't outlive our deadline.
            try:
                self._port.timeout = min(self._default_timeout, remaining)
            except (AttributeError, TypeError):
                pass
            chunk = self._port.read(n - len(out))
            if not chunk:
                continue
            out.extend(chunk)
        return bytes(out)

    def _read_response_header(self, timeout: float) -> bytes:
        """Read until the response header appears, discarding stale bytes."""
        deadline = time.monotonic() + timeout
        matched = bytearray()
        while True:
            remaining = deadline - time.monotonic()
            if remaining <= 0:
                raise H1TimeoutError(
                    f"timed out after {timeout:.3f}s waiting for response header "
                    f"{_p.HEADER_RESP.hex()}"
                )
            byte = self._read_exact(1, remaining)
            value = byte[0]
            if not matched:
                if value == _p.HEADER_RESP[0]:
                    matched.append(value)
                continue
            if value == _p.HEADER_RESP[1]:
                return bytes(matched) + byte
            if value == _p.HEADER_RESP[0]:
                matched[:] = byte
            else:
                matched.clear()

    def _read_frame(self, expected_cmd_type: int, timeout: float) -> bytes:
        """Read one full response frame for ``expected_cmd_type``."""
        deadline = time.monotonic() + timeout
        # Sync to header (2) then read totalLen (3) so we know frame length.
        header = self._read_response_header(timeout)
        remaining = max(deadline - time.monotonic(), 0.0)
        head = header + self._read_exact(3, remaining)
        total_len = int.from_bytes(head[2:5], "little")
        if total_len < _p.FRAME_OVERHEAD or total_len > 1_000_000:
            raise ProtocolError(f"implausible totalLen={total_len}")
        remaining = max(deadline - time.monotonic(), 0.0)
        rest = self._read_exact(total_len - 5, remaining)
        return head + rest

    def _request(
        self,
        frame: bytes,
        expected_cmd_type: int,
        timeout: Optional[float] = None,
    ) -> bytes:
        """Send ``frame``, wait for the matching response, return validData."""
        to = timeout if timeout is not None else self._default_timeout
        with self._lock:
            # Discard any residue before issuing a command. Under the lock the
            # input buffer should be empty here; anything present is stale — most
            # often a trailing stream frame the device emitted after a 0x04 stop
            # (PROTOCOL.md §8.2) — and would otherwise corrupt this response read.
            self._reset_input_buffer()
            self._write_frame(frame)
            deadline = time.monotonic() + to
            while True:
                remaining = deadline - time.monotonic()
                if remaining <= 0:
                    raise H1TimeoutError(
                        f"timed out after {to:.3f}s waiting for response "
                        f"0x{expected_cmd_type:02X}"
                    )
                raw = self._read_frame(expected_cmd_type, remaining)
                data_type, valid = _p.parse_frame(raw)
                if data_type == expected_cmd_type:
                    return valid

    # ---- device meta ------------------------------------------------------

    def get_device_info(self) -> DeviceInfo:
        valid = self._request(_p.cmd_get_device_info(), _p.Cmd.GET_DEVICE_INFO)
        return _p.decode_device_info(valid)

    def get_wavelength_range(self) -> WavelengthRange:
        valid = self._request(_p.cmd_get_wavelength_range(), _p.Cmd.GET_WAVELENGTH_RANGE)
        return _p.decode_wavelength_range(valid)

    # ---- exposure ---------------------------------------------------------

    def set_exposure_mode(self, mode: ExposureMode) -> None:
        valid = self._request(
            _p.cmd_set_exposure_mode(mode), _p.Cmd.SET_EXPOSURE_MODE
        )
        _p.expect_status(_p.Cmd.SET_EXPOSURE_MODE, valid)

    def get_exposure_mode(self) -> ExposureMode:
        valid = self._request(_p.cmd_get_exposure_mode(), _p.Cmd.GET_EXPOSURE_MODE)
        return _p.decode_exposure_mode(valid)

    def set_exposure_time_us(self, us: int) -> None:
        valid = self._request(
            _p.cmd_set_exposure_time(us), _p.Cmd.SET_EXPOSURE_TIME
        )
        _p.expect_status(_p.Cmd.SET_EXPOSURE_TIME, valid)

    def get_exposure_time_us(self) -> int:
        valid = self._request(_p.cmd_get_exposure_time(), _p.Cmd.GET_EXPOSURE_TIME)
        return _p.decode_u32(valid)

    def set_max_exposure_time_us(self, us: int) -> None:
        valid = self._request(
            _p.cmd_set_max_exposure_time(us), _p.Cmd.SET_MAX_EXPOSURE_TIME
        )
        _p.expect_status(_p.Cmd.SET_MAX_EXPOSURE_TIME, valid)

    def get_max_exposure_time_us(self) -> int:
        valid = self._request(
            _p.cmd_get_max_exposure_time(), _p.Cmd.GET_MAX_EXPOSURE_TIME
        )
        return _p.decode_u32(valid)

    # ---- modes ------------------------------------------------------------

    def set_cie_mode(self, mode: CieMode) -> None:
        valid = self._request(_p.cmd_set_cie_mode(mode), _p.Cmd.SET_CIE_MODE)
        _p.expect_status(_p.Cmd.SET_CIE_MODE, valid)

    def get_cie_mode(self) -> CieMode:
        valid = self._request(_p.cmd_get_cie_mode(), _p.Cmd.GET_CIE_MODE)
        return _p.decode_cie_mode(valid)

    def set_working_mode(self, mode: WorkingMode) -> None:
        valid = self._request(
            _p.cmd_set_working_mode(mode), _p.Cmd.SET_WORKING_MODE
        )
        _p.expect_status(_p.Cmd.SET_WORKING_MODE, valid)

    # ---- sleep ------------------------------------------------------------

    def enter_sleep(self) -> None:
        """Toggle sleep. Sends 0x40 once. No response per PROTOCOL.md §3.4."""
        with self._lock:
            self._write_frame(_p.cmd_enter_exit_sleep())

    def exit_sleep(self) -> None:
        """Same wire command as ``enter_sleep`` — the device toggles."""
        self.enter_sleep()

    # ---- capture ----------------------------------------------------------

    def capture_single(
        self,
        include_tm30: bool = False,
        timeout: Optional[float] = None,
    ) -> SpectrumFrame:
        cmd_code = (
            _p.Cmd.CAPTURE_SINGLE_WITH_TM30
            if include_tm30
            else _p.Cmd.CAPTURE_SINGLE_NO_TM30
        )
        # Capture can take a while if exposure_time is high — default to a
        # generous read timeout if the caller didn't specify one.
        to = timeout if timeout is not None else max(self._default_timeout, 5.0)
        valid = self._request(_p.cmd_capture_single(include_tm30), cmd_code, to)
        return _p.decode_spectrum_frame(valid, include_tm30=include_tm30)

    def stream(
        self,
        include_tm30: bool = False,
        max_frames: Optional[int] = None,
        frame_timeout: float = 10.0,
        stop_drain_s: float = 0.5,
    ) -> Iterator[SpectrumFrame]:
        """Yield ``SpectrumFrame`` objects until the consumer stops iterating.

        Sends CMD 0x33 / 0x35 to start the stream and CMD 0x04 to stop it. After
        the stop it drains trailing frames for up to ``stop_drain_s`` (PROTOCOL.md
        §8.2: the device may emit 1~2 more frames already in flight). Size this to
        roughly one exposure period so a slow-exposure trailing frame is consumed
        before the next command — otherwise it lands in the buffer and corrupts the
        next response read.
        """
        stream_code = (
            _p.Cmd.START_STREAM_WITH_TM30
            if include_tm30
            else _p.Cmd.START_STREAM_NO_TM30
        )
        return self._stream_iterator(
            include_tm30=include_tm30,
            stream_cmd=stream_code,
            max_frames=max_frames,
            frame_timeout=frame_timeout,
            stop_drain_s=stop_drain_s,
        )

    def _stream_iterator(
        self,
        include_tm30: bool,
        stream_cmd: int,
        max_frames: Optional[int],
        frame_timeout: float,
        stop_drain_s: float = 0.5,
    ) -> Iterator[SpectrumFrame]:
        # Acquire the lock for the whole stream so no other command interleaves.
        self._lock.acquire()
        self._streaming = True
        sent_stop = False
        emitted = 0
        last_exposure_us: Optional[int] = None
        try:
            self._write_frame(_p.cmd_start_stream(include_tm30))
            while True:
                if max_frames is not None and emitted >= max_frames:
                    break
                try:
                    raw = self._read_frame(stream_cmd, frame_timeout)
                except H1TimeoutError:
                    if sent_stop:
                        # Buffer drained — clean exit.
                        break
                    raise
                _, valid = _p.parse_frame(raw, expected_cmd_type=stream_cmd)
                frame = _p.decode_spectrum_frame(valid, include_tm30=include_tm30)
                last_exposure_us = frame.exposure_time_us
                emitted += 1
                yield frame
        finally:
            try:
                if not sent_stop:
                    self._write_frame(_p.cmd_stop_capture())
                    sent_stop = True
                    # Drain in-flight frames the device emits after 0x04
                    # (PROTOCOL.md §8.2). A trailing frame only starts arriving
                    # ~one *current* exposure period after the stop, so the window
                    # needs to cover one exposure — but the caller sizes
                    # ``stop_drain_s`` to the worst-case exposure *cap* (which can be
                    # seconds) because it can't know the auto-converged exposure up
                    # front. We DO know it here (the last frame's exposure), so drain
                    # for that instead, clamped to never exceed the caller's window.
                    # This keeps a long-exposure stream safe while making the common
                    # short-exposure case hand the device back in well under a second.
                    drain_window = max(stop_drain_s, 0.0)
                    if last_exposure_us is not None:
                        drain_window = min(
                            drain_window, (last_exposure_us / 1_000_000.0) + 0.4
                        )
                    drain_deadline = time.monotonic() + drain_window
                    while time.monotonic() < drain_deadline:
                        try:
                            in_waiting = getattr(self._port, "in_waiting", 0) or 0
                        except Exception:  # noqa: BLE001 - best-effort drain
                            in_waiting = 0
                        if in_waiting > 0:
                            try:
                                self._port.read(in_waiting)
                            except Exception:  # noqa: BLE001
                                break
                            continue
                        time.sleep(0.02)
                # Discard anything that arrived during the drain window so the
                # next command isn't fed a trailing stream frame.
                self._reset_input_buffer()
            except Exception:  # noqa: BLE001 - best-effort stop
                pass
            self._streaming = False
            self._lock.release()

    # ---- efficiency curve -------------------------------------------------

    def upload_efficiency_curve(self, ratios: Sequence[float]) -> None:
        """Upload a new ratio array.

        Implements the multi-packet protocol described in PROTOCOL.md §3.16:
        send a "start" packet (cmdData = 0x04), then split ``ratios`` into
        chunks of up to 247 floats and send each as cmdType 0x23, then call
        :meth:`verify_and_compute_efficiency_curve` to commit.
        """
        if len(ratios) == 0:
            raise ValueError("ratios must contain at least one value")
        with self._lock:
            self._write_frame(_p.cmd_send_efficiency_curve_start())
            chunk_size = _p.EFFICIENCY_CURVE_MAX_FLOATS_PER_PACKET
            for i in range(0, len(ratios), chunk_size):
                chunk = list(ratios[i : i + chunk_size])
                self._write_frame(_p.cmd_send_efficiency_curve_chunk(chunk))

    def verify_and_compute_efficiency_curve(
        self, timeout: float = 10.0
    ) -> None:
        valid = self._request(
            _p.cmd_verify_efficiency_curve(),
            _p.Cmd.VERIFY_EFFICIENCY_CURVE,
            timeout=timeout,
        )
        _p.expect_status(_p.Cmd.VERIFY_EFFICIENCY_CURVE, valid)

    def reset_efficiency_curve(self) -> None:
        valid = self._request(
            _p.cmd_reset_efficiency_curve(), _p.Cmd.RESET_EFFICIENCY_CURVE
        )
        _p.expect_status(_p.Cmd.RESET_EFFICIENCY_CURVE, valid)


# ---------------------------------------------------------------------------
# Async wrapper
# ---------------------------------------------------------------------------


class AsyncDevice:
    """Asyncio-friendly wrapper around :class:`Device`.

    Every method is the awaitable counterpart of the sync method with the same
    name. Internally we offload blocking calls to a thread (via
    ``loop.run_in_executor``) so we don't need a second serial implementation.
    """

    def __init__(
        self,
        port: Union[str, "SerialLike"],
        baudrate: int = DEFAULT_BAUDRATE,
        timeout: float = DEFAULT_TIMEOUT_S,
    ) -> None:
        self._sync = Device(port, baudrate=baudrate, timeout=timeout)

    async def __aenter__(self) -> "AsyncDevice":
        return self

    async def __aexit__(self, *exc: object) -> None:
        await self.close()

    async def close(self) -> None:
        await asyncio.get_event_loop().run_in_executor(None, self._sync.close)

    # ---- internal helper --------------------------------------------------

    async def _call(self, fn, /, *args, **kwargs):
        loop = asyncio.get_event_loop()
        return await loop.run_in_executor(None, lambda: fn(*args, **kwargs))

    # ---- one-shot methods -------------------------------------------------

    async def get_device_info(self) -> DeviceInfo:
        return await self._call(self._sync.get_device_info)

    async def get_wavelength_range(self) -> WavelengthRange:
        return await self._call(self._sync.get_wavelength_range)

    async def set_exposure_mode(self, mode: ExposureMode) -> None:
        await self._call(self._sync.set_exposure_mode, mode)

    async def get_exposure_mode(self) -> ExposureMode:
        return await self._call(self._sync.get_exposure_mode)

    async def set_exposure_time_us(self, us: int) -> None:
        await self._call(self._sync.set_exposure_time_us, us)

    async def get_exposure_time_us(self) -> int:
        return await self._call(self._sync.get_exposure_time_us)

    async def set_max_exposure_time_us(self, us: int) -> None:
        await self._call(self._sync.set_max_exposure_time_us, us)

    async def get_max_exposure_time_us(self) -> int:
        return await self._call(self._sync.get_max_exposure_time_us)

    async def set_cie_mode(self, mode: CieMode) -> None:
        await self._call(self._sync.set_cie_mode, mode)

    async def get_cie_mode(self) -> CieMode:
        return await self._call(self._sync.get_cie_mode)

    async def set_working_mode(self, mode: WorkingMode) -> None:
        await self._call(self._sync.set_working_mode, mode)

    async def enter_sleep(self) -> None:
        await self._call(self._sync.enter_sleep)

    async def exit_sleep(self) -> None:
        await self._call(self._sync.exit_sleep)

    async def capture_single(
        self,
        include_tm30: bool = False,
        timeout: Optional[float] = None,
    ) -> SpectrumFrame:
        return await self._call(self._sync.capture_single, include_tm30, timeout)

    async def upload_efficiency_curve(self, ratios: Sequence[float]) -> None:
        await self._call(self._sync.upload_efficiency_curve, ratios)

    async def verify_and_compute_efficiency_curve(
        self, timeout: float = 10.0
    ) -> None:
        await self._call(self._sync.verify_and_compute_efficiency_curve, timeout)

    async def reset_efficiency_curve(self) -> None:
        await self._call(self._sync.reset_efficiency_curve)

    # ---- streaming --------------------------------------------------------

    async def stream(
        self,
        include_tm30: bool = False,
        max_frames: Optional[int] = None,
        frame_timeout: float = 10.0,
        stop_drain_s: float = 0.5,
    ) -> AsyncIterator[SpectrumFrame]:
        """Async generator that mirrors :meth:`Device.stream`.

        Each iteration off-loads one ``next()`` call to the executor so other
        coroutines keep running during the long serial reads.
        """
        loop = asyncio.get_event_loop()
        sync_iter = self._sync.stream(
            include_tm30=include_tm30,
            max_frames=max_frames,
            frame_timeout=frame_timeout,
            stop_drain_s=stop_drain_s,
        )
        sentinel = object()

        def _next():
            try:
                return next(sync_iter)
            except StopIteration:
                return sentinel

        try:
            while True:
                item = await loop.run_in_executor(None, _next)
                if item is sentinel:
                    break
                yield item  # type: ignore[misc]
        finally:
            # Closing the generator triggers its finally-block which sends 0x04.
            await loop.run_in_executor(None, sync_iter.close)
