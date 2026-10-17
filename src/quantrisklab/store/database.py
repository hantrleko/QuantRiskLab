"""DuckDB tables for vintages, manifest, and COT positions."""

from __future__ import annotations

import json
from pathlib import Path

import duckdb
import polars as pl

from quantrisklab.paths import DB_PATH, MANIFEST_JSON
from quantrisklab.sources.http_util import ManifestRecord


def _empty_observations() -> pl.DataFrame:
    return pl.DataFrame(
        schema={
            "series_id": pl.Utf8,
            "source": pl.Utf8,
            "observation_date": pl.Date,
            "release_date": pl.Date,
            "value": pl.Float64,
            "realtime_start": pl.Date,
            "realtime_end": pl.Date,
        }
    )


def write_parquet(frame: pl.DataFrame, path: Path) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    frame.write_parquet(path)


def rebuild_database(
    observations: pl.DataFrame,
    positions: pl.DataFrame,
    series_meta: pl.DataFrame,
    manifest: list[ManifestRecord],
) -> None:
    if DB_PATH.exists():
        DB_PATH.unlink()
    wal = Path(str(DB_PATH) + ".wal")
    if wal.exists():
        wal.unlink()
    connection = duckdb.connect(str(DB_PATH))
    try:
        obs = observations if observations.height else _empty_observations()
        connection.register("obs_df", obs.to_arrow())
        connection.execute("CREATE TABLE observations AS SELECT * FROM obs_df")
        connection.register("meta_df", series_meta.to_arrow())
        connection.execute("CREATE TABLE series_meta AS SELECT * FROM meta_df")
        if positions.height:
            connection.register("pos_df", positions.to_arrow())
            connection.execute("CREATE TABLE cftc_positions AS SELECT * FROM pos_df")
        else:
            connection.execute(
                """
                CREATE TABLE cftc_positions (
                    market_id VARCHAR,
                    market_name VARCHAR,
                    title_zh VARCHAR,
                    report_family VARCHAR,
                    position_group VARCHAR,
                    position_group_zh VARCHAR,
                    observation_date DATE,
                    release_date DATE,
                    open_interest DOUBLE,
                    long_positions DOUBLE,
                    short_positions DOUBLE,
                    net_positions DOUBLE,
                    net_over_oi DOUBLE,
                    source_file VARCHAR
                )
                """
            )
        manifest_frame = pl.DataFrame([row.to_dict() for row in manifest]) if manifest else pl.DataFrame(
            schema={
                "path": pl.Utf8,
                "url": pl.Utf8,
                "access_date": pl.Utf8,
                "sha256": pl.Utf8,
                "original_unit": pl.Utf8,
                "original_frequency": pl.Utf8,
                "observation_date_min": pl.Utf8,
                "observation_date_max": pl.Utf8,
                "release_date_rule": pl.Utf8,
                "license": pl.Utf8,
                "series_id": pl.Utf8,
                "source": pl.Utf8,
                "http_status": pl.Int64,
                "row_count": pl.Int64,
                "notes": pl.Utf8,
            }
        )
        connection.register("man_df", manifest_frame.to_arrow())
        connection.execute("CREATE TABLE manifest AS SELECT * FROM man_df")
        connection.execute("CREATE INDEX idx_obs_series ON observations(series_id)")
    finally:
        connection.close()
    MANIFEST_JSON.write_text(
        json.dumps([row.to_dict() for row in manifest], ensure_ascii=False, indent=2),
        encoding="utf-8",
    )


def connect_readonly() -> duckdb.DuckDBPyConnection:
    if not DB_PATH.exists():
        raise FileNotFoundError("尚未构建数据库。请先运行 scripts/reproduce_v0.py")
    return duckdb.connect(str(DB_PATH), read_only=True)
