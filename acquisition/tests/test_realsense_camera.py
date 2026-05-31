from __future__ import annotations

from threading import Lock

import numpy as np

from spectrum_acq.devices.realsense import RealSenseD455Camera
from spectrum_acq.models import D455Profile, DeviceStatus


def test_snapshot_recovers_when_pipeline_profile_is_stale() -> None:
    rs = FakeRs()
    replacement = FakePipeline()
    rs.pipelines.append(replacement)
    camera = RealSenseD455Camera.__new__(RealSenseD455Camera)
    camera.profile = D455Profile(color_width=3, color_height=2, depth_width=3, depth_height=2)
    camera.rs = rs
    camera.pipeline = FakePipeline(started=False)
    camera.align = FakeAlign()
    camera._pipeline_profile = FakePipelineProfile()
    camera._depth_scale = 0.001
    camera._imu_requested = False
    camera._imu_error = None
    camera._lock = Lock()

    snapshot = camera.snapshot()

    assert snapshot.status == DeviceStatus.READY
    assert snapshot.color_rgb.shape == (2, 3, 3)
    assert snapshot.depth_mm.tolist() == [[1000, 2000, 0], [1500, 2500, 3000]]
    assert camera.pipeline is replacement
    assert replacement.start_calls == 1


class FakeRs:
    def __init__(self) -> None:
        self.pipelines: list[FakePipeline] = []

    class stream:
        depth = "depth"
        color = "color"
        accel = "accel"
        gyro = "gyro"

    class format:
        z16 = "z16"
        rgb8 = "rgb8"

    class camera_info:
        serial_number = "serial_number"
        firmware_version = "firmware_version"

    def pipeline(self) -> "FakePipeline":
        return self.pipelines.pop(0)

    def config(self) -> "FakeConfig":
        return FakeConfig()


class FakeConfig:
    def enable_stream(self, *args: object) -> None:
        pass


class FakePipeline:
    def __init__(self, *, started: bool = True) -> None:
        self.started = started
        self.start_calls = 0

    def start(self, config: FakeConfig) -> "FakePipelineProfile":
        self.started = True
        self.start_calls += 1
        return FakePipelineProfile()

    def stop(self) -> None:
        if not self.started:
            raise RuntimeError("stop cannot be called before start()")
        self.started = False

    def wait_for_frames(self, timeout_ms: int) -> "FakeFrameSet":
        if not self.started:
            raise RuntimeError("wait_for_frames cannot be called before start()")
        return FakeFrameSet()


class FakePipelineProfile:
    def get_device(self) -> "FakeDevice":
        return FakeDevice()


class FakeDevice:
    def supports(self, key: object) -> bool:
        return True

    def get_info(self, key: object) -> str:
        return f"fake-{key}"

    def first_depth_sensor(self) -> "FakeDepthSensor":
        return FakeDepthSensor()


class FakeDepthSensor:
    def get_depth_scale(self) -> float:
        return 0.001


class FakeAlign:
    def process(self, frames: "FakeFrameSet") -> "FakeFrameSet":
        return frames


class FakeFrameSet:
    def get_color_frame(self) -> "FakeFrame":
        return FakeFrame(np.zeros((2, 3, 3), dtype=np.uint8))

    def get_depth_frame(self) -> "FakeFrame":
        return FakeFrame(np.array([[1000, 2000, 0], [1500, 2500, 3000]], dtype=np.uint16))

    def first_or_default(self, stream: object) -> None:
        return None


class FakeFrame:
    def __init__(self, data: np.ndarray) -> None:
        self._data = data
        self.profile = FakeVideoProfile(data)

    def get_data(self) -> np.ndarray:
        return self._data

    def get_width(self) -> int:
        return int(self._data.shape[1])

    def get_height(self) -> int:
        return int(self._data.shape[0])


class FakeVideoProfile:
    def __init__(self, data: np.ndarray) -> None:
        self._data = data

    def as_video_stream_profile(self) -> "FakeVideoProfile":
        return self

    @property
    def intrinsics(self) -> "FakeIntrinsics":
        return FakeIntrinsics(self._data)


class FakeIntrinsics:
    def __init__(self, data: np.ndarray) -> None:
        self.width = int(data.shape[1])
        self.height = int(data.shape[0])
        self.fx = 1.0
        self.fy = 1.0
        self.ppx = 0.5
        self.ppy = 0.5
        self.model = "fake"
        self.coeffs = [0.0, 0.0, 0.0, 0.0, 0.0]
