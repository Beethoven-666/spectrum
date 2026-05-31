"""SQLite sample index.

The filesystem sample directory remains the source of truth; this index is a
rebuildable query cache for the Web UI.
"""

from __future__ import annotations

import json
import sqlite3
from pathlib import Path
from typing import Any


class SampleIndex:
    def __init__(self, db_path: Path) -> None:
        self.db_path = db_path
        self.db_path.parent.mkdir(parents=True, exist_ok=True)
        self._init_schema()

    def _connect(self) -> sqlite3.Connection:
        conn = sqlite3.connect(self.db_path)
        conn.row_factory = sqlite3.Row
        return conn

    def _init_schema(self) -> None:
        with self._connect() as conn:
            conn.execute(
                """
                CREATE TABLE IF NOT EXISTS samples (
                  id TEXT PRIMARY KEY,
                  created_at TEXT NOT NULL,
                  path TEXT NOT NULL,
                  schema_version TEXT NOT NULL,
                  quality_status TEXT NOT NULL,
                  distance_mm REAL,
                  angle_deg REAL,
                  h1_exposure_status TEXT,
                  d455_serial TEXT,
                  h1_serial TEXT,
                  main_rgb_status TEXT,
                  calibration_version TEXT,
                  config_profile TEXT,
                  size_bytes INTEGER NOT NULL,
                  warnings_json TEXT NOT NULL
                )
                """
            )
            conn.execute("CREATE INDEX IF NOT EXISTS idx_samples_created_at ON samples(created_at)")
            conn.execute("CREATE INDEX IF NOT EXISTS idx_samples_quality ON samples(quality_status)")

    def upsert_sample(self, sample_path: Path, metadata: dict[str, Any], quality: dict[str, Any]) -> None:
        size_bytes = directory_size(sample_path)
        h1 = metadata.get("devices", {}).get("h1", {})
        d455 = metadata.get("devices", {}).get("d455", {})
        main_rgb = metadata.get("devices", {}).get("main_rgb", {})
        geometry = quality.get("geometry", {})
        h1_quality = quality.get("h1", {})
        with self._connect() as conn:
            conn.execute(
                """
                INSERT INTO samples (
                  id, created_at, path, schema_version, quality_status,
                  distance_mm, angle_deg, h1_exposure_status,
                  d455_serial, h1_serial, main_rgb_status,
                  calibration_version, config_profile, size_bytes, warnings_json
                ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                ON CONFLICT(id) DO UPDATE SET
                  created_at=excluded.created_at,
                  path=excluded.path,
                  schema_version=excluded.schema_version,
                  quality_status=excluded.quality_status,
                  distance_mm=excluded.distance_mm,
                  angle_deg=excluded.angle_deg,
                  h1_exposure_status=excluded.h1_exposure_status,
                  d455_serial=excluded.d455_serial,
                  h1_serial=excluded.h1_serial,
                  main_rgb_status=excluded.main_rgb_status,
                  calibration_version=excluded.calibration_version,
                  config_profile=excluded.config_profile,
                  size_bytes=excluded.size_bytes,
                  warnings_json=excluded.warnings_json
                """,
                (
                    metadata["sample_id"],
                    metadata["created_at"],
                    str(sample_path),
                    metadata["schema_version"],
                    quality["status"],
                    geometry.get("distance_mm"),
                    geometry.get("angle_deg"),
                    h1_quality.get("exposure_status"),
                    d455.get("serial"),
                    h1.get("serial_number"),
                    main_rgb.get("status"),
                    metadata.get("calibration", {}).get("version"),
                    metadata.get("config", {}).get("profile"),
                    size_bytes,
                    json.dumps(quality.get("warnings", []), ensure_ascii=False),
                ),
            )

    def list_samples(self, *, limit: int = 100) -> list[dict[str, Any]]:
        with self._connect() as conn:
            rows = conn.execute(
                "SELECT * FROM samples ORDER BY created_at DESC LIMIT ?",
                (limit,),
            ).fetchall()
        return [_row_to_dict(row) for row in rows]

    def query_samples(
        self,
        *,
        limit: int = 1000,
        quality_status: str | None = None,
        calibration_version: str | None = None,
    ) -> list[dict[str, Any]]:
        clauses: list[str] = []
        params: list[Any] = []
        if quality_status:
            clauses.append("quality_status = ?")
            params.append(quality_status)
        if calibration_version:
            clauses.append("calibration_version = ?")
            params.append(calibration_version)
        where = f"WHERE {' AND '.join(clauses)}" if clauses else ""
        params.append(limit)
        with self._connect() as conn:
            rows = conn.execute(
                f"SELECT * FROM samples {where} ORDER BY created_at DESC LIMIT ?",
                params,
            ).fetchall()
        return [_row_to_dict(row) for row in rows]

    def get_sample(self, sample_id: str) -> dict[str, Any] | None:
        with self._connect() as conn:
            row = conn.execute("SELECT * FROM samples WHERE id = ?", (sample_id,)).fetchone()
        return _row_to_dict(row) if row else None

    def rebuild(self, samples_dir: Path) -> int:
        count = 0
        self._init_schema()
        with self._connect() as conn:
            conn.execute("DELETE FROM samples")
        for metadata_path in sorted(samples_dir.glob("*/metadata.json")):
            sample_path = metadata_path.parent
            quality_path = sample_path / "quality.json"
            if not quality_path.exists():
                continue
            metadata = json.loads(metadata_path.read_text(encoding="utf-8"))
            quality = json.loads(quality_path.read_text(encoding="utf-8"))
            self.upsert_sample(sample_path, metadata, quality)
            count += 1
        return count


def directory_size(path: Path) -> int:
    total = 0
    for file in path.rglob("*"):
        if file.is_file():
            total += file.stat().st_size
    return total


def _row_to_dict(row: sqlite3.Row) -> dict[str, Any]:
    out = dict(row)
    out["warnings"] = json.loads(out.pop("warnings_json", "[]"))
    return out
