from __future__ import annotations

import numpy as np

from spectrum_acq.geometry import compute_geometry
from spectrum_acq.models import QualityThresholds, Roi


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
