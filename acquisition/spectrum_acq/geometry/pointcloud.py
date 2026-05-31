"""Depth ROI and point-cloud calculations."""

from __future__ import annotations

import math
from dataclasses import dataclass, field
from typing import Any

import numpy as np

from spectrum_acq.models import QualityThresholds, Roi


@dataclass(frozen=True)
class PointCloudResult:
    full_points_xyz_m: np.ndarray
    roi_points_xyz_m: np.ndarray
    roi_mask: np.ndarray


@dataclass(frozen=True)
class GeometryResult:
    distance_mm: float | None
    depth_valid_ratio: float
    normal_camera: list[float] | None
    angle_deg: float | None
    status: str
    warnings: list[str] = field(default_factory=list)
    detail: dict[str, Any] = field(default_factory=dict)


def roi_bounds(roi: Roi, width: int, height: int) -> tuple[int, int, int, int]:
    clamped = roi.clamp()
    x0 = int(round(clamped.x * width))
    y0 = int(round(clamped.y * height))
    x1 = int(round((clamped.x + clamped.width) * width))
    y1 = int(round((clamped.y + clamped.height) * height))
    x0 = min(max(x0, 0), width - 1)
    y0 = min(max(y0, 0), height - 1)
    x1 = min(max(x1, x0 + 1), width)
    y1 = min(max(y1, y0 + 1), height)
    return x0, y0, x1, y1


def pointcloud_from_depth(depth_mm: np.ndarray, intrinsics: dict[str, Any], roi: Roi) -> PointCloudResult:
    if depth_mm.ndim != 2:
        raise ValueError("depth_mm must be a 2D array")
    height, width = depth_mm.shape
    fx = float(intrinsics.get("fx", width))
    fy = float(intrinsics.get("fy", width))
    ppx = float(intrinsics.get("ppx", width / 2.0))
    ppy = float(intrinsics.get("ppy", height / 2.0))
    y, x = np.indices((height, width))
    z = depth_mm.astype(np.float64) / 1000.0
    valid = z > 0
    x_m = (x.astype(np.float64) - ppx) * z / fx
    y_m = (y.astype(np.float64) - ppy) * z / fy
    full = np.stack([x_m[valid], y_m[valid], z[valid]], axis=1)

    x0, y0, x1, y1 = roi_bounds(roi, width, height)
    roi_mask = np.zeros_like(valid, dtype=bool)
    roi_mask[y0:y1, x0:x1] = True
    roi_valid = valid & roi_mask
    roi_points = np.stack([x_m[roi_valid], y_m[roi_valid], z[roi_valid]], axis=1)
    return PointCloudResult(full_points_xyz_m=full, roi_points_xyz_m=roi_points, roi_mask=roi_valid)


def compute_geometry(
    depth_mm: np.ndarray,
    intrinsics: dict[str, Any],
    roi: Roi,
    thresholds: QualityThresholds,
) -> tuple[PointCloudResult, GeometryResult]:
    pointcloud = pointcloud_from_depth(depth_mm, intrinsics, roi)
    x0, y0, x1, y1 = roi_bounds(roi, depth_mm.shape[1], depth_mm.shape[0])
    roi_depth = depth_mm[y0:y1, x0:x1]
    valid_depth = roi_depth[roi_depth > 0]
    total_roi_px = max(int(roi_depth.size), 1)
    valid_ratio = float(valid_depth.size / total_roi_px)
    warnings: list[str] = []
    distance_mm = float(np.median(valid_depth)) if valid_depth.size else None
    if valid_ratio < thresholds.min_depth_valid_ratio:
        warnings.append("depth_valid_ratio_below_threshold")
    if distance_mm is None:
        warnings.append("distance_unknown")
    elif not (
        thresholds.recommended_distance_min_mm
        <= distance_mm
        <= thresholds.recommended_distance_max_mm
    ):
        warnings.append("distance_outside_recommended_range")

    normal = _fit_plane_normal(pointcloud.roi_points_xyz_m)
    angle_deg = None
    if normal is None:
        warnings.append("normal_unknown")
    else:
        optical_axis = np.array([0.0, 0.0, 1.0])
        dot = float(abs(np.dot(normal, optical_axis)))
        dot = max(min(dot, 1.0), -1.0)
        angle_deg = math.degrees(math.acos(dot))
        if angle_deg >= thresholds.bad_angle_deg:
            warnings.append("angle_bad")
        elif angle_deg >= thresholds.warn_angle_deg:
            warnings.append("angle_warn")

    status = "ok" if not warnings else "warn"
    return pointcloud, GeometryResult(
        distance_mm=distance_mm,
        depth_valid_ratio=valid_ratio,
        normal_camera=normal.tolist() if normal is not None else None,
        angle_deg=angle_deg,
        status=status,
        warnings=warnings,
        detail={"roi_bounds": [x0, y0, x1, y1], "roi_point_count": int(pointcloud.roi_points_xyz_m.shape[0])},
    )


def _fit_plane_normal(points_xyz_m: np.ndarray) -> np.ndarray | None:
    if points_xyz_m.shape[0] < 16:
        return None
    centroid = points_xyz_m.mean(axis=0)
    centered = points_xyz_m - centroid
    try:
        _, _, vh = np.linalg.svd(centered, full_matrices=False)
    except np.linalg.LinAlgError:
        return None
    normal = vh[-1]
    norm = np.linalg.norm(normal)
    if norm <= 0:
        return None
    normal = normal / norm
    if normal[2] < 0:
        normal = -normal
    return normal
