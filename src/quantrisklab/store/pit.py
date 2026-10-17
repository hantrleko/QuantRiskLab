"""Point-in-time selection: as_of sees only vintages already released."""

from __future__ import annotations

from datetime import date, datetime

import duckdb
import polars as pl

PIT_SQL = """
SELECT series_id, observation_date, release_date, value, source
FROM (
    SELECT
        series_id,
        observation_date,
        release_date,
        value,
        source,
        ROW_NUMBER() OVER (
            PARTITION BY series_id, observation_date
            ORDER BY release_date DESC
        ) AS rn
    FROM observations
    WHERE series_id = ?
      AND release_date <= ?
      AND observation_date <= ?
) ranked
WHERE rn = 1
ORDER BY observation_date
"""


def _as_date(value: date | datetime | str) -> date:
    if isinstance(value, datetime):
        return value.date()
    if isinstance(value, date):
        return value
    return datetime.strptime(str(value)[:10], "%Y-%m-%d").date()


def latest_vintage(frame: pl.DataFrame, as_of: date, series_id: str | None = None) -> pl.DataFrame:
    """Return the latest vintage of each observation with release_date <= as_of.

    A later revision is invisible when its release_date is after as_of.
    """
    if frame.is_empty():
        return frame
    subset = frame.filter((pl.col("release_date") <= as_of) & (pl.col("observation_date") <= as_of))
    if series_id is not None:
        subset = subset.filter(pl.col("series_id") == series_id)
    if subset.is_empty():
        return subset.clear()
    return (
        subset.sort(["series_id", "observation_date", "release_date"])
        .unique(subset=["series_id", "observation_date"], keep="last")
        .sort(["series_id", "observation_date"])
    )


def query_series(connection: duckdb.DuckDBPyConnection, series_id: str, as_of: date) -> pl.DataFrame:
    arrow = connection.execute(PIT_SQL, [series_id, as_of, as_of]).to_arrow_table()
    table = pl.from_arrow(arrow)
    if table.is_empty():
        return table
    return table.with_columns(
        pl.col("observation_date").cast(pl.Date),
        pl.col("release_date").cast(pl.Date),
    )
