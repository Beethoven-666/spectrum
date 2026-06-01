"""H1 debug/control REST routes for the acquisition service."""

from __future__ import annotations

import json
from typing import Any

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
    def h1_stream(
        tm30: bool = Query(default=False),
        max_frames: int | None = Query(default=None, ge=1, le=1000),
    ) -> StreamingResponse:
        def stream():
            yield ": ok\n\n"
            try:
                for frame in coordinator.stream_h1(include_tm30=tm30, max_frames=max_frames):
                    payload = json_dumps(frame)
                    yield f"event: frame\ndata: {payload}\n\n"
            except Exception as exc:  # noqa: BLE001 - SSE clients need an event payload
                payload = json.dumps({"error": str(exc)}, ensure_ascii=False)
                yield f"event: error\ndata: {payload}\n\n"

        return StreamingResponse(
            stream(),
            media_type="text/event-stream",
            headers={
                "Cache-Control": "no-cache, no-transform",
                "Connection": "keep-alive",
                "X-Accel-Buffering": "no",
            },
        )


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
