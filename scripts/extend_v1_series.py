"""Append DFII10, T10YIE, and DTWEXBGS when FRED returns them.

A failed series is recorded and skipped. Nothing is interpolated.
"""

from __future__ import annotations

import json
from datetime import date, datetime, timezone

import duckdb

from quantrisklab.catalog import FRED_LICENSE, FRED_SLOTS, SAME_DAY
from quantrisklab.paths import DB_PATH, PARQUET_DIR
from quantrisklab.sources.fred import FredClient, FredError
from quantrisklab.store.database import write_parquet

SERIES = ("DFII10", "T10YIE", "DTWEXBGS")
START = "2010-01-01"


def _slot(series_id: str) -> dict:
    for slot in FRED_SLOTS:
        if series_id in slot.get("candidates", []):
            return slot
    raise KeyError(series_id)


def _meta_row(slot: dict, series_id: str, meta: dict, first: date, last: date) -> dict:
    stale = (date.today() - last).days > 21
    notes = slot["notes"]
    if stale:
        notes += " 官方序列已滞后或停更。只使用已发布的真实观测，不向前填充。"
    return {
        "series_id": series_id,
        "title_zh": slot["title_zh"],
        "title_en": str(meta.get("title") or ""),
        "source": "fred",
        "role": slot["role"],
        "unit": str(meta.get("units") or ""),
        "frequency": str(meta.get("frequency") or ""),
        "price_metrics": bool(slot["price_metrics"]),
        "pit_mode": "observation_date",
        "release_rule": slot["release_rule"],
        "stale": stale,
        "notes": notes,
        "license": FRED_LICENSE,
        "seasonal_adjustment": str(meta.get("seasonal_adjustment") or ""),
        "observation_start": first.isoformat(),
        "observation_end": last.isoformat(),
    }


def main() -> int:
    if not DB_PATH.exists():
        print("no database")
        return 1
    client = FredClient()
    connection = duckdb.connect(str(DB_PATH))
    columns = [row[0] for row in connection.execute("DESCRIBE series_meta").fetchall()]
    report = []
    try:
        for series_id in SERIES:
            slot = _slot(series_id)
            try:
                meta, _record = client.fetch_metadata(series_id)
                frame, _records, summary = client.fetch_observations(
                    series_id,
                    START,
                    date.today().isoformat(),
                    "fred",
                    "observation_date",
                    release_rule=SAME_DAY,
                    license_text=FRED_LICENSE,
                )
            except FredError as exc:
                report.append({"series_id": series_id, "status": "failed", "http_status": exc.status, "rows": 0})
                print(f"{series_id} failed http={exc.status} rows=0")
                continue
            present = frame.filter(frame["value"].is_not_null())
            if present.height == 0:
                report.append({"series_id": series_id, "status": "empty", "rows": 0})
                print(f"{series_id} empty rows=0")
                continue
            first = present["observation_date"].min()
            last = present["observation_date"].max()
            connection.execute("DELETE FROM observations WHERE series_id = ?", [series_id])
            connection.execute("DELETE FROM series_meta WHERE series_id = ?", [series_id])
            connection.register("new_obs", frame.to_arrow())
            connection.execute("INSERT INTO observations SELECT * FROM new_obs")
            connection.unregister("new_obs")
            row = _meta_row(slot, series_id, meta, first, last)
            ordered = {name: row.get(name) for name in columns}
            connection.register("new_meta", __import__("polars").DataFrame([ordered]).to_arrow())
            connection.execute(f"INSERT INTO series_meta SELECT {', '.join(columns)} FROM new_meta")
            connection.unregister("new_meta")
            write_parquet(frame, PARQUET_DIR / "observations" / f"{series_id}.parquet")
            report.append(
                {
                    "series_id": series_id,
                    "status": "stored",
                    "rows": int(present.height),
                    "start": first.isoformat(),
                    "end": last.isoformat(),
                    "nonnull": summary["nonnull"],
                }
            )
            print(f"{series_id} stored rows={present.height} {first} {last}")
    finally:
        connection.close()
        client.close()
    path = DB_PATH.parent / "v1_series_status.json"
    path.write_text(
        json.dumps({"written_at_utc": datetime.now(timezone.utc).isoformat(), "series": report}, indent=2),
        encoding="utf-8",
    )
    print("status file written")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
