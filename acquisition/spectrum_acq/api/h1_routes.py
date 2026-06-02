"""H1 debug/control REST routes for the acquisition service."""

from __future__ import annotations

import asyncio
import json
import queue
import threading
from typing import Any, Iterator

from fastapi import FastAPI, HTTPException, Query
from fastapi.responses import StreamingResponse

from spectrum_acq.capture.coordinator import CaptureCoordinator
from spectrum_acq.models import json_dumps, to_jsonable


def register_h1_routes(app: FastAPI, coordinator: CaptureCoordinator) -> None:
    @app.get("/h1/info")
    def h1_info() -> dict[str, Any]:
        return _run_h1(coordinator, coordinator.h1_device_info)

    @app.get("/h1/exposure")
    def h1_get_exposure() -> dict[str, Any]:
        return _run_h1(coordinator, coordinator.h1_get_exposure)

    @app.patch("/h1/exposure")
    async def h1_patch_exposure(body: dict[str, Any]) -> dict[str, Any]:
        mode = body.get("mode")
        if mode is not None and mode not in {"auto", "manual"}:
            raise HTTPException(status_code=400, detail='mode must be "auto" or "manual"')
        time_us = body.get("timeUs")
        if time_us is not None and (not isinstance(time_us, int) or time_us < 0):
            raise HTTPException(status_code=400, detail="timeUs must be a non-negative integer (us)")
        max_time_us = body.get("maxTimeUs")
        if max_time_us is not None and (not isinstance(max_time_us, int) or max_time_us < 0):
            raise HTTPException(status_code=400, detail="maxTimeUs must be a non-negative integer (us)")
        return _run_h1(
            coordinator,
            lambda: coordinator.h1_patch_exposure(
                mode=mode,
                time_us=time_us,
                max_time_us=max_time_us,
            ),
        )

    @app.get("/h1/cie-mode")
    def h1_get_cie_mode() -> dict[str, str]:
        return _run_h1(coordinator, coordinator.h1_get_cie_mode)

    @app.put("/h1/cie-mode")
    async def h1_put_cie_mode(body: dict[str, Any]) -> dict[str, str]:
        mode = body.get("mode")
        if not isinstance(mode, str):
            raise HTTPException(status_code=400, detail="mode is required")
        try:
            return _run_h1(coordinator, lambda: coordinator.h1_set_cie_mode(mode))
        except ValueError as exc:
            raise HTTPException(status_code=400, detail=str(exc)) from exc

    @app.put("/h1/working-mode")
    async def h1_put_working_mode(body: dict[str, Any]) -> dict[str, str]:
        mode = body.get("mode")
        if mode not in {"streaming", "trigger"}:
            raise HTTPException(status_code=400, detail='mode must be "streaming" or "trigger"')
        return _run_h1(coordinator, lambda: coordinator.h1_set_working_mode(str(mode)))

    @app.post("/h1/sleep")
    def h1_sleep() -> dict[str, Any]:
        return _run_h1(coordinator, coordinator.h1_enter_sleep)

    @app.post("/h1/wake")
    def h1_wake() -> dict[str, Any]:
        return _run_h1(coordinator, coordinator.h1_exit_sleep)

    @app.post("/h1/capture")
    def h1_capture(tm30: bool = Query(default=False)) -> dict[str, Any]:
        return to_jsonable(_run_h1(coordinator, lambda: coordinator.h1_capture_single(include_tm30=tm30)))

    @app.post("/h1/efficiency-curve")
    async def h1_upload_efficiency_curve(body: dict[str, Any]) -> dict[str, Any]:
        ratios = body.get("ratios")
        if not isinstance(ratios, list) or len(ratios) == 0:
            raise HTTPException(status_code=400, detail="ratios must be a non-empty array of numbers")
        floats: list[float] = []
        for value in ratios:
            if not isinstance(value, (int, float)):
                raise HTTPException(status_code=400, detail="ratios must contain only finite numbers")
            numeric = float(value)
            if numeric != numeric or numeric in {float("inf"), float("-inf")}:
                raise HTTPException(status_code=400, detail="ratios must contain only finite numbers")
            floats.append(numeric)
        return _run_h1(coordinator, lambda: coordinator.h1_upload_efficiency_curve(floats))

    @app.post("/h1/efficiency-curve/verify")
    def h1_verify_efficiency_curve() -> dict[str, Any]:
        return _run_h1(coordinator, coordinator.h1_verify_efficiency_curve)

    @app.post("/h1/efficiency-curve/reset")
    def h1_reset_efficiency_curve() -> dict[str, Any]:
        return _run_h1(coordinator, coordinator.h1_reset_efficiency_curve)

    @app.get("/h1/stream")
    async def h1_stream(
        tm30: bool = Query(default=False),
        max_frames: int | None = Query(default=None, ge=1, le=1000),
    ) -> StreamingResponse:
        # The H1 SDK stream generator holds the device lock (a threading.RLock)
        # across the whole stream and releases it in its ``finally``. An RLock may
        # only be released by the thread that acquired it. Starlette drives a *sync*
        # generator across rotating threadpool threads, so the acquire and the
        # teardown release would land on different threads -> "cannot release
        # un-acquired lock", leaving the device lock wedged (every later call 409s
        # and the next stream's auto-exposure prime blocks forever).
        #
        # Fix: run the blocking device stream on ONE dedicated worker thread, so
        # acquire + release + gen.close() all happen on the same thread, and bridge
        # frames to the async SSE response through a queue. On client disconnect the
        # async generator's ``finally`` sets the stop flag; the worker then closes
        # the generator on its own thread, sending CMD 0x04 and releasing the lock
        # cleanly (PROTOCOL.md §8.2/§8.4).
        events = _bridge_sync_stream(
            lambda: coordinator.stream_h1(include_tm30=tm30, max_frames=max_frames)
        )
        return StreamingResponse(
            events,
            media_type="text/event-stream",
            headers={
                "Cache-Control": "no-cache, no-transform",
                "Connection": "keep-alive",
                "X-Accel-Buffering": "no",
            },
        )


def _bridge_sync_stream(make_gen, *, maxsize: int = 32):
    """Bridge a blocking sync frame-generator to an async SSE event generator.

    The sync generator (which holds the device lock for its lifetime) is iterated
    entirely on one dedicated worker thread, so it is also *closed* on that thread
    — keeping the lock acquire/release on the same thread. Frames flow to the event
    loop through a bounded queue; client disconnect stops the worker deterministically.
    """
    q: "queue.Queue[tuple[str, str] | None]" = queue.Queue(maxsize=maxsize)
    stop = threading.Event()
    SENTINEL = None

    def producer() -> None:
        gen: Iterator[dict[str, Any]] = make_gen()
        try:
            for frame in gen:
                if stop.is_set():
                    break
                payload = json_dumps(frame)
                # Backpressure-aware put that still notices a gone consumer.
                while not stop.is_set():
                    try:
                        q.put(("frame", payload), timeout=1.0)
                        break
                    except queue.Full:
                        continue
        except Exception as exc:  # noqa: BLE001 - SSE clients need an event payload
            try:
                q.put(("error", json.dumps({"error": str(exc)}, ensure_ascii=False)), timeout=1.0)
            except queue.Full:
                pass
        finally:
            # Runs the SDK + coordinator ``finally`` blocks on THIS thread: sends
            # CMD 0x04 and releases the device/coordinator locks on the acquiring
            # thread.
            gen.close()
            try:
                q.put(SENTINEL, timeout=1.0)
            except queue.Full:
                pass

    thread = threading.Thread(target=producer, name="h1-stream", daemon=True)
    thread.start()

    async def event_stream():
        loop = asyncio.get_running_loop()
        try:
            yield ": ok\n\n"
            while True:
                item = await loop.run_in_executor(None, q.get)
                if item is SENTINEL:
                    break
                kind, payload = item
                if kind == "error":
                    yield f"event: error\ndata: {payload}\n\n"
                    break
                yield f"event: frame\ndata: {payload}\n\n"
        finally:
            # Client disconnected or stream ended: tell the worker to stop and drain
            # the queue so its puts unblock and it can close the generator cleanly.
            stop.set()
            try:
                while q.get_nowait() is not SENTINEL:
                    pass
            except queue.Empty:
                pass

    return event_stream()


def _run_h1(coordinator: CaptureCoordinator, fn):
    try:
        return fn()
    except RuntimeError as exc:
        if str(exc) == "capture busy":
            raise HTTPException(status_code=409, detail=str(exc)) from exc
        raise HTTPException(status_code=400, detail=str(exc)) from exc
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc
    except Exception as exc:
        detail: dict[str, Any] = {"error": str(exc)}
        code = getattr(exc, "code", None)
        cmd_type = getattr(exc, "cmd_type", None)
        if code is not None:
            detail["code"] = code
        if cmd_type is not None:
            detail["cmdType"] = cmd_type
        raise HTTPException(status_code=502, detail=detail) from exc
