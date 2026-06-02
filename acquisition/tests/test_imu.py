"""IMU roll/pitch (atan2) and two-read motion-delta coverage (M15).

The roll/pitch math and the per-read delta tracking live inline in
``RealSenseD455Camera.read`` (realsense.py ~111-122), so these tests drive the
real ``read`` path with the existing fake ``pyrealsense2`` harness instead of a
private helper. The "motion warn" decision itself lives in
``CaptureCoordinator._quality``; the final test wires a real two-read delta into
that method to confirm the threshold crossing surfaces as ``imu_motion_warn``.
"""

from __future__ import annotations

import math
from types import SimpleNamespace

# Reuse the in-tree fake librealsense harness (FakeRs / FakePipeline /
# FakeFrameSet / make_camera) rather than duplicating it here.
from test_realsense_camera import FakePipeline, FakeFrameSet, FakeRs, make_camera

from spectrum_acq.capture.coordinator import CaptureCoordinator
from spectrum_acq.config import default_config
from spectrum_acq.geometry.pointcloud import GeometryResult
from spectrum_acq.models import DeviceStatus, QualityStatus


def _single_read(accel: tuple[float, float, float]):
    rs = FakeRs()
    rs.pipelines.append(FakePipeline(frames=[FakeFrameSet(accel=accel)]))
    camera = make_camera(rs, enable_imu=True)
    camera.open()
    return camera.read()


def test_imu_roll_pitch_from_tilt_vector() -> None:
    # M15: a non-zero accel vector must give roll = atan2(ay, az) and
    # pitch = atan2(-ax, sqrt(ay^2 + az^2)). The -ax sign and the az-vs-ay axis
    # ordering are the easy-to-flip parts, so pick ax, ay, az all distinct.
    ax, ay, az = 1.0, 2.0, 9.0
    snapshot = _single_read((ax, ay, az))
    imu = snapshot.imu

    assert imu["available"] is True
    assert imu["accel_xyz"] == [ax, ay, az]
    assert math.isclose(imu["roll_deg"], math.degrees(math.atan2(ay, az)), rel_tol=1e-9)
    assert math.isclose(
        imu["pitch_deg"],
        math.degrees(math.atan2(-ax, math.sqrt(ay * ay + az * az))),
        rel_tol=1e-9,
    )


def test_imu_pitch_sign_follows_negative_ax() -> None:
    # M15: pitch carries the -ax sign — a positive forward tilt (ax > 0) must
    # produce a negative pitch, and flipping ax flips the sign symmetrically.
    pos = _single_read((1.0, 0.0, 9.81)).imu
    neg = _single_read((-1.0, 0.0, 9.81)).imu

    assert pos["pitch_deg"] < 0.0
    assert neg["pitch_deg"] > 0.0
    assert math.isclose(pos["pitch_deg"], -neg["pitch_deg"], rel_tol=1e-9)
    # Pure forward/back tilt with ay == 0 leaves roll at zero.
    assert math.isclose(pos["roll_deg"], 0.0, abs_tol=1e-9)


def test_imu_first_read_has_zero_delta() -> None:
    # M15: the first read has no prior angles, so the reported deltas are 0.0,
    # not the absolute angle.
    imu = _single_read((0.0, 5.0, 9.81)).imu
    assert imu["roll_deg"] != 0.0  # there *is* a tilt...
    assert imu["delta_roll_deg"] == 0.0  # ...but the first-read delta is zeroed
    assert imu["delta_pitch_deg"] == 0.0


def test_imu_two_read_delta_crosses_threshold_triggers_motion_warn() -> None:
    # M15: two reads from one streaming session, the second tilted far enough
    # that |delta_roll| exceeds max_imu_delta_deg. The delta is computed across
    # reads (previous angles persist on the camera), and feeding the second
    # snapshot into _quality must yield "imu_motion_warn".
    rs = FakeRs()
    rs.pipelines.append(
        FakePipeline(
            frames=[
                FakeFrameSet(accel=(0.0, 0.0, 9.81)),  # level: roll ~ 0
                FakeFrameSet(accel=(0.0, 5.0, 9.81)),  # tilted: roll ~ 27 deg
            ]
        )
    )
    camera = make_camera(rs, enable_imu=True)
    camera.open()

    first = camera.read()
    second = camera.read()

    config = default_config()
    threshold = config.quality.max_imu_delta_deg
    assert math.isclose(first.imu["roll_deg"], 0.0, abs_tol=1e-9)
    # The second read's delta is measured against the first read's angle.
    expected_delta = second.imu["roll_deg"] - first.imu["roll_deg"]
    assert math.isclose(second.imu["delta_roll_deg"], expected_delta, rel_tol=1e-9)
    assert abs(second.imu["delta_roll_deg"]) > threshold

    coordinator = CaptureCoordinator.__new__(CaptureCoordinator)
    coordinator.config = config
    h1_capture = SimpleNamespace(selected_attempt=SimpleNamespace(exposure_status="normal"))
    geometry = GeometryResult(
        distance_mm=300.0,
        depth_valid_ratio=0.9,
        normal_camera=[0.0, 0.0, 1.0],
        angle_deg=2.0,
        status="ok",
        warnings=[],
    )
    quality = coordinator._quality(
        h1_capture=h1_capture,
        d455_snapshot=second,
        main_rgb_status=str(DeviceStatus.READY),
        geometry=geometry,
        storage_status={"status": QualityStatus.GOOD},
    )

    assert "imu_motion_warn" in quality["warnings"]
    assert quality["status"] == QualityStatus.WARN


def test_imu_small_delta_does_not_trigger_motion_warn() -> None:
    # M15 (negative control): a sub-threshold tilt change must NOT warn, so the
    # warning is genuinely tied to the threshold crossing and not always set.
    rs = FakeRs()
    rs.pipelines.append(
        FakePipeline(
            frames=[
                FakeFrameSet(accel=(0.0, 0.0, 9.81)),
                FakeFrameSet(accel=(0.0, 0.2, 9.81)),  # ~1.2 deg roll, well under 8
            ]
        )
    )
    camera = make_camera(rs, enable_imu=True)
    camera.open()
    camera.read()
    second = camera.read()

    config = default_config()
    assert abs(second.imu["delta_roll_deg"]) < config.quality.max_imu_delta_deg

    coordinator = CaptureCoordinator.__new__(CaptureCoordinator)
    coordinator.config = config
    h1_capture = SimpleNamespace(selected_attempt=SimpleNamespace(exposure_status="normal"))
    geometry = GeometryResult(
        distance_mm=300.0,
        depth_valid_ratio=0.9,
        normal_camera=[0.0, 0.0, 1.0],
        angle_deg=2.0,
        status="ok",
        warnings=[],
    )
    quality = coordinator._quality(
        h1_capture=h1_capture,
        d455_snapshot=second,
        main_rgb_status=str(DeviceStatus.READY),
        geometry=geometry,
        storage_status={"status": QualityStatus.GOOD},
    )

    assert "imu_motion_warn" not in quality["warnings"]
    assert quality["status"] == QualityStatus.GOOD
