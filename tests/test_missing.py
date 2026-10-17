"""Missing marks in the cached FRED response stay missing."""

import json
from pathlib import Path

import pytest

pytestmark = pytest.mark.integration

from quantrisklab.sources.fred import _parse_value

RAW = Path(__file__).resolve().parents[1] / "data" / "raw" / "fred" / "DGS2.observations.offset0.json"


def test_cached_dgs2_dot_values_are_missing():
    assert RAW.exists()
    payload = json.loads(RAW.read_text(encoding="utf-8"))
    observations = payload["observations"]
    assert any(row.get("value") == "." for row in observations)
    parsed = [_parse_value(row.get("value")) for row in observations[:30]]
    assert any(value is None for value in parsed)
    assert any(isinstance(value, float) for value in parsed)
