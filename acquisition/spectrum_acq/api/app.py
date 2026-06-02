"""FastAPI app for the acquisition service."""

from __future__ import annotations

import asyncio
import json
import logging
import uuid
from contextlib import asynccontextmanager
from pathlib import Path
from typing import Any

from fastapi import Depends, FastAPI, HTTPException, Query
from fastapi.responses import FileResponse, Response, StreamingResponse
import numpy as np
from PIL import Image

from spectrum_acq import __version__
from spectrum_acq import paths
from spectrum_acq.api.auth import require_token
from spectrum_acq.api.h1_routes import register_h1_routes
from spectrum_acq.capture.coordinator import CaptureCoordinator, create_default_coordinator
from spectrum_acq.config import load_config, save_config
from spectrum_acq.models import AcquisitionConfig, Roi, to_jsonable

logger = logging.getLogger(__name__)

SAMPLE_FILE_PREVIEWS = {
    "d455/color.jpg": ("d455/color.jpg", "image/jpeg"),
    "d455/depth.png": ("d455/depth.png", "image/png"),
    "h1/spectrum.json": ("h1/spectrum.json", "application/json"),
}

# L1: only these H1 auto-exposure modes are accepted from request bodies;
# anything else is rejected with HTTP 400 rather than silently falling through.
VALID_EXPOSURE_MODES = {"conservative", "strict", "multi_exposure"}


def create_app(config: AcquisitionConfig | None = None) -> FastAPI:
    active_config = config or load_config()
    save_config(active_config)
    coordinator = create_default_coordinator(active_config)

    @asynccontextmanager
    async def lifespan(_app: FastAPI):
        try:
            yield
        finally:
            coordinator.close()

    app = FastAPI(title="spectrum-acq", version=__version__, lifespan=lifespan)
    app.state.config = active_config
    app.state.coordinator = coordinator

    def apply_config(next_config: AcquisitionConfig) -> None:
        nonlocal active_config
        active_config = next_config
        coordinator.apply_config(next_config)
        app.state.config = next_config

    @app.get("/health")
    def health() -> dict[str, Any]:
        return {
            "ok": True,
            "service": "spectrum-acq",
            "version": __version__,
            "mock": active_config.mock,
        }

    @app.get("/devices")
    def devices() -> dict[str, Any]:
        return to_jsonable(coordinator.devices())

    register_h1_routes(app, coordinator)

    @app.get("/storage")
    def storage() -> dict[str, Any]:
        return to_jsonable(coordinator.store.storage_status())

    @app.get("/config")
    def get_config() -> dict[str, Any]:
        return to_jsonable(active_config)

    # M1: plain ``def`` so FastAPI runs these blocking handlers (file I/O,
    # config reload, capture) in its threadpool instead of stalling the event
    # loop. H1: state-changing routes are gated behind ``require_token``.
    @app.put("/config", dependencies=[Depends(require_token)])
    def put_config(body: dict[str, Any]) -> dict[str, Any]:
        cfg_path = active_config.data_dir / "config" / "acquisition.json"
        cfg_path.parent.mkdir(parents=True, exist_ok=True)
        current_payload = to_jsonable(active_config)
        next_payload = _deep_merge(current_payload, body)
        cfg_path.write_text(json.dumps(next_payload, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
        next_config = load_config(cfg_path, data_dir=active_config.data_dir)
        save_config(next_config)
        apply_config(next_config)
        # d455_profile / main_rgb_profile / streaming now hot-apply via
        # coordinator.apply_config (camera workers rebuild), so they are no
        # longer restart-required. mock / data_dir / h1_port still are.
        restart_required = any(
            current_payload.get(field) != to_jsonable(next_config).get(field)
            for field in ["mock", "data_dir", "h1_port"]
        )
        return {
            "ok": True,
            "config": to_jsonable(next_config),
            "restart_required": restart_required,
        }

    register_preview_routes(app, coordinator)

    @app.post("/capture", dependencies=[Depends(require_token)])
    def capture(body: dict[str, Any] | None = None) -> dict[str, Any]:
        payload = body or {}
        roi = None
        if isinstance(payload.get("roi"), dict):
            # Unverified-low: a malformed roi object (unknown/extra keys, wrong
            # types) makes Roi(**...) raise TypeError. Surface that as 400
            # rather than letting it bubble up to a 500.
            try:
                roi = Roi(**payload["roi"])
            except TypeError as exc:
                raise HTTPException(status_code=400, detail="invalid roi") from exc
        # L1: validate the requested exposure mode up front instead of letting
        # an unknown value silently reach the coordinator.
        exposure_mode = payload.get("exposure_mode")
        if exposure_mode is not None and exposure_mode not in VALID_EXPOSURE_MODES:
            raise HTTPException(status_code=400, detail="invalid exposure_mode")
        try:
            result = coordinator.capture(
                roi=roi,
                exposure_mode=exposure_mode,
                force=bool(payload.get("force", False)),
            )
        except RuntimeError as exc:
            raise HTTPException(status_code=409 if str(exc) == "capture busy" else 400, detail=str(exc)) from exc
        return to_jsonable(result)

    @app.get("/capture/current")
    def capture_current() -> dict[str, Any]:
        return coordinator.state

    @app.get("/events")
    async def events() -> StreamingResponse:
        async def stream():
            last_payload = ""
            while True:
                payload = json.dumps(to_jsonable(coordinator.state), ensure_ascii=False)
                if payload != last_payload:
                    yield f"event: state\ndata: {payload}\n\n"
                    last_payload = payload
                await asyncio.sleep(0.5)

        return StreamingResponse(stream(), media_type="text/event-stream")

    @app.get("/samples")
    def samples(limit: int = Query(default=100, ge=1, le=1000)) -> dict[str, Any]:
        return {"samples": to_jsonable(coordinator.store.list_samples(limit=limit))}

    @app.get("/samples/{sample_id}")
    def sample(sample_id: str) -> dict[str, Any]:
        row = coordinator.store.get_sample(sample_id)
        if row is None:
            raise HTTPException(status_code=404, detail="sample not found")
        sample_path = coordinator.store.sample_path(sample_id)
        metadata_path = sample_path / "metadata.json"
        quality_path = sample_path / "quality.json"
        return {
            "index": row,
            "metadata": _read_json(metadata_path),
            "quality": _read_json(quality_path),
        }

    # H1: sample file-access routes are gated behind ``require_token``.
    # M17: validate the id and require it to exist in the index before
    # touching the filesystem (the hardened SampleStore.sample_path adds
    # path-traversal containment as a second layer of defence).
    @app.get("/samples/{sample_id}/download", dependencies=[Depends(require_token)])
    def sample_download(sample_id: str) -> FileResponse:
        if not paths.valid_name(sample_id):
            raise HTTPException(status_code=404, detail="sample not found")
        if coordinator.store.get_sample(sample_id) is None:
            raise HTTPException(status_code=404, detail="sample not found")
        try:
            archive = coordinator.store.export_sample_zip(sample_id)
        except FileNotFoundError as exc:
            raise HTTPException(status_code=404, detail="sample not found") from exc
        return FileResponse(archive, filename=archive.name, media_type="application/zip")

    @app.get("/samples/{sample_id}/preview", dependencies=[Depends(require_token)])
    def sample_preview(sample_id: str) -> FileResponse:
        if not paths.valid_name(sample_id):
            raise HTTPException(status_code=404, detail="preview not found")
        if coordinator.store.get_sample(sample_id) is None:
            raise HTTPException(status_code=404, detail="preview not found")
        preview = coordinator.store.sample_path(sample_id) / "roi" / "preview.jpg"
        if not preview.exists():
            raise HTTPException(status_code=404, detail="preview not found")
        return FileResponse(preview, media_type="image/jpeg")

    @app.get("/samples/{sample_id}/files/{file_key:path}", dependencies=[Depends(require_token)])
    def sample_file_preview(sample_id: str, file_key: str) -> FileResponse:
        if not paths.valid_name(sample_id):
            raise HTTPException(status_code=404, detail="sample not found")
        if coordinator.store.get_sample(sample_id) is None:
            raise HTTPException(status_code=404, detail="sample not found")
        file_def = SAMPLE_FILE_PREVIEWS.get(file_key)
        if file_def is None:
            raise HTTPException(status_code=404, detail="sample file not allowed")
        relative_path, media_type = file_def
        sample_file = coordinator.store.sample_path(sample_id) / relative_path
        if not sample_file.exists() or not sample_file.is_file():
            raise HTTPException(status_code=404, detail="sample file not found")
        return FileResponse(sample_file, media_type=media_type)

    @app.post("/samples/export", dependencies=[Depends(require_token)])
    def export_samples(body: dict[str, Any] | None = None) -> dict[str, Any]:
        payload = body or {}
        if payload:
            # Unverified-low: clamp the requested limit to a sane bound (1..1000)
            # so a caller can't request an unbounded export. A non-integer value
            # is rejected with 400 rather than raising a ValueError -> 500.
            try:
                limit = int(payload.get("limit", 1000))
            except (TypeError, ValueError) as exc:
                raise HTTPException(status_code=400, detail="invalid limit") from exc
            limit = max(1, min(limit, 1000))
            archive = coordinator.store.export_filtered_zip(
                quality_status=payload.get("quality_status"),
                calibration_version=payload.get("calibration_version"),
                limit=limit,
            )
        else:
            archive = coordinator.store.export_all_zip()
        # Unverified-low: do not leak the absolute server filesystem path. Return
        # only the archive's basename as an opaque reference; the existing
        # download routes (keyed by filename) remain the way to fetch it.
        return {"filename": archive.name}

    @app.get("/calibration")
    def calibration() -> dict[str, Any]:
        path = active_config.calibration_path
        if path is None:
            return {"status": "uncalibrated", "version": None, "path": None}
        exists = Path(path).exists()
        return {"status": "configured" if exists else "missing", "version": Path(path).stem, "path": str(path)}

    @app.put("/calibration", dependencies=[Depends(require_token)])
    def put_calibration(body: dict[str, Any]) -> dict[str, Any]:
        version = str(body.get("version", "manual"))
        calib_dir = active_config.data_dir / "calibration"
        calib_dir.mkdir(parents=True, exist_ok=True)
        # H2: the version comes straight from the request body and is used as a
        # filename, so route it through safe_join (which enforces valid_name and
        # path containment) instead of trusting it. Reject traversal/injection
        # attempts with 400 rather than writing outside calib_dir.
        try:
            out = paths.safe_join(calib_dir, f"{version}.json")
        except ValueError as exc:
            raise HTTPException(status_code=400, detail="invalid calibration version") from exc
        payload = {**body, "version": version}
        try:
            out.write_text(
                json.dumps(payload, ensure_ascii=False, indent=2) + "\n",
                encoding="utf-8",
            )
            next_config = type(active_config)(**{**active_config.__dict__, "calibration_path": out})
            save_config(next_config)
            apply_config(next_config)
        except Exception:  # noqa: BLE001
            # L3: never leak str(exc)/internals to the client. Log the detail
            # server-side with a correlation id and return a generic message.
            correlation_id = uuid.uuid4().hex[:12]
            logger.exception("calibration save failed (correlation_id=%s)", correlation_id)
            raise HTTPException(
                status_code=500,
                detail=f"calibration save failed (ref {correlation_id})",
            ) from None
        return {"status": "saved", "version": version, "path": str(out)}

    return app


def register_preview_routes(app: FastAPI, coordinator: CaptureCoordinator) -> None:
    @app.get("/preview/d455/status")
    def preview_d455_status() -> dict[str, Any]:
        return to_jsonable(coordinator.d455.status())

    @app.get("/preview/d455/frame")
    def preview_d455_frame() -> Response:
        snapshot = coordinator.d455.preview()
        if snapshot is None:
            raise HTTPException(status_code=503, detail="d455 warming up")
        image = Image.fromarray(snapshot.color_rgb, mode="RGB")
        import io

        buf = io.BytesIO()
        image.save(buf, format="JPEG", quality=80)
        return Response(content=buf.getvalue(), media_type="image/jpeg")

    @app.get("/preview/d455/depth")
    def preview_d455_depth() -> Response:
        snapshot = coordinator.d455.preview()
        if snapshot is None:
            raise HTTPException(status_code=503, detail="d455 warming up")
        import io

        depth = snapshot.depth_mm.astype("float32")
        valid = depth[depth > 0]
        if valid.size:
            near = float(np.percentile(valid, 2))
            far = float(np.percentile(valid, 98))
            scale = np.clip((depth - near) / max(far - near, 1.0), 0.0, 1.0)
        else:
            scale = np.zeros_like(depth)
        image = Image.fromarray((scale * 255).astype("uint8"), mode="L")
        buf = io.BytesIO()
        image.save(buf, format="PNG")
        return Response(content=buf.getvalue(), media_type="image/png")

    @app.get("/preview/d455/imu")
    def preview_d455_imu() -> dict[str, Any]:
        try:
            snapshot = coordinator.d455.preview()
        except Exception as exc:  # noqa: BLE001 - surface to the attitude indicator as JSON
            return {"available": False, "enabled": False, "error": str(exc)}
        if snapshot is None:
            return {
                "available": False,
                "enabled": coordinator.config.d455_profile.enable_imu,
                "error": "warming up",
            }
        return to_jsonable(snapshot.imu)

    @app.get("/preview/main_rgb/status")
    def preview_main_rgb_status() -> dict[str, Any]:
        return to_jsonable(coordinator.main_rgb.status())

    @app.get("/preview/main_rgb/frame")
    def preview_main_rgb_frame() -> Response:
        capture = coordinator.main_rgb.preview()
        if capture is None or capture.image_rgb is None:
            detail = "main RGB unavailable"
            if capture is not None:
                detail = capture.metadata.get("error") or capture.metadata.get("reason") or detail
            raise HTTPException(status_code=503, detail=detail)
        import io

        image = Image.fromarray(capture.image_rgb, mode="RGB")
        buf = io.BytesIO()
        image.save(buf, format="JPEG", quality=85)
        return Response(content=buf.getvalue(), media_type="image/jpeg")


def _read_json(path: Path) -> Any:
    # Unverified-low: a sample whose metadata/quality file is missing or
    # corrupt must not 500 the detail endpoint. Return None so the caller can
    # render a partial record instead.
    try:
        return json.loads(path.read_text(encoding="utf-8"))
    except (FileNotFoundError, json.JSONDecodeError, OSError):
        return None


def _deep_merge(base: dict[str, Any], overlay: dict[str, Any]) -> dict[str, Any]:
    out = dict(base)
    for key, value in overlay.items():
        if isinstance(value, dict) and isinstance(out.get(key), dict):
            out[key] = _deep_merge(out[key], value)
        else:
            out[key] = value
    return out
