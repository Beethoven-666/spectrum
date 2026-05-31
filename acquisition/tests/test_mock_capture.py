from __future__ import annotations

import json
from pathlib import Path

import pytest

from spectrum_acq.capture import create_mock_coordinator
from spectrum_acq.capture.coordinator import CaptureCoordinator
from spectrum_acq.config import default_config
from spectrum_acq.devices.mock import MockD455Camera, MockH1Spectrometer, NullMainRgbProvider
from spectrum_acq.models import H1AutoExposureConfig, QualityStatus
from spectrum_acq.storage import SampleStore


def test_mock_capture_writes_complete_sample(tmp_path: Path) -> None:
    coordinator = create_mock_coordinator(tmp_path / "data")

    result = coordinator.capture()

    sample_path = Path(result.sample_path)
    assert sample_path.exists()
    assert result.quality_status in {QualityStatus.GOOD, QualityStatus.WARN, QualityStatus.BAD}

    expected_files = [
        "metadata.json",
        "quality.json",
        "h1/spectrum.json",
        "h1/spectrum.csv",
        "h1/exposure_attempts.json",
        "d455/color.jpg",
        "d455/depth.png",
        "d455/depth.npy",
        "d455/imu.json",
        "d455/pointcloud_full.ply",
        "d455/pointcloud_roi.ply",
        "main_rgb/status.json",
        "roi/roi.json",
        "roi/preview.jpg",
    ]
    for rel in expected_files:
        assert (sample_path / rel).exists(), rel

    metadata = json.loads((sample_path / "metadata.json").read_text())
    quality = json.loads((sample_path / "quality.json").read_text())
    assert metadata["schema_version"] == "leaf-multimodal-sample/v1"
    assert metadata["devices"]["main_rgb"]["status"] == "missing"
    assert metadata["calibration"]["status"] == "uncalibrated"
    assert quality["h1"]["exposure_status"] == "normal"

    rows = coordinator.store.list_samples()
    assert len(rows) == 1
    assert rows[0]["id"] == result.sample_id


def test_sample_export_zip(tmp_path: Path) -> None:
    coordinator = create_mock_coordinator(tmp_path / "data")
    result = coordinator.capture()

    archive = coordinator.store.export_sample_zip(result.sample_id)
    filtered = coordinator.store.export_filtered_zip(quality_status="warn")

    assert archive.exists()
    assert archive.suffix == ".zip"
    assert filtered.exists()
    assert filtered.suffix == ".zip"


def test_sqlite_index_rebuilds_from_sample_directories(tmp_path: Path) -> None:
    coordinator = create_mock_coordinator(tmp_path / "data")
    result = coordinator.capture()
    coordinator.store.index.db_path.unlink()

    count = coordinator.store.rebuild_index()

    assert count == 1
    assert coordinator.store.get_sample(result.sample_id)["id"] == result.sample_id


def test_strict_h1_exposure_failure_does_not_index_sample(tmp_path: Path) -> None:
    base = default_config(tmp_path / "data")
    config = type(base)(
        **{
            **base.__dict__,
            "h1_auto_exposure": H1AutoExposureConfig(mode="strict", max_attempts=2),
        }
    )
    coordinator = CaptureCoordinator(
        config=config,
        h1=MockH1Spectrometer(scenario="always_under"),
        d455=MockD455Camera(),
        main_rgb=NullMainRgbProvider(),
        store=SampleStore(config),
    )

    with pytest.raises(RuntimeError, match="H1 strict exposure failed"):
        coordinator.capture()

    assert coordinator.store.list_samples() == []
