"""CIE mode string mapping shared by the H1 gateway and API layer."""

from __future__ import annotations

from typing import Any


def _cie_mode_to_name() -> dict[Any, str]:
    from h1_sdk.types import CieMode

    return {
        CieMode.Cie1931_2: "cie1931_2",
        CieMode.Cie1964_10: "cie1964_10",
        CieMode.Cie2015_2: "cie2015_2",
        CieMode.Cie2015_10: "cie2015_10",
    }


def _cie_name_to_mode() -> dict[str, Any]:
    return {name: mode for mode, name in _cie_mode_to_name().items()}


def cie_mode_name(mode: Any) -> str:
    return _cie_mode_to_name().get(mode, "cie1931_2")


def cie_mode_from_name(mode_name: str) -> Any:
    mode = _cie_name_to_mode().get(mode_name)
    if mode is None:
        raise ValueError(f'unknown CIE mode "{mode_name}"')
    return mode
