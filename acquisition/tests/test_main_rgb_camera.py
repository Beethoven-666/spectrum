from __future__ import annotations

import io
from pathlib import Path
from unittest.mock import patch

import pytest
from PIL import Image

from spectrum_acq.devices.main_rgb import (
    V4l2MainRgbCamera,
    _decode_mjpeg,
    discover_main_rgb_device,
    iter_complete_frames,
)
from spectrum_acq.models import DeviceStatus, MainRgbProfile


def _jpeg(width: int, height: int, color: tuple[int, int, int] = (10, 20, 30)) -> bytes:
    buf = io.BytesIO()
    Image.new("RGB", (width, height), color=color).save(buf, format="JPEG")
    return buf.getvalue()


class _FakeStdout:
    def __init__(self, chunks: list[bytes]) -> None:
        self._chunks = list(chunks)

    def read(self, _n: int) -> bytes:
        return self._chunks.pop(0) if self._chunks else b""


class _FakeProc:
    def __init__(self, chunks: list[bytes]) -> None:
        self.stdout = _FakeStdout(chunks)


def test_decode_mjpeg_roundtrip() -> None:
    source = Image.new("RGB", (4, 3), color=(10, 20, 30))
    buf = io.BytesIO()
    source.save(buf, format="JPEG")
    arr = _decode_mjpeg(buf.getvalue())
    assert arr.shape == (3, 4, 3)
    assert arr[1, 2].tolist() == [10, 20, 30]


def test_discover_prefers_sonix_by_id(tmp_path: Path) -> None:
    by_id = tmp_path / "by-id"
    by_id.mkdir()
    realsense = by_id / "usb-Intel_R__RealSense_TM__Depth_Camera_455f-video-index0"
    sonix = by_id / "usb-Sonix_Technology_Co.__Ltd._USB_2.0_Camera-video-index0"
    other = by_id / "usb-Example_Webcam-video-index0"
    for link, target in [
        (realsense, tmp_path / "video0"),
        (sonix, tmp_path / "video4"),
        (other, tmp_path / "video5"),
    ]:
        target.touch()
        link.symlink_to(target)

    discovered = discover_main_rgb_device(by_id_dir=by_id)

    assert discovered == str(sonix)


def test_capture_returns_ready_frame(tmp_path: Path) -> None:
    jpeg = io.BytesIO()
    Image.new("RGB", (8, 6), color=(1, 2, 3)).save(jpeg, format="JPEG")
    fake_jpg = tmp_path / "frame.jpg"
    fake_jpg.write_bytes(jpeg.getvalue())

    camera = V4l2MainRgbCamera(
        MainRgbProfile(device_path="/dev/video-test", width=8, height=6, pixel_format="MJPG")
    )

    def fake_stream(device: str, *, width: int, height: int, pixel_format: str, timeout_s: float) -> bytes:
        assert device == "/dev/video-test"
        assert width == 8 and height == 6 and pixel_format == "MJPG"
        return fake_jpg.read_bytes()

    with (
        patch.object(camera, "_device_path", return_value="/dev/video-test"),
        patch("spectrum_acq.devices.main_rgb.shutil.which", return_value="/usr/bin/v4l2-ctl"),
        patch("spectrum_acq.devices.main_rgb._stream_mjpeg", side_effect=fake_stream),
    ):
        capture = camera.capture()

    assert capture.status == DeviceStatus.READY
    assert capture.image_rgb is not None
    assert capture.image_rgb.shape == (6, 8, 3)
    assert capture.metadata["driver"] == "v4l2"


def test_capture_missing_device() -> None:
    camera = V4l2MainRgbCamera(MainRgbProfile(device_path="/dev/does-not-exist"))
    capture = camera.capture()
    assert capture.status == DeviceStatus.MISSING
    assert capture.image_rgb is None


def test_iter_complete_frames_splits_and_keeps_partial() -> None:
    jpeg1 = _jpeg(4, 4)
    jpeg2 = _jpeg(8, 8)
    buf = bytearray(b"\x00\x01junk" + jpeg1 + jpeg2 + b"\xff\xd8partial")
    frames = list(iter_complete_frames(buf))
    assert frames == [jpeg1, jpeg2]
    assert bytes(buf) == b"\xff\xd8partial"  # incomplete trailing frame retained


def test_iter_complete_frames_reassembles_across_chunks() -> None:
    jpeg = _jpeg(4, 4)
    buf = bytearray(jpeg[:5])
    assert list(iter_complete_frames(buf)) == []  # not finished yet
    buf += jpeg[5:]
    assert list(iter_complete_frames(buf)) == [jpeg]


def test_persistent_read_returns_freshest_frame() -> None:
    camera = V4l2MainRgbCamera(MainRgbProfile(device_path="/dev/video-test", mode="persistent"))
    camera._proc = _FakeProc([_jpeg(4, 4) + _jpeg(8, 8)])  # two frames in one chunk
    camera._buf = bytearray()

    capture = camera.read()

    assert capture.status == DeviceStatus.READY
    assert capture.image_rgb.shape == (8, 8, 3)  # freshest frame, older one dropped
    assert capture.metadata["mode"] == "persistent"


def test_persistent_read_skips_corrupt_latest_frame() -> None:
    camera = V4l2MainRgbCamera(MainRgbProfile(device_path="/dev/video-test", mode="persistent"))
    camera._proc = _FakeProc([_jpeg(4, 4), b"\xff\xd8\xff\xd9", _jpeg(8, 8)])
    camera._buf = bytearray()

    first = camera.read()
    second = camera.read()

    assert first.image_rgb.shape == (4, 4, 3)
    assert second.image_rgb.shape == (8, 8, 3)
    assert camera.decode_failures == 1


def test_persistent_read_raises_on_stream_end() -> None:
    camera = V4l2MainRgbCamera(MainRgbProfile(device_path="/dev/video-test", mode="persistent"))
    camera._proc = _FakeProc([])  # stdout immediately EOF
    camera._buf = bytearray()

    with pytest.raises(RuntimeError):
        camera.read()
