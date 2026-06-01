"""FastAPI app for the acquisition service."""

from __future__ import annotations

import asyncio
import json
from pathlib import Path
from typing import Any

from fastapi import FastAPI, HTTPException, Query
from fastapi.responses import FileResponse, Response, StreamingResponse
import numpy as np
from PIL import Image

from spectrum_acq import __version__
from spectrum_acq.api.h1_routes import register_h1_routes
from spectrum_acq.capture.coordinator import CaptureCoordinator, create_default_coordinator
from spectrum_acq.config import load_config, save_config
from spectrum_acq.models import AcquisitionConfig, Roi, to_jsonable

SAMPLE_FILE_PREVIEWS = {
    "d455/color.jpg": ("d455/color.jpg", "image/jpeg"),
    "d455/depth.png": ("d455/depth.png", "image/png"),
    "h1/spectrum.json": ("h1/spectrum.json", "application/json"),
}


def create_app(config: AcquisitionConfig | None = None) -> FastAPI:
    active_config = config or load_config()
    save_config(active_config)
    coordinator = create_default_coordinator(active_config)

    app = FastAPI(title="spectrum-acq", version=__version__)
    app.state.config = active_config
    app.state.coordinator = coordinator

    def apply_config(next_config: AcquisitionConfig) -> None:
        nonlocal active_config
        active_config = next_config
        coordinator.config = next_config
        coordinator.store.config = next_config
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

    @app.put("/config")
    async def put_config(body: dict[str, Any]) -> dict[str, Any]:
        cfg_path = active_config.data_dir / "config" / "acquisition.json"
        cfg_path.parent.mkdir(parents=True, exist_ok=True)
        current_payload = to_jsonable(active_config)
        next_payload = _deep_merge(current_payload, body)
        cfg_path.write_text(json.dumps(next_payload, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
        next_config = load_config(cfg_path, data_dir=active_config.data_dir)
        save_config(next_config)
        apply_config(next_config)
        restart_required = any(
            current_payload.get(field) != to_jsonable(next_config).get(field)
            for field in ["mock", "data_dir", "h1_port", "d455_profile"]
        )
        return {
            "ok": True,
            "config": to_jsonable(next_config),
            "restart_required": restart_required,
        }

    register_preview_routes(app, coordinator)

    @app.post("/capture")
    async def capture(body: dict[str, Any] | None = None) -> dict[str, Any]:
        payload = body or {}
        roi = None
        if isinstance(payload.get("roi"), dict):
            roi = Roi(**payload["roi"])
        try:
            result = coordinator.capture(
                roi=roi,
                exposure_mode=payload.get("exposure_mode"),
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

    @app.get("/samples/{sample_id}/download")
    def sample_download(sample_id: str) -> FileResponse:
        try:
            archive = coordinator.store.export_sample_zip(sample_id)
        except FileNotFoundError as exc:
            raise HTTPException(status_code=404, detail="sample not found") from exc
        return FileResponse(archive, filename=archive.name, media_type="application/zip")

    @app.get("/samples/{sample_id}/preview")
    def sample_preview(sample_id: str) -> FileResponse:
        preview = coordinator.store.sample_path(sample_id) / "roi" / "preview.jpg"
        if not preview.exists():
            raise HTTPException(status_code=404, detail="preview not found")
        return FileResponse(preview, media_type="image/jpeg")

    @app.get("/samples/{sample_id}/files/{file_key:path}")
    def sample_file_preview(sample_id: str, file_key: str) -> FileResponse:
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

    @app.post("/samples/export")
    def export_samples(body: dict[str, Any] | None = None) -> dict[str, Any]:
        payload = body or {}
        if payload:
            archive = coordinator.store.export_filtered_zip(
                quality_status=payload.get("quality_status"),
                calibration_version=payload.get("calibration_version"),
                limit=int(payload.get("limit", 1000)),
            )
        else:
            archive = coordinator.store.export_all_zip()
        return {"archive": str(archive), "filename": archive.name}

    @app.get("/calibration")
    def calibration() -> dict[str, Any]:
        path = active_config.calibration_path
        if path is None:
            return {"status": "uncalibrated", "version": None, "path": None}
        exists = Path(path).exists()
        return {"status": "configured" if exists else "missing", "version": Path(path).stem, "path": str(path)}

    @app.put("/calibration")
    async def put_calibration(body: dict[str, Any]) -> dict[str, Any]:
        version = str(body.get("version", "manual"))
        out = active_config.data_dir / "calibration" / f"{version}.json"
        out.parent.mkdir(parents=True, exist_ok=True)
        payload = {**body, "version": version}
        out.write_text(
            json.dumps(payload, ensure_ascii=False, indent=2) + "\n",
            encoding="utf-8",
        )
        next_config = type(active_config)(**{**active_config.__dict__, "calibration_path": out})
        save_config(next_config)
        apply_config(next_config)
        return {"status": "saved", "version": version, "path": str(out)}

    return app


def register_preview_routes(app: FastAPI, coordinator: CaptureCoordinator) -> None:
    @app.get("/preview/d455/status")
    def preview_d455_status() -> dict[str, Any]:
        return to_jsonable(coordinator.d455.status())

    @app.get("/preview/d455/frame")
    def preview_d455_frame() -> Response:
        snapshot = coordinator.d455.snapshot()
        image = Image.fromarray(snapshot.color_rgb, mode="RGB")
        import io

        buf = io.BytesIO()
        image.save(buf, format="JPEG", quality=80)
        return Response(content=buf.getvalue(), media_type="image/jpeg")

    @app.get("/preview/d455/depth")
    def preview_d455_depth() -> Response:
        snapshot = coordinator.d455.snapshot()
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


def _read_json(path: Path) -> Any:
    return json.loads(path.read_text(encoding="utf-8"))


def _deep_merge(base: dict[str, Any], overlay: dict[str, Any]) -> dict[str, Any]:
    out = dict(base)
    for key, value in overlay.items():
        if isinstance(value, dict) and isinstance(out.get(key), dict):
            out[key] = _deep_merge(out[key], value)
        else:
            out[key] = value
    return out
