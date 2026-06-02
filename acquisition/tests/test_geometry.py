from __future__ import annotations

import math
from types import SimpleNamespace

import numpy as np

from spectrum_acq.capture.coordinator import CaptureCoordinator
from spectrum_acq.config import default_config
from spectrum_acq.geometry import compute_geometry
from spectrum_acq.geometry.pointcloud import GeometryResult, _fit_plane_normal
from spectrum_acq.models import DeviceStatus, QualityStatus, QualityThresholds, Roi


# Default intrinsics for a small synthetic frame: fx == fy == width, principal
# point at the image centre. Mirrors pointcloud_from_depth's own defaults so the
# back-projection is a clean pinhole.
def _intrinsics(width: int, height: int) -> dict[str, float]:
    return {"fx": float(width), "fy": float(width), "ppx": width / 2.0, "ppy": height / 2.0}


def _tilted_plane_depth_mm(
    width: int,
    height: int,
    intrinsics: dict[str, float],
    *,
    tilt_deg: float,
    plane_distance_m: float = 0.5,
) -> np.ndarray:
    """Synthesize a depth image of a flat plane tilted ``tilt_deg`` about the Y axis.

    The plane normal in camera space is ``(sin t, 0, cos t)`` and the plane is
    ``n . X = plane_distance_m``. For each pixel ray ``r = ((u-ppx)/fx,
    (v-ppy)/fy, 1)`` the surface point is ``z * r`` with ``z = d / (n . r)``, so
    back-projecting the resulting depth must recover a plane whose normal makes
    exactly ``tilt_deg`` with the optical axis (up to uint16 rounding).
    """
    fx, fy = intrinsics["fx"], intrinsics["fy"]
    ppx, ppy = intrinsics["ppx"], intrinsics["ppy"]
    theta = math.radians(tilt_deg)
    nx, nz = math.sin(theta), math.cos(theta)
    y, x = np.indices((height, width))
    rx = (x - ppx) / fx
    denom = nx * rx + nz  # n . r  (n_y == 0, r_z == 1)
    z_m = plane_distance_m / denom
    z_m = np.clip(z_m, 0.0, 5.0)
    return np.rint(z_m * 1000.0).astype(np.uint16)


def test_geometry_center_roi_plane() -> None:
    depth = np.full((20, 30), 420, dtype=np.uint16)
    intrinsics = {"fx": 30.0, "fy": 30.0, "ppx": 15.0, "ppy": 10.0}

    pointcloud, geometry = compute_geometry(depth, intrinsics, Roi(), QualityThresholds())

    assert pointcloud.full_points_xyz_m.shape[0] == 600
    assert pointcloud.roi_points_xyz_m.shape[0] > 0
    assert geometry.distance_mm == 420.0
    assert geometry.depth_valid_ratio == 1.0
    assert geometry.angle_deg is not None
    assert geometry.angle_deg < 1.0


def test_geometry_tilted_plane_reports_known_angle() -> None:
    # M14: a plane tilted 30 deg about Y must be recovered as ~30 deg (the
    # rounding to integer millimetres leaves a sub-degree residual).
    width, height = 40, 40
    intrinsics = _intrinsics(width, height)
    full_roi = Roi(x=0.0, y=0.0, width=1.0, height=1.0)
    depth = _tilted_plane_depth_mm(width, height, intrinsics, tilt_deg=30.0)

    _, geometry = compute_geometry(depth, intrinsics, full_roi, QualityThresholds())

    assert geometry.angle_deg is not None
    assert abs(geometry.angle_deg - 30.0) < 1.0
    # 30 deg is below the default warn (45) / bad (70) thresholds.
    assert "angle_bad" not in geometry.warnings
    assert "angle_warn" not in geometry.warnings


def test_geometry_all_zero_depth_has_no_points_or_normal() -> None:
    # M14: an all-zero depth frame yields no valid points, no distance, no
    # normal, and the matching warnings (and a non-"ok" status).
    depth = np.zeros((20, 30), dtype=np.uint16)
    intrinsics = {"fx": 30.0, "fy": 30.0, "ppx": 15.0, "ppy": 10.0}

    pointcloud, geometry = compute_geometry(depth, intrinsics, Roi(), QualityThresholds())

    assert pointcloud.full_points_xyz_m.shape == (0, 3)
    assert pointcloud.roi_points_xyz_m.shape == (0, 3)
    assert geometry.distance_mm is None
    assert geometry.depth_valid_ratio == 0.0
    assert geometry.angle_deg is None
    assert geometry.normal_camera is None
    assert geometry.status != "ok"
    assert "depth_valid_ratio_below_threshold" in geometry.warnings
    assert "distance_unknown" in geometry.warnings
    assert "normal_unknown" in geometry.warnings


def test_fit_plane_normal_requires_at_least_16_points() -> None:
    # M14: _fit_plane_normal returns None below its 16-point floor and a unit
    # vector at/above it. Exercise the boundary directly on the private helper.
    rng = np.random.default_rng(0)
    points = rng.normal(size=(15, 3))
    assert _fit_plane_normal(points) is None

    # A frontal plane (z constant) of >=16 points fits to a +Z unit normal.
    flat = np.column_stack(
        [
            rng.uniform(-0.1, 0.1, size=16),
            rng.uniform(-0.1, 0.1, size=16),
            np.full(16, 0.42),
        ]
    )
    normal = _fit_plane_normal(flat)
    assert normal is not None
    assert math.isclose(float(np.linalg.norm(normal)), 1.0, rel_tol=1e-6)
    assert normal[2] > 0  # canonicalized to point toward the camera


def test_geometry_small_roi_under_16_points_has_no_normal() -> None:
    # M14: a tiny ROI yields fewer than 16 valid points, so no plane normal can
    # be fitted (angle is unknown) even though distance/ratio are fine.
    depth = np.full((10, 10), 420, dtype=np.uint16)
    intrinsics = _intrinsics(10, 10)
    roi = Roi(x=0.0, y=0.0, width=0.3, height=0.3)  # 3x3 px -> 9 points (<16)

    pointcloud, geometry = compute_geometry(depth, intrinsics, roi, QualityThresholds())

    assert pointcloud.roi_points_xyz_m.shape[0] < 16
    assert geometry.angle_deg is None
    assert geometry.normal_camera is None
    assert "normal_unknown" in geometry.warnings


def test_geometry_low_valid_ratio_warns() -> None:
    # M14: a sparse ROI (mostly zero depth) drops below min_depth_valid_ratio
    # and raises depth_valid_ratio_below_threshold.
    width, height = 40, 40
    depth = np.zeros((height, width), dtype=np.uint16)
    depth[18:23, 18:23] = 420  # 25 valid px out of 1600 -> ratio ~0.016
    intrinsics = _intrinsics(width, height)
    full_roi = Roi(x=0.0, y=0.0, width=1.0, height=1.0)
    thresholds = QualityThresholds()

    _, geometry = compute_geometry(depth, intrinsics, full_roi, thresholds)

    assert geometry.depth_valid_ratio < thresholds.min_depth_valid_ratio
    assert "depth_valid_ratio_below_threshold" in geometry.warnings


def test_geometry_bad_angle_warns_and_quality_marks_bad() -> None:
    # M14: a plane steeper than bad_angle_deg emits "angle_bad", and that exact
    # warning is what CaptureCoordinator._quality keys on to mark a sample BAD.
    width, height = 40, 40
    intrinsics = _intrinsics(width, height)
    full_roi = Roi(x=0.0, y=0.0, width=1.0, height=1.0)
    thresholds = QualityThresholds()
    depth = _tilted_plane_depth_mm(width, height, intrinsics, tilt_deg=75.0)

    _, geometry = compute_geometry(depth, intrinsics, full_roi, thresholds)

    assert geometry.angle_deg is not None
    assert geometry.angle_deg >= thresholds.bad_angle_deg
    assert "angle_bad" in geometry.warnings

    # Tie through _quality: build a coordinator shell with only the config the
    # method touches, and feed lightweight stubs for the unrelated inputs.
    coordinator = CaptureCoordinator.__new__(CaptureCoordinator)
    coordinator.config = default_config()
    h1_capture = SimpleNamespace(selected_attempt=SimpleNamespace(exposure_status="normal"))
    d455_snapshot = SimpleNamespace(imu={"available": False}, captured_at="t")
    quality = coordinator._quality(
        h1_capture=h1_capture,
        d455_snapshot=d455_snapshot,
        main_rgb_status=str(DeviceStatus.READY),
        geometry=geometry,
        storage_status={"status": QualityStatus.GOOD},
    )
    assert quality["status"] == QualityStatus.BAD
    assert "angle_bad" in quality["warnings"]
