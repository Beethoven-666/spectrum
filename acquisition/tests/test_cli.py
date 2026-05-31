from __future__ import annotations

import sys
from pathlib import Path

from spectrum_acq.cli import main
from spectrum_acq.config import default_config, load_config, save_config


def test_cli_preserves_saved_calibration_path(tmp_path: Path, monkeypatch) -> None:
    data_dir = tmp_path / "data"
    calibration_path = data_dir / "calibration" / "bench.json"
    calibration_path.parent.mkdir(parents=True)
    calibration_path.write_text('{"version":"bench"}\n', encoding="utf-8")
    save_config(
        type(default_config(data_dir))(
            **{
                **default_config(data_dir).__dict__,
                "calibration_path": calibration_path,
            }
        )
    )
    monkeypatch.setattr(
        sys,
        "argv",
        ["spectrum-acq", "rebuild-index", "--data-dir", str(data_dir), "--hardware"],
    )

    main()

    assert load_config(data_dir=data_dir).calibration_path == calibration_path
