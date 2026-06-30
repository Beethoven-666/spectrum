"""Regression: a main RGB frame must not crash the capture write.

The main RGB camera is intermittent (USB stall) — most captures see it MISSING
(``image_rgb=None``). But the moment it delivers a frame, ``MainRgbCapture`` carries
an ``np.ndarray`` image. Writing the sample used to ``json.dump`` the whole capture
into ``main_rgb/status.json``; ``to_jsonable`` didn't handle numpy, so the capture
500'd with "Object of type ndarray is not JSON serializable". Now (1) ``to_jsonable``
converts numpy and (2) ``status.json`` carries status+metadata only, not the frame.
"""

from __future__ import annotations

import json
from pathlib import Path

import numpy as np

from spectrum_acq.capture.coordinator import (
    CaptureCoordinator,
    build_d455_stream,
)
from spectrum_acq.config import default_config
from spectrum_acq.devices.interfaces import MainRgbCapture
from spectrum_acq.devices.mock import MockH1Spectrometer
from spectrum_acq.devices.streaming import DirectStream
from spectrum_acq.models import DeviceStatus, to_jsonable, utc_now_iso
from spectrum_acq.storage import SampleStore


def test_to_jsonable_converts_numpy() -> None:
    payload = {
        "arr": np.arange(6, dtype=np.int64).reshape(2, 3),
        "f32": np.float32(1.5),
        "i32": np.int32(7),
        "b": np.bool_(True),
        "nan": np.float64("nan"),  # must become null, not NaN
    }
    out = to_jsonable(payload)
    # Round-trips through strict JSON (no NaN/ndarray) without raising.
    text = json.dumps(out, allow_nan=False)
    assert json.loads(text) == {
        "arr": [[0, 1, 2], [3, 4, 5]],
        "f32": 1.5,
        "i32": 7,
        "b": True,
        "nan": None,
    }


def _image_main_rgb() -> DirectStream:
    capture = MainRgbCapture(
        status=DeviceStatus.READY,
        captured_at=utc_now_iso(),
        image_rgb=np.zeros((8, 8, 3), dtype=np.uint8),
        metadata={"driver": "v4l2", "width": 8, "height": 8},
    )
    return DirectStream(read=lambda: capture, status=lambda: {"status": "ready"})


def test_capture_with_main_rgb_frame_writes_sample(tmp_path: Path) -> None:
    config = default_config(tmp_path / "data")
    coordinator = CaptureCoordinator(
        config=config,
        h1=MockH1Spectrometer(scenario="normal"),
        d455=build_d455_stream(config),
        main_rgb=_image_main_rgb(),
        store=SampleStore(config),
    )

    result = coordinator.capture()  # used to 500 with ndarray-not-serializable
    root = Path(result.sample_path)

    # The image is saved as a JPEG, and status.json stays lean (no raw frame).
    assert (root / "main_rgb" / "color.jpg").exists()
    status = json.loads((root / "main_rgb" / "status.json").read_text())
    assert status["status"] == "ready"
    assert status["has_image"] is True
    assert "image_rgb" not in status  # the 640x480x3 array must NOT be embedded
    assert status["metadata"]["width"] == 8
