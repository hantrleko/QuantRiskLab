"""Store OAS history, UNRATE vintages, CFTC years, and one gold attempt.

Only rows returned by the source are written. A failed request is recorded
and does not invent observations.
"""

from __future__ import annotations

import json
import urllib.error
import urllib.request
from datetime import date, datetime, timezone

import duckdb
import polars as pl

from quantrisklab.assemble_cache import CFTC_LOCAL
from quantrisklab.catalog import ALFRED_SLOTS, FRED_LICENSE, FRED_SLOTS, SAME_DAY
from quantrisklab.paths import DB_PATH, PARQUET_DIR, RAW_DIR, ensure_dirs
from quantrisklab.sources.cftc import parse_cot_zip
from quantrisklab.sources.fred import FredClient, FredError
from quantrisklab.store.database import write_parquet

OAS = "BAMLC0A0CM"
GOLD = "GOLDPMGBD228NLBM"
UNRATE_WINDOWS = (
    ("2015-01-01", "2017-12-31"),
    ("2018-01-01", "2020-12-31"),
    ("2021-01-01", "2023-12-31"),
    ("2024-01-01", date.today().isoformat()),
)


def _slot(series_id: str) -> dict:
    for slot in FRED_SLOTS:
        if series_id in slot.get("candidates", []):
            return slot
    for slot in ALFRED_SLOTS:
        if slot.get("series_id") == series_id:
            return slot
    raise KeyError(series_id)


def _columns(connection: duckdb.DuckDBPyConnection, table: str) -> list[str]:
    return [row[0] for row in connection.execute(f"DESCRIBE {table}").fetchall()]


def _insert(connection: duckdb.DuckDBPyConnection, table: str, frame: pl.DataFrame) -> None:
    columns = _columns(connection, table)
    missing = [name for name in columns if name not in frame.columns]
    if missing:
        raise RuntimeError(f"{table} 缺少列 {missing}")
    connection.register("incoming", frame.select(columns).to_arrow())
    quoted = ", ".join(columns)
    connection.execute(f"INSERT INTO {table} ({quoted}) SELECT {quoted} FROM incoming")
    connection.unregister("incoming")


def _as_date(value) -> date:
    if isinstance(value, datetime):
        return value.date()
    if isinstance(value, date):
        return value
    return date.fromisoformat(str(value)[:10])


def _meta_row(
    slot: dict,
    series_id: str,
    meta: dict,
    first: date,
    last: date,
    source: str,
    pit_mode: str,
    extra_note: str = "",
) -> dict:
    frequency = str(meta.get("frequency") or "")
    limit = 45 if frequency.lower().startswith("month") else 21
    stale = (date.today() - last).days > limit
    notes = slot["notes"] + extra_note
    if series_id == GOLD:
        notes += " 入库的是下午定盘价。上午定盘价没有可用观测。"
    if stale:
        notes += " 官方序列已滞后或停更。只使用已发布的真实观测，不向前填充。"
    return {
        "series_id": series_id,
        "title_zh": "伦敦金下午定盘价" if series_id == GOLD else slot["title_zh"],
        "title_en": str(meta.get("title") or ""),
        "source": source,
        "role": slot["role"],
        "unit": str(meta.get("units") or ""),
        "frequency": frequency,
        "price_metrics": bool(slot["price_metrics"]),
        "pit_mode": pit_mode,
        "release_rule": slot["release_rule"],
        "stale": stale,
        "notes": notes,
        "license": FRED_LICENSE,
        "seasonal_adjustment": str(meta.get("seasonal_adjustment") or ""),
        "observation_start": first.isoformat(),
        "observation_end": last.isoformat(),
    }


def _store_series(
    connection: duckdb.DuckDBPyConnection,
    frame: pl.DataFrame,
    slot: dict,
    series_id: str,
    meta: dict,
    source: str,
    pit_mode: str,
) -> dict:
    present = frame.filter(frame["value"].is_not_null())
    if present.height == 0:
        return {"series_id": series_id, "status": "empty", "rows": 0}
    first = present["observation_date"].min()
    last = present["observation_date"].max()
    connection.execute("DELETE FROM observations WHERE series_id = ?", [series_id])
    connection.execute("DELETE FROM series_meta WHERE series_id = ?", [series_id])
    _insert(connection, "observations", frame)
    row = _meta_row(slot, series_id, meta, first, last, source, pit_mode)
    meta_frame = pl.DataFrame([{name: row.get(name) for name in _columns(connection, "series_meta")}])
    _insert(connection, "series_meta", meta_frame)
    write_parquet(frame, PARQUET_DIR / "observations" / f"{series_id}.parquet")
    return {
        "series_id": series_id,
        "status": "stored",
        "rows": int(present.height),
        "start": first.isoformat(),
        "end": last.isoformat(),
    }


def _archive_pages(series_id: str, subdir: str, tag: str) -> None:
    folder = RAW_DIR / subdir
    marker = f"{series_id}.observations.offset"
    for path in list(folder.glob(f"{series_id}.observations.offset*.json")):
        rest = path.name[len(marker) :]
        head = rest.split(".", 1)[0]
        if "-" in head:
            continue
        dest = folder / f"{marker}{tag}-{rest}"
        if dest.exists():
            dest.unlink()
        path.replace(dest)


def _merge_from_date(
    connection: duckdb.DuckDBPyConnection,
    frame: pl.DataFrame,
    slot: dict,
    series_id: str,
    meta: dict,
    new_first: date,
) -> dict:
    """Keep already stored rows that the new response does not cover."""
    connection.execute(
        "DELETE FROM observations WHERE series_id = ? AND observation_date >= ?",
        [series_id, new_first],
    )
    _insert(connection, "observations", frame)
    span = connection.execute(
        """
        SELECT MIN(observation_date), MAX(observation_date), COUNT(*)
        FROM observations
        WHERE series_id = ? AND value IS NOT NULL
        """,
        [series_id],
    ).fetchone()
    first = _as_date(span[0])
    last = _as_date(span[1])
    connection.execute("DELETE FROM series_meta WHERE series_id = ?", [series_id])
    row = _meta_row(
        slot,
        series_id,
        meta,
        first,
        last,
        "fred",
        "observation_date",
        " 官方文件的起点晚于库内已有样本，更早的真实观测仍保留。",
    )
    meta_frame = pl.DataFrame([{name: row.get(name) for name in _columns(connection, "series_meta")}])
    _insert(connection, "series_meta", meta_frame)
    stored = pl.from_arrow(
        connection.execute("SELECT * FROM observations WHERE series_id = ?", [series_id]).fetch_arrow_table()
    )
    write_parquet(stored, PARQUET_DIR / "observations" / f"{series_id}.parquet")
    print(f"{series_id} merged rows={int(span[2])} {first} {last} returned_from={new_first}")
    return {
        "series_id": series_id,
        "status": "merged",
        "rows": int(span[2]),
        "start": first.isoformat(),
        "end": last.isoformat(),
        "returned_start": new_first.isoformat(),
    }


def _fred_replace(client: FredClient, connection: duckdb.DuckDBPyConnection, series_id: str, extend_only: bool) -> dict:
    slot = _slot(series_id)
    try:
        meta, _record = client.fetch_metadata(series_id)
        frame, _records, _summary = client.fetch_observations(
            series_id,
            "2010-01-01",
            date.today().isoformat(),
            "fred",
            "observation_date",
            release_rule=SAME_DAY,
            license_text=FRED_LICENSE,
        )
    except FredError as exc:
        print(f"{series_id} failed http={exc.status} rows=0")
        return {"series_id": series_id, "status": "failed", "http_status": exc.status, "rows": 0}
    present = frame.filter(frame["value"].is_not_null())
    if present.height == 0:
        print(f"{series_id} empty rows=0")
        return {"series_id": series_id, "status": "empty", "rows": 0}
    new_first = _as_date(present["observation_date"].min())
    if extend_only:
        current = connection.execute(
            "SELECT MIN(observation_date), COUNT(*) FROM observations WHERE series_id = ? AND value IS NOT NULL",
            [series_id],
        ).fetchone()
        current_start = None if current is None or current[0] is None else _as_date(current[0])
        current_rows = 0 if current is None or current[1] is None else int(current[1])
        if current_start is not None and new_first > current_start:
            return _merge_from_date(connection, frame, slot, series_id, meta, new_first)
        if current_start is not None and new_first >= current_start and present.height <= current_rows:
            print(f"{series_id} unchanged rows={current_rows} start={current_start}")
            return {
                "series_id": series_id,
                "status": "unchanged",
                "rows": current_rows,
                "start": str(current_start),
            }
    stored = _store_series(connection, frame, slot, series_id, meta, "fred", "observation_date")
    print(f"{series_id} stored rows={stored['rows']} {stored.get('start')} {stored.get('end')}")
    return stored


def _unrate(client: FredClient, connection: duckdb.DuckDBPyConnection) -> dict:
    slot = _slot("UNRATE")
    try:
        meta, _record = client.fetch_metadata("UNRATE")
    except FredError as exc:
        print(f"UNRATE metadata failed http={exc.status}")
        return {"series_id": "UNRATE", "status": "failed", "http_status": exc.status, "rows": 0, "windows": []}
    frames: list[pl.DataFrame] = []
    windows = []
    today = date.today().isoformat()
    for start, end in UNRATE_WINDOWS:
        try:
            frame, _records, _summary = client.fetch_observations(
                "UNRATE",
                start,
                end,
                "alfred",
                "alfred",
                realtime_start="2015-01-01",
                realtime_end=today,
                release_rule=slot["release_rule"],
                license_text=FRED_LICENSE,
                raw_subdir="alfred",
            )
        except FredError as exc:
            print(f"UNRATE {start} failed http={exc.status} rows=0")
            windows.append({"start": start, "end": end, "status": "failed", "http_status": exc.status, "rows": 0})
            continue
        _archive_pages("UNRATE", "alfred", start.replace("-", ""))
        present = frame.filter(frame["value"].is_not_null())
        windows.append({"start": start, "end": end, "status": "returned" if present.height else "empty", "rows": int(present.height)})
        print(f"UNRATE {start} rows={present.height}")
        if present.height:
            frames.append(frame)
    if not frames:
        return {"series_id": "UNRATE", "status": "empty", "rows": 0, "windows": windows}
    merged = pl.concat(frames, how="vertical").unique(
        subset=["series_id", "observation_date", "release_date", "realtime_start"],
        keep="last",
    )
    stored = _store_series(connection, merged, slot, "UNRATE", meta, "alfred", "alfred")
    stored["windows"] = windows
    stored["partial"] = any(item["status"] != "returned" for item in windows)
    print(f"UNRATE stored rows={stored['rows']} partial={stored['partial']}")
    return stored


def _download_zip(url: str, dest) -> str:
    if dest.exists() and dest.stat().st_size > 1000:
        return "cached"
    request = urllib.request.Request(url, headers={"User-Agent": "QuantRiskLab/2.0 research"})
    try:
        with urllib.request.urlopen(request, timeout=180) as response:
            payload = response.read()
            status = getattr(response, "status", 200)
    except urllib.error.HTTPError as exc:
        return f"http {exc.code}"
    except (urllib.error.URLError, TimeoutError, ConnectionError):
        return "failed"
    if status != 200 or len(payload) < 100:
        return f"http {status}"
    dest.parent.mkdir(parents=True, exist_ok=True)
    dest.write_bytes(payload)
    return "downloaded"


def _cftc(connection: duckdb.DuckDBPyConnection) -> list[dict]:
    reports = []
    frames = []
    for family, name, url in CFTC_LOCAL:
        dest = RAW_DIR / "cftc" / name
        state = _download_zip(url, dest)
        if state.startswith("http") or state == "failed":
            print(f"{name} {state} rows=0")
            reports.append({"file": name, "status": state, "rows": 0})
            continue
        try:
            frame = parse_cot_zip(dest.read_bytes(), family, dest.name)
        except (OSError, ValueError) as exc:
            print(f"{name} parse_failed rows=0")
            reports.append({"file": name, "status": "parse_failed", "rows": 0, "detail": type(exc).__name__})
            continue
        if frame.height == 0:
            print(f"{name} empty rows=0")
            reports.append({"file": name, "status": "empty", "rows": 0})
            continue
        connection.execute("DELETE FROM cftc_positions WHERE source_file = ?", [dest.name])
        _insert(connection, "cftc_positions", frame)
        frames.append(frame)
        print(f"{name} stored rows={frame.height}")
        reports.append({"file": name, "status": state, "rows": int(frame.height)})
    if frames:
        positions = pl.from_arrow(connection.execute("SELECT * FROM cftc_positions").fetch_arrow_table())
        write_parquet(positions, PARQUET_DIR / "cftc" / "positions.parquet")
    return reports


def main() -> int:
    ensure_dirs()
    if not DB_PATH.exists():
        print("no database")
        return 1
    client = FredClient()
    client.timeout_seconds = 180
    connection = duckdb.connect(str(DB_PATH))
    report: dict = {}
    try:
        report["oas"] = _fred_replace(client, connection, OAS, True)
        report["gold"] = _fred_replace(client, connection, GOLD, False)
        report["unrate"] = _unrate(client, connection)
        report["cftc"] = _cftc(connection)
    finally:
        connection.close()
        client.close()
    path = DB_PATH.parent / "v11_series_status.json"
    path.write_text(
        json.dumps({"written_at_utc": datetime.now(timezone.utc).isoformat(), **report}, ensure_ascii=False, indent=2),
        encoding="utf-8",
    )
    print("status file written")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
