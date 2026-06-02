"""M12: sample-write atomicity / crash-consistency tests.

These guard the H4 (index-after-rename) and M7 (durability) fixes in
``spectrum_acq.storage.sample_store``. The invariants under test:

* A payload-write failure must NOT leave a sample under ``samples/`` (the
  capture is reported FAILED and the sample stays unindexed; the partial is
  quarantined for diagnosis).
* The inverse failure mode must never happen: a complete on-disk sample that is
  reported FAILED. In particular, an index (SQLite) upsert failure must leave
  the finished sample on disk and NOT raise into a FAILED capture, because the
  filesystem is the source of truth and the index is a rebuildable cache.
"""

from __future__ import annotations

from pathlib import Path

import pytest

from spectrum_acq.capture import create_mock_coordinator
from spectrum_acq.storage import sample_store as sample_store_mod


def test_payload_write_failure_leaves_no_indexed_sample(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    coordinator = create_mock_coordinator(tmp_path / "data")
    store = coordinator.store

    # Inject a failure late in the payload write (after most artifacts exist)
    # to exercise the partial->failed quarantine path.
    def boom(*_args, **_kwargs):  # noqa: ANN002, ANN003
        raise RuntimeError("injected payload write failure")

    monkeypatch.setattr(sample_store_mod, "_save_roi_preview", boom)

    with pytest.raises(RuntimeError, match="injected payload write failure"):
        coordinator.capture()

    # No sample directory must exist under samples/ (nothing renamed into place).
    samples_dir = store.samples_dir
    assert list(samples_dir.iterdir()) == [], "a failed capture left a sample on disk"

    # Nothing indexed.
    assert store.list_samples() == []

    # The partial payload is quarantined as a .failed dir with an error record,
    # which is explicitly NOT under samples/ and so is never reported as a
    # valid sample.
    failed_dirs = list(store.tmp_dir.glob("*.failed"))
    assert len(failed_dirs) == 1
    assert (failed_dirs[0] / "error.json").exists()
    # And no leftover .partial.
    assert list(store.tmp_dir.glob("*.partial")) == []


def test_index_upsert_failure_keeps_complete_sample_on_disk(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """H4: a complete on-disk sample is never reported FAILED-but-present.

    If the index upsert fails *after* the atomic rename, the sample directory
    is complete and durable; the capture must succeed and the sample must be
    recoverable via rebuild_index().
    """
    coordinator = create_mock_coordinator(tmp_path / "data")
    store = coordinator.store

    def boom(*_args, **_kwargs):  # noqa: ANN002, ANN003
        raise RuntimeError("injected index failure")

    monkeypatch.setattr(store.index, "upsert_sample", boom)

    # Capture must NOT raise: the index is a best-effort cache, the sample is
    # already durably on disk.
    result = coordinator.capture()

    sample_path = Path(result.sample_path)
    # The complete sample is present under samples/...
    assert sample_path.exists()
    assert sample_path.parent == store.samples_dir
    assert (sample_path / "metadata.json").exists()
    assert (sample_path / "quality.json").exists()
    # ...but the (failed) index has no row yet.
    assert store.list_samples() == []

    # Reconcile: rebuild_index recovers the on-disk sample.
    monkeypatch.undo()  # restore the real upsert_sample for rebuild
    count = store.rebuild_index()
    assert count == 1
    assert store.get_sample(result.sample_id)["id"] == result.sample_id


def test_successful_capture_is_present_and_indexed(tmp_path: Path) -> None:
    """The happy path: complete sample is on disk AND indexed (the positive
    control for the two failure-mode tests above)."""
    coordinator = create_mock_coordinator(tmp_path / "data")
    result = coordinator.capture()

    sample_path = Path(result.sample_path)
    assert sample_path.exists()
    rows = coordinator.store.list_samples()
    assert len(rows) == 1
    assert rows[0]["id"] == result.sample_id
    # No quarantine / partial residue from a clean run.
    assert list(coordinator.store.tmp_dir.glob("*.failed")) == []
    assert list(coordinator.store.tmp_dir.glob("*.partial")) == []
