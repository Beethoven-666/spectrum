from __future__ import annotations

import json
import math

from spectrum_acq.models import json_dumps, to_jsonable


def test_to_jsonable_replaces_non_finite_floats_with_null() -> None:
    payload = {
        "photometric": {"b_ratio": math.inf, "lux": 123.4},
        "values": [float("nan"), 1.0],
    }
    sanitized = to_jsonable(payload)
    assert sanitized["photometric"]["b_ratio"] is None
    assert sanitized["photometric"]["lux"] == 123.4
    assert sanitized["values"][0] is None
    assert sanitized["values"][1] == 1.0


def test_json_dumps_is_strict_json() -> None:
    payload = {"ratio": math.inf}
    encoded = json_dumps(payload)
    assert "Infinity" not in encoded
    assert json.loads(encoded) == {"ratio": None}
