"""PLY point-cloud writer."""

from __future__ import annotations

from pathlib import Path

import numpy as np


def write_ascii_ply(path: Path, points_xyz_m: np.ndarray) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("w", encoding="ascii") as f:
        f.write("ply\n")
        f.write("format ascii 1.0\n")
        f.write(f"element vertex {points_xyz_m.shape[0]}\n")
        f.write("property float x\n")
        f.write("property float y\n")
        f.write("property float z\n")
        f.write("end_header\n")
        for x, y, z in points_xyz_m:
            f.write(f"{x:.6f} {y:.6f} {z:.6f}\n")
