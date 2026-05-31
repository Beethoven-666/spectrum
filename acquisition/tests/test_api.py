from __future__ import annotations

from dataclasses import replace
from pathlib import Path

from fastapi.testclient import TestClient

from spectrum_acq.api import create_app
from spectrum_acq.config import default_config
from spectrum_acq.models import DiskThresholds


def test_api_mock_capture_roundtrip(tmp_path: Path) -> None:
    app = create_app(default_config(tmp_path / "data"))
    client = TestClient(app)

    health = client.get("/health")
    assert health.status_code == 200
    assert health.json()["ok"] is True

    devices = client.get("/devices")
    assert devices.status_code == 200
    assert devices.json()["h1"]["status"] == "ready"

    capture = client.post("/capture")
    assert capture.status_code == 200
    sample_id = capture.json()["sample_id"]

    samples = client.get("/samples")
    assert samples.status_code == 200
    assert samples.json()["samples"][0]["id"] == sample_id

    detail = client.get(f"/samples/{sample_id}")
    assert detail.status_code == 200
    assert detail.json()["metadata"]["sample_id"] == sample_id

    download = client.get(f"/samples/{sample_id}/download")
    assert download.status_code == 200
    assert download.headers["content-type"] == "application/zip"

    preview = client.get(f"/samples/{sample_id}/preview")
    assert preview.status_code == 200
    assert preview.headers["content-type"] == "image/jpeg"

    color = client.get(f"/samples/{sample_id}/files/d455/color.jpg")
    assert color.status_code == 200
    assert color.headers["content-type"] == "image/jpeg"

    depth = client.get(f"/samples/{sample_id}/files/d455/depth.png")
    assert depth.status_code == 200
    assert depth.headers["content-type"] == "image/png"

    spectrum = client.get(f"/samples/{sample_id}/files/h1/spectrum.json")
    assert spectrum.status_code == 200
    assert spectrum.headers["content-type"] == "application/json"
    assert "wavelengths" in spectrum.json()

    blocked = client.get(f"/samples/{sample_id}/files/metadata.json")
    assert blocked.status_code == 404

    missing = client.get("/samples/not-a-sample/files/d455/color.jpg")
    assert missing.status_code == 404


def test_h1_stream_sse_uses_acquisition_device(tmp_path: Path) -> None:
    app = create_app(default_config(tmp_path / "data"))
    client = TestClient(app)

    with client.stream("GET", "/h1/stream?max_frames=2") as response:
        assert response.status_code == 200
        body = "".join(response.iter_text())

    assert "event: frame" in body
    assert '"wavelengthStart": 340' in body
    assert '"rawSpectrum":' in body


def test_config_and_calibration_affect_next_sample(tmp_path: Path) -> None:
    app = create_app(default_config(tmp_path / "data"))
    client = TestClient(app)

    config_update = client.put(
        "/config",
        json={
            "roi": {"x": 0.1, "y": 0.2, "width": 0.3, "height": 0.4, "source": "manual"},
            "h1_auto_exposure": {"mode": "strict"},
        },
    )
    assert config_update.status_code == 200
    assert config_update.json()["restart_required"] is False
    assert client.get("/config").json()["roi"]["source"] == "manual"

    calibration = client.put(
        "/calibration",
        json={"version": "bench-v1", "notes": "mock alignment"},
    )
    assert calibration.status_code == 200
    assert calibration.json()["version"] == "bench-v1"

    capture = client.post("/capture")
    assert capture.status_code == 200
    sample_id = capture.json()["sample_id"]
    detail = client.get(f"/samples/{sample_id}").json()
    assert detail["metadata"]["roi"]["source"] == "manual"
    assert detail["metadata"]["calibration"]["version"] == "bench-v1"


def test_low_disk_blocks_capture(tmp_path: Path) -> None:
    base = default_config(tmp_path / "data")
    disk = DiskThresholds(
        warn_free_bytes=base.disk.warn_free_bytes,
        stop_free_bytes=10**18,
        allow_below_stop=False,
    )
    app = create_app(replace(base, disk=disk))
    client = TestClient(app)

    capture = client.post("/capture")

    assert capture.status_code == 400
    assert capture.json()["detail"] == "low disk space"


def test_disk_warning_status_is_reported(tmp_path: Path) -> None:
    base = default_config(tmp_path / "data")
    disk = DiskThresholds(
        warn_free_bytes=10**18,
        stop_free_bytes=0,
        allow_below_stop=False,
    )
    app = create_app(replace(base, disk=disk))
    client = TestClient(app)

    storage = client.get("/storage")

    assert storage.status_code == 200
    assert storage.json()["status"] == "warn"
