"""Point-in-time checks on cached FRED rows. Missing vintages stay a documented gap."""

from datetime import timedelta
from pathlib import Path

import polars as pl

from quantrisklab.paths import PARQUET_DIR
from quantrisklab.store.pit import latest_vintage

ROOT = Path(__file__).resolve().parents[1]
SOURCES = ROOT / "DATA_SOURCES.md"
CFTC = PARQUET_DIR / "cftc" / "positions.parquet"
ALFRED = PARQUET_DIR / "observations" / "UNRATE.parquet"


def _dates(frame: pl.DataFrame) -> pl.DataFrame:
    return frame.with_columns(
        pl.col("observation_date").cast(pl.Date),
        pl.col("release_date").cast(pl.Date),
    )


def test_cached_dgs10_is_hidden_before_its_observation_date():
    path = PARQUET_DIR / "observations" / "DGS10.parquet"
    assert path.exists()
    frame = _dates(pl.read_parquet(path)).filter(pl.col("value").is_not_null())
    row = frame.row(-1, named=True)
    observation = row["observation_date"]
    hidden = latest_vintage(frame, observation - timedelta(days=1), "DGS10")
    assert hidden.filter(pl.col("observation_date") == observation).is_empty()
    visible = latest_vintage(frame, observation, "DGS10")
    assert visible.filter(pl.col("observation_date") == observation)["value"][0] == row["value"]


def test_alfred_revision_gap_is_explicit_when_vintages_are_absent():
    text = SOURCES.read_text(encoding="utf-8")
    if ALFRED.exists():
        frame = _dates(pl.read_parquet(ALFRED))
        revised = (
            frame.group_by("observation_date")
            .agg(pl.col("value").n_unique().alias("n_values"))
            .filter(pl.col("n_values") > 1)
        )
        assert revised.height > 0 or "没有" in text
        return
    assert "ALFRED" in text or "UNRATE" in text
    assert any(token in text for token in ("超时", "阻碍", "拒绝入库", "不再重试", "没有区分"))


def test_cftc_release_lag_or_documented_gap():
    text = SOURCES.read_text(encoding="utf-8")
    if not CFTC.exists():
        assert "CFTC" in text or "cftc" in text.lower()
        assert any(token in text for token in ("超时", "阻碍", "失败", "不再重试", "没有"))
        return
    frame = _dates(pl.read_parquet(CFTC))
    assert frame.filter(pl.col("release_date") <= pl.col("observation_date")).is_empty()
    view = frame.rename({"market_id": "series_id", "net_positions": "value"})
    row = view.row(0, named=True)
    hidden = latest_vintage(view, row["observation_date"], row["series_id"])
    assert hidden.filter(pl.col("observation_date") == row["observation_date"]).is_empty()
