"""Regression tests for SampleIndex.rebuild() resilience (M6/M13).

A truncated/corrupt metadata.json or a sample directory missing its
quality.json must NOT abort the whole rebuild or empty the index — the bad
directories are skipped (and logged) while every good sample is indexed
atomically.
"""

from __future__ import annotations

import json
from pathlib import Path

from spectrum_acq.storage.sqlite_index import SampleIndex


def _write_sample(sample_dir: Path, sample_id: str) -> None:
    """Create a fully valid sample directory (metadata.json + quality.json)."""
    sample_dir.mkdir(parents=True, exist_ok=True)
    metadata = {
        "sample_id": sample_id,
        "created_at": "2026-06-02T00:00:00Z",
        "schema_version": "leaf-multimodal-sample/v1",
        "devices": {
            "h1": {"serial_number": "H1-123"},
            "d455": {"serial": "D455-456"},
            "main_rgb": {"status": "missing"},
        },
        "calibration": {"version": "cal-v1"},
        "config": {"profile": "default"},
    }
    quality = {
        "status": "good",
        "geometry": {"distance_mm": 100.0, "angle_deg": 5.0},
        "h1": {"exposure_status": "normal"},
        "warnings": [],
    }
    (sample_dir / "metadata.json").write_text(json.dumps(metadata), encoding="utf-8")
    (sample_dir / "quality.json").write_text(json.dumps(quality), encoding="utf-8")


def test_rebuild_skips_bad_dirs_and_keeps_valid(tmp_path: Path) -> None:
    samples_dir = tmp_path / "samples"
    samples_dir.mkdir()

    # 1) A valid sample.
    _write_sample(samples_dir / "good_sample", "good_sample")

    # 2) A sample whose metadata.json is truncated (invalid JSON).
    truncated = samples_dir / "truncated_sample"
    truncated.mkdir()
    (truncated / "metadata.json").write_text('{"sample_id": "trunc", "created_', encoding="utf-8")
    (truncated / "quality.json").write_text(json.dumps({"status": "good"}), encoding="utf-8")

    # 3) A sample missing quality.json entirely.
    missing_quality = samples_dir / "missing_quality_sample"
    missing_quality.mkdir()
    (missing_quality / "metadata.json").write_text(
        json.dumps(
            {
                "sample_id": "missing_q",
                "created_at": "2026-06-02T00:00:00Z",
                "schema_version": "leaf-multimodal-sample/v1",
            }
        ),
        encoding="utf-8",
    )

    index = SampleIndex(tmp_path / "index" / "samples.sqlite3")
    indexed = index.rebuild(samples_dir)

    # Only the valid sample is indexed; the two bad dirs are skipped.
    assert indexed == 1
    rows = index.list_samples()
    assert [row["id"] for row in rows] == ["good_sample"]
    assert index.get_sample("good_sample") is not None
    assert index.get_sample("trunc") is None
    assert index.get_sample("missing_q") is None


def test_rebuild_does_not_empty_index_when_a_dir_is_bad(tmp_path: Path) -> None:
    """A bad directory encountered during rebuild must not wipe good rows.

    Seed the index, then rebuild a directory set that contains one valid and one
    corrupt sample; the valid sample must survive and the corrupt one is skipped.
    """
    samples_dir = tmp_path / "samples"
    samples_dir.mkdir()
    _write_sample(samples_dir / "keep_me", "keep_me")

    index = SampleIndex(tmp_path / "index" / "samples.sqlite3")
    # Pre-seed via a normal rebuild so the table starts non-empty.
    assert index.rebuild(samples_dir) == 1

    # Now add a corrupt sibling and rebuild again.
    corrupt = samples_dir / "corrupt"
    corrupt.mkdir()
    (corrupt / "metadata.json").write_text("not json at all", encoding="utf-8")
    (corrupt / "quality.json").write_text("{}", encoding="utf-8")

    indexed = index.rebuild(samples_dir)
    assert indexed == 1
    assert index.get_sample("keep_me") is not None
    # Index is not emptied and the rebuild did not raise.
    assert len(index.list_samples()) == 1


def test_rebuild_handles_missing_required_key(tmp_path: Path) -> None:
    """metadata.json that parses but lacks a required key (KeyError) is skipped."""
    samples_dir = tmp_path / "samples"
    samples_dir.mkdir()
    _write_sample(samples_dir / "good_sample", "good_sample")

    no_id = samples_dir / "no_sample_id"
    no_id.mkdir()
    (no_id / "metadata.json").write_text(
        json.dumps({"created_at": "x", "schema_version": "v1"}),  # missing sample_id
        encoding="utf-8",
    )
    (no_id / "quality.json").write_text(json.dumps({"status": "good"}), encoding="utf-8")

    index = SampleIndex(tmp_path / "index" / "samples.sqlite3")
    indexed = index.rebuild(samples_dir)

    assert indexed == 1
    assert index.get_sample("good_sample") is not None
