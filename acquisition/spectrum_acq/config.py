"""Configuration loading and persistence."""

from __future__ import annotations

import json
from dataclasses import fields, is_dataclass
from pathlib import Path
from typing import Any, TypeVar

from .models import (
    AcquisitionConfig,
    D455Profile,
    DiskThresholds,
    H1AutoExposureConfig,
    QualityThresholds,
    Roi,
    to_jsonable,
)

T = TypeVar("T")


def default_config(data_dir: Path | str = "data") -> AcquisitionConfig:
    return AcquisitionConfig(data_dir=Path(data_dir))


def config_file_for(data_dir: Path) -> Path:
    return data_dir / "config" / "acquisition.json"


def load_config(path: Path | None = None, *, data_dir: Path | str = "data") -> AcquisitionConfig:
    base = default_config(data_dir)
    cfg_path = path or config_file_for(base.data_dir)
    if not cfg_path.exists():
        return base
    with cfg_path.open("r", encoding="utf-8") as f:
        raw = json.load(f)
    return _merge_config(base, raw)


def save_config(config: AcquisitionConfig, path: Path | None = None) -> Path:
    cfg_path = path or config_file_for(config.data_dir)
    cfg_path.parent.mkdir(parents=True, exist_ok=True)
    with cfg_path.open("w", encoding="utf-8") as f:
        json.dump(to_jsonable(config), f, ensure_ascii=False, indent=2)
        f.write("\n")
    return cfg_path


def _merge_config(base: AcquisitionConfig, raw: dict[str, Any]) -> AcquisitionConfig:
    return AcquisitionConfig(
        data_dir=Path(raw.get("data_dir", base.data_dir)),
        mock=bool(raw.get("mock", base.mock)),
        roi=_merge_dataclass(base.roi, raw.get("roi", {}), Roi),
        d455_profile=_merge_dataclass(base.d455_profile, raw.get("d455_profile", {}), D455Profile),
        disk=_merge_dataclass(base.disk, raw.get("disk", {}), DiskThresholds),
        h1_auto_exposure=_merge_dataclass(
            base.h1_auto_exposure,
            raw.get("h1_auto_exposure", {}),
            H1AutoExposureConfig,
        ),
        quality=_merge_dataclass(base.quality, raw.get("quality", {}), QualityThresholds),
        h1_port=str(raw.get("h1_port", base.h1_port)),
        calibration_path=(
            Path(raw["calibration_path"]) if raw.get("calibration_path") else base.calibration_path
        ),
    )


def _merge_dataclass(base: T, raw: dict[str, Any], cls: type[T]) -> T:
    if not is_dataclass(base):
        raise TypeError("base must be a dataclass")
    values = {field.name: getattr(base, field.name) for field in fields(base)}
    values.update({k: v for k, v in raw.items() if k in values})
    return cls(**values)
