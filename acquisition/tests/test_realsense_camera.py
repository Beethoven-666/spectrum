from __future__ import annotations

import numpy as np
import pytest

from spectrum_acq.devices.realsense import RealSenseD455Camera
from spectrum_acq.models import D455Profile, DeviceStatus


def make_camera(rs: "FakeRs", *, enable_imu: bool = False, frame_deadline_s: float = 3.0) -> RealSenseD455Camera:
    camera = RealSenseD455Camera.__new__(RealSenseD455Camera)
    camera.profile = D455Profile(color_width=3, color_height=2, depth_width=3, depth_height=2, enable_imu=enable_imu)
    camera.rs = rs
    camera.align = FakeAlign()
    camera._enable_imu = enable_imu
    camera._frame_timeout_ms = 1000
    camera._frame_deadline_s = frame_deadline_s
    camera.pipeline = None
    camera._pipeline_profile = None
    camera._depth_scale = None
    camera._imu_requested = enable_imu
    camera._imu_error = None
    camera._previous_imu_angles = None
    camera._latest_motion_frames = {}
    return camera


def test_open_enables_color_depth_only_without_imu() -> None:
    rs = FakeRs()
    rs.pipelines.append(FakePipeline())
    camera = make_camera(rs, enable_imu=False)

    camera.open()

    assert camera._pipeline_profile is not None
    assert rs.configs[-1].streams == ["depth", "color"]
    assert camera._imu_requested is False


def test_open_enables_imu_streams_when_requested() -> None:
    rs = FakeRs()
    rs.pipelines.append(FakePipeline())
    camera = make_camera(rs, enable_imu=True)

    camera.open()

    assert rs.configs[-1].streams == ["depth", "color", "accel", "gyro"]
    assert camera._imu_requested is True
    assert camera._imu_error is None


def test_open_falls_back_without_imu_when_start_raises() -> None:
    rs = FakeRs()
    rs.pipelines.append(FakePipeline(start_error=RuntimeError("imu unavailable")))
    rs.pipelines.append(FakePipeline())
    camera = make_camera(rs, enable_imu=True)

    camera.open()

    assert camera._imu_requested is False
    assert "imu unavailable" in (camera._imu_error or "")
    assert rs.configs[-1].streams == ["depth", "color"]


def test_read_returns_snapshot() -> None:
    rs = FakeRs()
    rs.pipelines.append(FakePipeline(frames=[FakeFrameSet()]))
    camera = make_camera(rs)
    camera.open()

    snapshot = camera.read()

    assert snapshot.status == DeviceStatus.READY
    assert snapshot.color_rgb.shape == (2, 3, 3)
    assert snapshot.depth_mm.tolist() == [[1000, 2000, 0], [1500, 2500, 3000]]


def test_read_reuses_motion_frame_until_color_depth_arrives() -> None:
    rs = FakeRs()
    rs.pipelines.append(
        FakePipeline(
            frames=[
                FakeFrameSet(color=False, depth=False, accel=(0.0, 0.0, 9.81)),
                FakeFrameSet(),
            ]
        )
    )
    camera = make_camera(rs, enable_imu=True)
    camera.open()

    snapshot = camera.read()

    assert snapshot.imu["available"] is True
    assert snapshot.imu["accel_xyz"] == [0.0, 0.0, 9.81]
    assert snapshot.imu["roll_deg"] == 0.0
    assert snapshot.imu["pitch_deg"] == -0.0


def test_read_raises_when_color_depth_never_arrive() -> None:
    rs = FakeRs()
    rs.pipelines.append(FakePipeline(frames=[FakeFrameSet(color=False, depth=False)]))
    camera = make_camera(rs, frame_deadline_s=0.0)
    camera.open()

    with pytest.raises(RuntimeError):
        camera.read()


def test_close_stops_pipeline() -> None:
    rs = FakeRs()
    pipeline = FakePipeline()
    rs.pipelines.append(pipeline)
    camera = make_camera(rs)
    camera.open()
    assert pipeline.started is True

    camera.close()

    assert camera._pipeline_profile is None
    assert pipeline.stop_calls == 1
    assert pipeline.started is False


def test_describe_reports_missing_and_ready() -> None:
    missing = make_camera(FakeRs(devices=[]))
    assert missing.describe()["status"] == DeviceStatus.MISSING

    present = make_camera(FakeRs(devices=[FakeDevice()]))
    described = present.describe()
    assert described["status"] == DeviceStatus.READY
    assert described["serial"] == "fake-serial_number"


class FakeRs:
    def __init__(self, devices: list["FakeDevice"] | None = None) -> None:
        self.pipelines: list[FakePipeline] = []
        self.configs: list[FakeConfig] = []
        self.devices = devices if devices is not None else [FakeDevice()]

    class stream:
        depth = "depth"
        color = "color"
        accel = "accel"
        gyro = "gyro"

    class format:
        z16 = "z16"
        rgb8 = "rgb8"

    class camera_info:
        name = "name"
        serial_number = "serial_number"
        firmware_version = "firmware_version"

    def pipeline(self) -> "FakePipeline":
        return self.pipelines.pop(0)

    def config(self) -> "FakeConfig":
        cfg = FakeConfig()
        self.configs.append(cfg)
        return cfg

    def context(self) -> "FakeContext":
        return FakeContext(self.devices)


class FakeContext:
    def __init__(self, devices: list["FakeDevice"]) -> None:
        self._devices = devices

    def query_devices(self) -> list["FakeDevice"]:
        return self._devices


class FakeConfig:
    def __init__(self) -> None:
        self.streams: list[str] = []

    def enable_stream(self, *args: object) -> None:
        self.streams.append(str(args[0]))


class FakePipeline:
    def __init__(
        self,
        *,
        started: bool = False,
        frames: list["FakeFrameSet"] | None = None,
        start_error: BaseException | None = None,
    ) -> None:
        self.started = started
        self.start_calls = 0
        self.stop_calls = 0
        self.frames = list(frames) if frames is not None else []
        self.start_error = start_error

    def start(self, config: FakeConfig) -> "FakePipelineProfile":
        self.start_calls += 1
        if self.start_error is not None:
            raise self.start_error
        self.started = True
        return FakePipelineProfile()

    def stop(self) -> None:
        self.stop_calls += 1
        if not self.started:
            raise RuntimeError("stop cannot be called before start()")
        self.started = False

    def wait_for_frames(self, timeout_ms: int) -> "FakeFrameSet":
        if not self.started:
            raise RuntimeError("wait_for_frames cannot be called before start()")
        if self.frames:
            return self.frames.pop(0)
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
    def __init__(
        self,
        *,
        color: bool = True,
        depth: bool = True,
        accel: tuple[float, float, float] | None = None,
        gyro: tuple[float, float, float] | None = None,
    ) -> None:
        self._color = color
        self._depth = depth
        self._motion = {"accel": accel, "gyro": gyro}

    def get_color_frame(self) -> "FakeFrame | None":
        if not self._color:
            return None
        return FakeFrame(np.zeros((2, 3, 3), dtype=np.uint8))

    def get_depth_frame(self) -> "FakeFrame | None":
        if not self._depth:
            return None
        return FakeFrame(np.array([[1000, 2000, 0], [1500, 2500, 3000]], dtype=np.uint16))

    def first_or_default(self, stream: object) -> "FakeMotionFrame | None":
        motion = self._motion.get(str(stream))
        if motion is None:
            return None
        return FakeMotionFrame(motion)


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


class FakeMotionFrame:
    def __init__(self, xyz: tuple[float, float, float]) -> None:
        self._xyz = xyz

    def as_motion_frame(self) -> "FakeMotionFrame":
        return self

    def get_motion_data(self) -> "FakeMotionData":
        return FakeMotionData(*self._xyz)

    def get_timestamp(self) -> float:
        return 123.0


class FakeMotionData:
    def __init__(self, x: float, y: float, z: float) -> None:
        self.x = x
        self.y = y
        self.z = z


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
