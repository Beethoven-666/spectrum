"""Filesystem sample package writer and export helpers."""

from __future__ import annotations

import csv
import json
import logging
import math
import os
import shutil
import zipfile
from pathlib import Path
from typing import Any

import numpy as np
from PIL import Image, ImageDraw

from spectrum_acq import paths
from spectrum_acq.devices.interfaces import D455Snapshot, H1Capture, MainRgbCapture
from spectrum_acq.geometry.pointcloud import GeometryResult, PointCloudResult, roi_bounds
from spectrum_acq.models import AcquisitionConfig, CaptureResult, QualityStatus, Roi, to_jsonable, utc_now

from .ply import write_ascii_ply
from .sqlite_index import SampleIndex, directory_size

logger = logging.getLogger(__name__)


class SampleStore:
    def __init__(self, config: AcquisitionConfig) -> None:
        self.config = config
        self.root = config.data_dir
        self.samples_dir = self.root / "samples"
        self.tmp_dir = self.root / ".tmp"
        self.exports_dir = self.root / "exports"
        self.index = SampleIndex(self.root / "index" / "samples.sqlite3")
        self.samples_dir.mkdir(parents=True, exist_ok=True)
        self.tmp_dir.mkdir(parents=True, exist_ok=True)
        self.exports_dir.mkdir(parents=True, exist_ok=True)

    def write_sample(
        self,
        *,
        sample_id: str,
        h1: H1Capture,
        d455: D455Snapshot,
        main_rgb: MainRgbCapture,
        pointcloud: PointCloudResult,
        geometry: GeometryResult,
        roi: Roi,
        quality: dict[str, Any],
        metadata: dict[str, Any],
    ) -> CaptureResult:
        partial = self.tmp_dir / f"{sample_id}.partial"
        final = self.samples_dir / sample_id
        if partial.exists():
            shutil.rmtree(partial)
        if final.exists():
            raise FileExistsError(f"sample already exists: {sample_id}")
        partial.mkdir(parents=True)
        try:
            # Build the whole sample in the .partial directory. Any failure
            # here (payload write) must NOT leave a sample under samples/, so
            # this is the only section that can raise into a FAILED capture.
            self._write_payload(
                partial,
                h1=h1,
                d455=d455,
                main_rgb=main_rgb,
                pointcloud=pointcloud,
                geometry=geometry,
                roi=roi,
                quality=quality,
                metadata=metadata,
            )
            # M7 (durability): fsync the payload directory tree before the
            # rename so a power loss cannot leave a renamed-but-empty sample.
            _fsync_tree(partial)
        except Exception as exc:
            # The sample never reached samples/, so the on-disk state is clean.
            # Quarantine the partial payload for offline diagnosis and re-raise
            # so the capture is reported FAILED (and stays unindexed).
            if partial.exists():
                _write_json(
                    partial / "error.json",
                    {
                        "sample_id": sample_id,
                        "error": str(exc),
                    },
                )
            failed = self.tmp_dir / f"{sample_id}.failed"
            if failed.exists():
                shutil.rmtree(failed)
            if partial.exists():
                partial.rename(failed)
            raise

        # H4 / M7: the rename is the atomic commit point. Once it succeeds the
        # sample is a complete, durable directory under samples/. We then fsync
        # the parent so the rename itself survives a power loss.
        partial.rename(final)
        _fsync_dir(self.samples_dir)

        # H4: index the FINAL path AFTER the sample is durably on disk, and make
        # the upsert best-effort. A failing index write must never turn a
        # complete on-disk sample into a FAILED-but-present, unindexed sample;
        # the filesystem is the source of truth and ``rebuild_index`` reconciles
        # the SQLite cache. We log loudly so the gap is visible/operable.
        try:
            self.index.upsert_sample(final, metadata, quality)
        except Exception:  # noqa: BLE001 - index is a rebuildable cache, not the truth
            logger.exception(
                "sample %s written to %s but index upsert failed; "
                "sample is on disk and recoverable via rebuild_index()",
                sample_id,
                final,
            )

        return CaptureResult(
            sample_id=sample_id,
            sample_path=str(final),
            quality_status=QualityStatus(quality["status"]),
            warnings=list(quality.get("warnings", [])),
            metadata=metadata,
        )

    def storage_status(self) -> dict[str, Any]:
        # L7: disk_usage can raise OSError (e.g. the data_dir is on a mount that
        # went away). Don't let that surface as an opaque 500 that aborts a
        # capture; report a "storage-unavailable" status instead. The free-space
        # gate in the coordinator only blocks on ``free_bytes <= stop_free_bytes``
        # AND ``status`` checks, so a BAD/unknown status fails safe (capture is
        # marked low-quality / blocked rather than crashing).
        try:
            usage = shutil.disk_usage(self.root)
        except OSError as exc:
            logger.warning("storage_status: disk_usage(%s) failed: %s", self.root, exc)
            # Fail safe: report zero free space so the numeric free-space gates in
            # the coordinator / export helpers treat storage as full (block /
            # warn) rather than raising on a None comparison. The ``available``
            # flag and ``error`` string carry the real "unknown" signal.
            return {
                "data_dir": str(self.root),
                "total_bytes": 0,
                "used_bytes": 0,
                "free_bytes": 0,
                "warn_free_bytes": self.config.disk.warn_free_bytes,
                "stop_free_bytes": self.config.disk.stop_free_bytes,
                "status": QualityStatus.BAD,
                "available": False,
                "error": str(exc),
            }
        free = usage.free
        if free <= self.config.disk.stop_free_bytes:
            status = QualityStatus.BAD
        elif free <= self.config.disk.warn_free_bytes:
            status = QualityStatus.WARN
        else:
            status = QualityStatus.GOOD
        return {
            "data_dir": str(self.root),
            "total_bytes": usage.total,
            "used_bytes": usage.used,
            "free_bytes": usage.free,
            "warn_free_bytes": self.config.disk.warn_free_bytes,
            "stop_free_bytes": self.config.disk.stop_free_bytes,
            "status": status,
            "available": True,
        }

    def list_samples(self, *, limit: int = 100) -> list[dict[str, Any]]:
        return self.index.list_samples(limit=limit)

    def get_sample(self, sample_id: str) -> dict[str, Any] | None:
        return self.index.get_sample(sample_id)

    def sample_path(self, sample_id: str) -> Path:
        # M17: never trust ``sample_id`` to be a bare component. Route it through
        # paths.safe_join so a traversal payload (e.g. "../../etc") cannot escape
        # samples_dir. safe_join raises ValueError on an invalid name or an
        # escape; callers (API routes) already pre-validate and treat failures
        # as 404, but this is the authoritative containment layer.
        return paths.safe_join(self.samples_dir, sample_id)

    def export_sample_zip(self, sample_id: str) -> Path:
        sample_path = self.sample_path(sample_id)
        if not sample_path.exists():
            raise FileNotFoundError(sample_id)
        self._ensure_export_space(directory_size(sample_path))
        out = self.exports_dir / f"{sample_id}.zip"
        _zip_directory(sample_path, out, root_name=sample_id)
        return out

    def export_all_zip(self) -> Path:
        created = utc_now().strftime("%Y%m%dT%H%M%SZ")
        out = self.exports_dir / f"samples_{created}.zip"
        self._export_sample_paths(list(self._iter_sample_dirs()), out)
        return out

    def export_filtered_zip(
        self,
        *,
        quality_status: str | None = None,
        calibration_version: str | None = None,
        limit: int = 1000,
    ) -> Path:
        rows = self.index.query_samples(
            limit=limit,
            quality_status=quality_status,
            calibration_version=calibration_version,
        )
        sample_paths = [Path(row["path"]) for row in rows]
        created = utc_now().strftime("%Y%m%dT%H%M%SZ")
        parts = ["samples"]
        if quality_status:
            parts.append(quality_status)
        if calibration_version:
            parts.append(calibration_version)
        out = self.exports_dir / f"{'_'.join(parts)}_{created}.zip"
        self._export_sample_paths(sample_paths, out)
        return out

    def rebuild_index(self) -> int:
        return self.index.rebuild(self.samples_dir)

    def _iter_sample_dirs(self) -> list[Path]:
        return [sample for sample in sorted(self.samples_dir.iterdir()) if sample.is_dir()]

    def _export_sample_paths(self, sample_paths: list[Path], out: Path) -> None:
        estimated_bytes = sum(directory_size(path) for path in sample_paths if path.exists())
        self._ensure_export_space(estimated_bytes)
        with zipfile.ZipFile(out, "w", compression=zipfile.ZIP_DEFLATED) as zf:
            for sample in sample_paths:
                if not sample.exists() or not sample.is_dir():
                    continue
                for file in sample.rglob("*"):
                    if file.is_file():
                        zf.write(file, file.relative_to(self.samples_dir))

    def _ensure_export_space(self, estimated_bytes: int) -> None:
        storage = self.storage_status()
        remaining_after_export = storage["free_bytes"] - estimated_bytes
        if remaining_after_export <= self.config.disk.stop_free_bytes:
            raise RuntimeError("low disk space for export")

    def _write_payload(
        self,
        root: Path,
        *,
        h1: H1Capture,
        d455: D455Snapshot,
        main_rgb: MainRgbCapture,
        pointcloud: PointCloudResult,
        geometry: GeometryResult,
        roi: Roi,
        quality: dict[str, Any],
        metadata: dict[str, Any],
    ) -> None:
        for dirname in ["h1", "d455", "main_rgb", "roi"]:
            (root / dirname).mkdir(parents=True, exist_ok=True)

        _write_json(root / "metadata.json", metadata)
        _write_json(root / "quality.json", quality)

        spectrum = {
            "status": to_jsonable(h1.status),
            "selected_attempt": to_jsonable(h1.selected_attempt),
            "wavelengths": h1.wavelengths,
            "raw_spectrum": h1.raw_spectrum,
            "actual_spectrum": h1.actual_spectrum,
            "photometric": h1.photometric,
            "plant": h1.plant,
            "spectrum_coefficient": h1.spectrum_coefficient,
        }
        _write_json(root / "h1" / "spectrum.json", spectrum)
        _write_json(root / "h1" / "exposure_attempts.json", [to_jsonable(a) for a in h1.attempts])
        _write_spectrum_csv(root / "h1" / "spectrum.csv", h1.wavelengths, h1.raw_spectrum, h1.actual_spectrum)
        _write_exposure_frames(root / "h1", h1)

        _save_rgb(root / "d455" / "color.jpg", d455.color_rgb)
        Image.fromarray(d455.depth_mm.astype(np.uint16)).save(root / "d455" / "depth.png")
        np.save(root / "d455" / "depth.npy", d455.depth_mm)
        _write_json(root / "d455" / "imu.json", d455.imu)
        write_ascii_ply(root / "d455" / "pointcloud_full.ply", pointcloud.full_points_xyz_m)
        write_ascii_ply(root / "d455" / "pointcloud_roi.ply", pointcloud.roi_points_xyz_m)

        # status.json carries status + metadata only — NOT the raw frame. The
        # image is written separately as color.jpg below; embedding the ndarray
        # here would bloat the JSON with a 640x480x3 nested list (and used to crash
        # the whole capture before to_jsonable handled numpy).
        _write_json(
            root / "main_rgb" / "status.json",
            {
                "status": to_jsonable(main_rgb.status),
                "captured_at": main_rgb.captured_at,
                "metadata": to_jsonable(main_rgb.metadata),
                "has_image": main_rgb.image_rgb is not None,
            },
        )
        if main_rgb.image_rgb is not None:
            _save_rgb(root / "main_rgb" / "color.jpg", main_rgb.image_rgb)

        _write_json(
            root / "roi" / "roi.json",
            {
                "roi": to_jsonable(roi),
                "geometry": to_jsonable(geometry),
                "coordinate_space": "d455_color",
            },
        )
        _save_roi_preview(root / "roi" / "preview.jpg", d455.color_rgb, roi)


def _write_json(path: Path, payload: Any) -> None:
    # M7 (durability): flush + fsync so the JSON metadata/quality artifacts hit
    # stable storage. quality.json/metadata.json are the artifacts ``rebuild``
    # relies on to reconstruct the index, so they must survive a power loss.
    with path.open("w", encoding="utf-8") as f:
        json.dump(to_jsonable(payload), f, ensure_ascii=False, indent=2)
        f.write("\n")
        f.flush()
        os.fsync(f.fileno())


def _fsync_dir(path: Path) -> None:
    """fsync a directory so renames/creations of its entries are durable.

    Directory fsync is how POSIX guarantees a rename (or the appearance of a
    new file) survives a crash. Best-effort: some filesystems / platforms
    disallow opening a directory for fsync, in which case we log and move on
    rather than failing an otherwise-successful capture.
    """
    try:
        fd = os.open(path, os.O_RDONLY)
    except OSError as exc:  # pragma: no cover - platform/filesystem dependent
        logger.debug("fsync_dir: open(%s) failed: %s", path, exc)
        return
    try:
        os.fsync(fd)
    except OSError as exc:  # pragma: no cover - platform/filesystem dependent
        logger.debug("fsync_dir: fsync(%s) failed: %s", path, exc)
    finally:
        os.close(fd)


def _fsync_tree(root: Path) -> None:
    """fsync every file and directory under *root* (inclusive).

    Used to make a freshly-written sample payload durable before the atomic
    rename into samples/. We fsync files first, then their containing
    directories, finishing with *root* itself.
    """
    for child in sorted(root.rglob("*"), key=lambda p: len(p.parts), reverse=True):
        if child.is_file():
            try:
                fd = os.open(child, os.O_RDONLY)
            except OSError as exc:  # pragma: no cover - filesystem dependent
                logger.debug("fsync_tree: open(%s) failed: %s", child, exc)
                continue
            try:
                os.fsync(fd)
            except OSError as exc:  # pragma: no cover - filesystem dependent
                logger.debug("fsync_tree: fsync(%s) failed: %s", child, exc)
            finally:
                os.close(fd)
        elif child.is_dir():
            _fsync_dir(child)
    _fsync_dir(root)


def _csv_cell(value: Any) -> Any:
    """L2: render a CSV cell, blanking non-finite floats.

    JSON serialisation nullifies NaN/inf (via ``to_jsonable``), but the CSV
    writer would otherwise emit literal ``nan``/``inf`` tokens. Mirror the JSON
    behaviour by writing an empty cell for any non-finite float so the two
    representations agree and downstream parsers don't choke.
    """
    if isinstance(value, float) and not math.isfinite(value):
        return ""
    return value


def _write_spectrum_csv(
    path: Path, wavelengths: list[int], raw: list[int], actual: list[float]
) -> None:
    with path.open("w", encoding="utf-8", newline="") as f:
        writer = csv.writer(f)
        writer.writerow(["wavelength_nm", "raw", "actual"])
        writer.writerows(
            (_csv_cell(w), _csv_cell(r), _csv_cell(a)) for w, r, a in zip(wavelengths, raw, actual)
        )


def _write_exposure_frames(h1_dir: Path, h1: H1Capture) -> None:
    """Persist every exposure level for offline study (multi_exposure mode).

    No-op for the other modes, which only keep the selected ``spectrum.{json,csv}``.
    """
    if not h1.frames:
        return
    exposures_dir = h1_dir / "exposures"
    exposures_dir.mkdir(parents=True, exist_ok=True)
    summary = []
    for frame in h1.frames:
        csv_name = f"attempt_{frame.attempt:02d}.csv"
        _write_spectrum_csv(
            exposures_dir / csv_name, h1.wavelengths, frame.raw_spectrum, frame.actual_spectrum
        )
        summary.append(
            {
                "attempt": frame.attempt,
                "exposure_time_us": frame.exposure_time_us,
                "exposure_status": frame.exposure_status,
                "spectrum_coefficient": frame.spectrum_coefficient,
                "selected": frame.selected,
                "csv": f"exposures/{csv_name}",
            }
        )
    _write_json(h1_dir / "exposures.json", summary)


def _save_rgb(path: Path, image_rgb: np.ndarray) -> None:
    Image.fromarray(image_rgb.astype(np.uint8), mode="RGB").save(path, quality=90)


def _save_roi_preview(path: Path, image_rgb: np.ndarray, roi: Roi) -> None:
    image = Image.fromarray(image_rgb.astype(np.uint8), mode="RGB")
    draw = ImageDraw.Draw(image)
    x0, y0, x1, y1 = roi_bounds(roi, image.width, image.height)
    draw.rectangle([x0, y0, x1 - 1, y1 - 1], outline=(255, 230, 0), width=2)
    image.save(path, quality=90)


def _zip_directory(source: Path, out: Path, *, root_name: str) -> None:
    out.parent.mkdir(parents=True, exist_ok=True)
    with zipfile.ZipFile(out, "w", compression=zipfile.ZIP_DEFLATED) as zf:
        for file in source.rglob("*"):
            if file.is_file():
                zf.write(file, Path(root_name) / file.relative_to(source))
