"""Yields and VIX are not prices. No fabricated price path is used to force a VaR test."""

from pathlib import Path

import polars as pl
import pytest

from quantrisklab.metrics.risk import summarize_level

pytestmark = pytest.mark.integration
from quantrisklab.paths import PARQUET_DIR

ROOT = Path(__file__).resolve().parents[1]
SOURCES = ROOT / "DATA_SOURCES.md"
LEVELS = ("DGS2", "DGS10", "DFF", "T10Y2Y", "VIXCLS")


def test_cached_levels_are_not_priced_as_assets():
    assert SOURCES.exists(), "缺少 DATA_SOURCES.md"
    text = SOURCES.read_text(encoding="utf-8")
    assert "DCOILWTICO" in text
    assert "SP500" in text
    for series_id in LEVELS:
        path = PARQUET_DIR / "observations" / f"{series_id}.parquet"
        assert path.exists(), series_id
        frame = pl.read_parquet(path)
        summary = summarize_level(frame)
        assert summary["eligible"] is False
        assert "不是资产价格" in summary["reason"]
        assert "var" not in summary
    assert "不做回测" in text or "不报告策略收益" in text or "VaR" in text
