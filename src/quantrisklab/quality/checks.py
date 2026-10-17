"""Data-quality checks on the latest visible vintage. Missing values stay missing."""

from __future__ import annotations

from datetime import date

import duckdb

from quantrisklab.store.pit import query_series


def _dates(frame_col) -> list[date]:
    values = []
    for item in frame_col:
        if hasattr(item, "date") and not isinstance(item, date):
            item = item.date()
        values.append(item)
    return values


def long_gap_count(dates: list[date], frequency: str) -> int:
    if len(dates) < 2:
        return 0
    ordered = sorted(dates)
    limit = 5
    freq = frequency.lower()
    if freq.startswith("week"):
        limit = 10
    elif freq.startswith("month"):
        limit = 40
    elif freq.startswith("quart"):
        limit = 120
    gaps = 0
    for left, right in zip(ordered, ordered[1:]):
        if (right - left).days > limit:
            gaps += 1
    return gaps


def build_quality_report(connection: duckdb.DuckDBPyConnection, as_of: date | None = None) -> list[dict]:
    as_of = as_of or date.today()
    meta = connection.execute(
        """
        SELECT series_id, title_zh, title_en, source, role, unit, frequency,
               price_metrics, pit_mode, release_rule, stale, notes, license
        FROM series_meta
        ORDER BY series_id
        """
    ).fetchall()
    columns = [
        "series_id",
        "title_zh",
        "title_en",
        "source",
        "role",
        "unit",
        "frequency",
        "price_metrics",
        "pit_mode",
        "release_rule",
        "stale",
        "notes",
        "license",
    ]
    reports = []
    for row in meta:
        item = dict(zip(columns, row))
        series_id = item["series_id"]
        counts = connection.execute(
            """
            SELECT
                COUNT(*) AS n_vintage_rows,
                COUNT(DISTINCT release_date) AS n_releases,
                SUM(CASE WHEN value IS NULL THEN 1 ELSE 0 END) AS null_values
            FROM observations
            WHERE series_id = ?
            """,
            [series_id],
        ).fetchone()
        duplicates = connection.execute(
            """
            SELECT COALESCE(SUM(cnt - 1), 0) FROM (
                SELECT COUNT(*) AS cnt
                FROM observations
                WHERE series_id = ?
                GROUP BY observation_date, release_date
                HAVING COUNT(*) > 1
            )
            """,
            [series_id],
        ).fetchone()[0]
        revisions = connection.execute(
            """
            SELECT COUNT(*) FROM (
                SELECT observation_date
                FROM observations
                WHERE series_id = ? AND value IS NOT NULL
                GROUP BY observation_date
                HAVING COUNT(DISTINCT value) > 1
            )
            """,
            [series_id],
        ).fetchone()[0]
        latest = query_series(connection, series_id, as_of)
        present = latest.filter(latest["value"].is_not_null()) if latest.height else latest
        missing = int(latest.height - present.height) if latest.height else 0
        obs_dates = _dates(present["observation_date"].to_list()) if present.height else []
        start = obs_dates[0].isoformat() if obs_dates else None
        end = obs_dates[-1].isoformat() if obs_dates else None
        reports.append(
            {
                **item,
                "price_metrics": bool(item["price_metrics"]),
                "stale": bool(item["stale"]),
                "as_of": as_of.isoformat(),
                "n_vintage_rows": int(counts[0] or 0),
                "n_releases": int(counts[1] or 0),
                "null_values_all_vintages": int(counts[2] or 0),
                "duplicate_vintage_keys": int(duplicates or 0),
                "revised_observations": int(revisions or 0),
                "n_visible": int(present.height),
                "missing_visible": missing,
                "missing_rate_visible": (missing / latest.height) if latest.height else None,
                "start": start,
                "end": end,
                "long_gaps": long_gap_count(obs_dates, item["frequency"] or ""),
                "release_before_observation": int(
                    connection.execute(
                        """
                        SELECT COUNT(*) FROM observations
                        WHERE series_id = ? AND release_date < observation_date
                        """,
                        [series_id],
                    ).fetchone()[0]
                ),
            }
        )
    return reports
