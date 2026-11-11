"""Extend the local snapshot to 2000 and add NASDAQCOM plus BAA10Y.

The public site must not run this. A failed request does not delete stored rows,
and a shorter official file does not erase older real observations.
"""

from __future__ import annotations

import csv
import json
import os
import zipfile
from datetime import date, datetime, timedelta, timezone

import duckdb
import polars as pl

from extend_v11 import _archive_pages, _as_date, _columns, _download_zip, _meta_row
from quantrisklab.catalog import FRED_LICENSE, YIELD_NOTE
from quantrisklab.paths import DB_PATH, PARQUET_DIR, RAW_DIR, ensure_dirs
from quantrisklab.sources.cftc import parse_cot_zip
from quantrisklab.sources.fred import FredClient, FredError
from quantrisklab.store.database import write_parquet

HISTORY_START = "2000-01-01"
FRESH_DAYS = 40
EQUITY_CANDIDATES = ("WILL5000PRFC", "WILL5000PR", "NASDAQCOM")
EQUITY_TITLES = {
    "WILL5000PRFC": "威尔希尔5000全市值价格指数",
    "WILL5000PR": "威尔希尔5000价格指数",
    "NASDAQCOM": "纳斯达克综合指数",
}
CREDIT_ID = "BAA10Y"
CREDIT_TITLE = "穆迪 Baa 与 10 年国债利差"
DAILY_EXISTING = (
    "DGS2",
    "DGS10",
    "DFF",
    "T10Y2Y",
    "VIXCLS",
    "DCOILWTICO",
    "DFII10",
    "T10YIE",
    "DTWEXBGS",
    "BAMLC0A0CM",
    "SP500",
)


def _slot(series_id: str) -> dict:
    from quantrisklab.catalog import ALFRED_SLOTS, FRED_SLOTS

    for slot in FRED_SLOTS:
        if series_id in slot.get("candidates", []):
            return slot
    for slot in ALFRED_SLOTS:
        if slot.get("series_id") == series_id:
            return slot
    raise KeyError(series_id)


def _insert_rows(connection: duckdb.DuckDBPyConnection, table: str, frame: pl.DataFrame) -> None:
    columns = _columns(connection, table)
    missing = [name for name in columns if name not in frame.columns]
    if missing:
        raise RuntimeError(f"{table} 缺少列 {missing}")
    connection.register("incoming", frame.select(columns).to_arrow())
    try:
        quoted = ", ".join(columns)
        connection.execute(f"INSERT INTO {table} ({quoted}) SELECT {quoted} FROM incoming")
    finally:
        connection.unregister("incoming")


def _retry(action):
    try:
        return action(), None
    except FredError as exc:
        if exc.status != 0:
            return None, exc
        try:
            return action(), None
        except FredError as again:
            return None, again


def _failure(series_id: str, exc: FredError) -> dict:
    detail = str(exc).replace("\n", " ")[:180]
    print(f"{series_id} failed http={exc.status} rows=0", flush=True)
    return {"series_id": series_id, "status": "failed", "http_status": exc.status, "detail": detail, "rows": 0}


def _span(connection: duckdb.DuckDBPyConnection, series_id: str):
    row = connection.execute(
        """
        SELECT MIN(observation_date), MAX(observation_date), COUNT(*)
        FROM observations
        WHERE series_id = ? AND value IS NOT NULL
        """,
        [series_id],
    ).fetchone()
    if row is None or row[2] in (None, 0) or row[0] is None:
        return None, None, 0
    return _as_date(row[0]), _as_date(row[1]), int(row[2])


def _identity(connection: duckdb.DuckDBPyConnection, series_id: str) -> dict | None:
    row = connection.execute(
        "SELECT title_zh, notes, release_rule FROM series_meta WHERE series_id = ?",
        [series_id],
    ).fetchone()
    if row is None:
        return None
    return {"title_zh": row[0], "notes": row[1], "release_rule": row[2]}


def _meta_frame(connection, slot, series_id, meta, first, last, source, pit_mode, identity):
    row = _meta_row(slot, series_id, meta, first, last, source, pit_mode)
    if identity and identity.get("title_zh"):
        row["title_zh"] = identity["title_zh"]
    if identity and identity.get("notes"):
        row["notes"] = identity["notes"]
    if identity and identity.get("release_rule"):
        row["release_rule"] = identity["release_rule"]
    columns = _columns(connection, "series_meta")
    return pl.DataFrame([{name: row.get(name) for name in columns}])


def _replace_all(connection, frame, slot, series_id, meta, source, pit_mode, identity) -> dict:
    present = frame.filter(pl.col("value").is_not_null())
    first = _as_date(present["observation_date"].min())
    last = _as_date(present["observation_date"].max())
    meta_frame = _meta_frame(connection, slot, series_id, meta, first, last, source, pit_mode, identity)
    connection.execute("BEGIN")
    try:
        connection.execute("DELETE FROM observations WHERE series_id = ?", [series_id])
        connection.execute("DELETE FROM series_meta WHERE series_id = ?", [series_id])
        _insert_rows(connection, "observations", frame)
        _insert_rows(connection, "series_meta", meta_frame)
        connection.execute("COMMIT")
    except Exception:
        connection.execute("ROLLBACK")
        raise
    write_parquet(frame, PARQUET_DIR / "observations" / f"{series_id}.parquet")
    print(f"{series_id} stored rows={present.height} {first} {last}", flush=True)
    return {
        "series_id": series_id,
        "status": "stored",
        "rows": int(present.height),
        "start": first.isoformat(),
        "end": last.isoformat(),
    }


def _merge_keep_earlier(connection, frame, slot, series_id, meta, new_first, source, pit_mode, identity) -> dict:
    meta_frame = None
    connection.execute("BEGIN")
    try:
        connection.execute(
            "DELETE FROM observations WHERE series_id = ? AND observation_date >= ?",
            [series_id, new_first],
        )
        _insert_rows(connection, "observations", frame)
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
        meta_frame = _meta_frame(connection, slot, series_id, meta, first, last, source, pit_mode, identity)
        connection.execute("DELETE FROM series_meta WHERE series_id = ?", [series_id])
        _insert_rows(connection, "series_meta", meta_frame)
        connection.execute("COMMIT")
    except Exception:
        connection.execute("ROLLBACK")
        raise
    stored = pl.from_arrow(
        connection.execute("SELECT * FROM observations WHERE series_id = ?", [series_id]).fetch_arrow_table()
    )
    write_parquet(stored, PARQUET_DIR / "observations" / f"{series_id}.parquet")
    print(f"{series_id} merged rows={int(span[2])} {first} {last} returned_from={new_first}", flush=True)
    return {
        "series_id": series_id,
        "status": "merged",
        "rows": int(span[2]),
        "start": first.isoformat(),
        "end": last.isoformat(),
        "returned_start": new_first.isoformat(),
    }


def _apply(connection, frame, slot, series_id, meta, source, pit_mode, preserve: bool) -> dict:
    present = frame.filter(pl.col("value").is_not_null())
    if present.height == 0:
        print(f"{series_id} empty rows=0", flush=True)
        return {"series_id": series_id, "status": "empty", "rows": 0}
    new_first = _as_date(present["observation_date"].min())
    new_last = _as_date(present["observation_date"].max())
    current_start, current_end, current_rows = _span(connection, series_id)
    if current_end is not None and new_last < current_end - timedelta(days=21):
        print(f"{series_id} short_tail {new_last} stored_end={current_end} rows={current_rows}", flush=True)
        return {
            "series_id": series_id,
            "status": "short_tail",
            "rows": current_rows,
            "returned_end": new_last.isoformat(),
        }
    identity = _identity(connection, series_id) if preserve else None
    if current_start is not None and new_first > current_start:
        return _merge_keep_earlier(
            connection, frame, slot, series_id, meta, new_first, source, pit_mode, identity
        )
    return _replace_all(connection, frame, slot, series_id, meta, source, pit_mode, identity)


def _fetch_daily(client: FredClient, series_id: str, slot: dict):
    def pull():
        meta, _record = client.fetch_metadata(series_id)
        frame, _records, _summary = client.fetch_observations(
            series_id,
            HISTORY_START,
            date.today().isoformat(),
            "fred",
            "observation_date",
            release_rule=slot["release_rule"],
            license_text=FRED_LICENSE,
        )
        return meta, frame

    return _retry(pull)


def _metadata(client: FredClient, series_id: str):
    fetched, exc = _retry(lambda: client.fetch_metadata(series_id))
    if exc is not None:
        return None, exc
    meta, _record = fetched
    return meta, None


def _choose_equity(client: FredClient):
    notes = []
    today = date.today()
    for series_id in EQUITY_CANDIDATES:
        meta, exc = _metadata(client, series_id)
        if exc is not None:
            print(f"{series_id} metadata failed http={exc.status}", flush=True)
            notes.append({"series_id": series_id, "status": "failed", "http_status": exc.status})
            continue
        start = date.fromisoformat(str(meta.get("observation_start"))[:10])
        end = date.fromisoformat(str(meta.get("observation_end"))[:10])
        fresh = (today - end).days <= FRESH_DAYS
        covers = start <= date(2000, 1, 1)
        print(f"{series_id} official {start} {end} fresh={fresh}", flush=True)
        notes.append(
            {
                "series_id": series_id,
                "start": start.isoformat(),
                "end": end.isoformat(),
                "fresh": fresh,
                "covers_2000": covers,
            }
        )
        if covers and fresh:
            return series_id, meta, notes
    return None, None, notes


def _equity_slot(series_id: str, meta: dict) -> dict:
    slot = dict(_slot(series_id))
    official_start = str(meta.get("observation_start") or "")[:10]
    official_end = str(meta.get("observation_end") or "")[:10]
    slot["title_zh"] = EQUITY_TITLES[series_id]
    slot["notes"] = (
        "这不是标普 500，也不与 SP500 拼接。"
        f"FRED 官方起点 {official_start}，官方终点 {official_end}。"
        "本库从 2000-01-01 起保存实际返回的观测。价格指数不含股息。"
    )
    return slot


def _credit_slot(meta: dict) -> dict:
    slot = dict(_slot(CREDIT_ID))
    official_start = str(meta.get("observation_start") or "")[:10]
    slot["title_zh"] = CREDIT_TITLE
    slot["notes"] = (
        YIELD_NOTE
        + " 这是穆迪 Baa 公司债收益率与 10 年国债收益率之差，不是 ICE BofA OAS。"
        + f" FRED 官方起点 {official_start}。OAS 仍单独保存为 BAMLC0A0CM。"
    )
    return slot


def _store_daily(client, connection, series_id: str, slot: dict, known_meta: dict | None, preserve: bool) -> dict:
    if known_meta is None:
        fetched, exc = _fetch_daily(client, series_id, slot)
        if exc is not None:
            return _failure(series_id, exc)
        meta, frame = fetched
    else:
        meta = known_meta

        def pull():
            frame, _records, _summary = client.fetch_observations(
                series_id,
                HISTORY_START,
                date.today().isoformat(),
                "fred",
                "observation_date",
                release_rule=slot["release_rule"],
                license_text=FRED_LICENSE,
            )
            return frame

        frame, exc = _retry(pull)
        if exc is not None:
            return _failure(series_id, exc)
    return _apply(connection, frame, slot, series_id, meta, "fred", "observation_date", preserve)


def _windows():
    today = date.today()
    year = 2000
    while year <= today.year:
        end_year = min(year + 2, today.year)
        start = f"{year}-01-01"
        end = today.isoformat() if end_year == today.year else f"{end_year}-12-31"
        yield start, end
        year = end_year + 1


def _fetch_alfred_span(client, series_id, start, end, slot, depth=0):
    def pull():
        frame, _records, _summary = client.fetch_observations(
            series_id,
            start,
            end,
            "alfred",
            "alfred",
            realtime_start=HISTORY_START,
            realtime_end=date.today().isoformat(),
            release_rule=slot["release_rule"],
            license_text=FRED_LICENSE,
            raw_subdir="alfred",
        )
        return frame

    frame, exc = _retry(pull)
    if exc is None:
        _archive_pages(series_id, "alfred", start.replace("-", ""))
        present = frame.filter(pl.col("value").is_not_null())
        print(f"{series_id} {start} rows={present.height}", flush=True)
        return frame, [{"start": start, "end": end, "status": "returned", "rows": int(present.height)}]
    start_year = int(start[:4])
    end_year = int(end[:4])
    if depth < 3 and end_year > start_year:
        mid = (start_year + end_year) // 2
        print(f"{series_id} {start} split after http={exc.status}", flush=True)
        left, left_windows = _fetch_alfred_span(client, series_id, f"{start_year}-01-01", f"{mid}-12-31", slot, depth + 1)
        right, right_windows = _fetch_alfred_span(
            client, series_id, f"{mid + 1}-01-01", end, slot, depth + 1
        )
        pieces = [item for item in (left, right) if item is not None and item.height]
        combined = pl.concat(pieces, how="vertical") if pieces else None
        return combined, left_windows + right_windows
    print(f"{series_id} {start} failed http={exc.status} rows=0", flush=True)
    return None, [{"start": start, "end": end, "status": "failed", "http_status": exc.status, "rows": 0}]


def _refresh_parquet(connection, series_id: str) -> None:
    stored = pl.from_arrow(
        connection.execute("SELECT * FROM observations WHERE series_id = ?", [series_id]).fetch_arrow_table()
    )
    write_parquet(stored, PARQUET_DIR / "observations" / f"{series_id}.parquet")


def _alfred(client, connection, series_id: str) -> dict:
    slot = _slot(series_id)
    meta, exc = _metadata(client, series_id)
    if exc is not None:
        return _failure(series_id, exc)
    frames = []
    windows = []
    for start, end in _windows():
        frame, report = _fetch_alfred_span(client, series_id, start, end, slot)
        windows.extend(report)
        if frame is not None and frame.height:
            frames.append(frame)
    failed = any(item["status"] != "returned" for item in windows)
    if not frames:
        return {"series_id": series_id, "status": "empty", "rows": 0, "windows": windows, "partial": True}
    merged = pl.concat(frames, how="vertical").unique(
        subset=["series_id", "observation_date", "release_date", "realtime_start"],
        keep="last",
    )
    current_start, _current_end, current_rows = _span(connection, series_id)
    if failed and current_start is not None:
        early = merged.filter(pl.col("observation_date") < pl.lit(current_start))
        if early.height == 0:
            print(f"{series_id} partial; kept {current_rows} stored rows", flush=True)
            return {
                "series_id": series_id,
                "status": "partial_kept",
                "rows": current_rows,
                "windows": windows,
                "partial": True,
            }
        connection.execute("BEGIN")
        try:
            _insert_rows(connection, "observations", early)
            connection.execute("COMMIT")
        except Exception:
            connection.execute("ROLLBACK")
            raise
        _refresh_parquet(connection, series_id)
        span = _span(connection, series_id)
        connection.execute(
            "UPDATE series_meta SET observation_start = ?, observation_end = ? WHERE series_id = ?",
            [span[0].isoformat(), span[1].isoformat(), series_id],
        )
        print(f"{series_id} partial_extended rows={early.height} start={span[0]}", flush=True)
        return {
            "series_id": series_id,
            "status": "partial_extended",
            "rows": int(span[2]),
            "start": span[0].isoformat(),
            "end": span[1].isoformat(),
            "windows": windows,
            "partial": True,
        }
    identity = _identity(connection, series_id)
    stored = _replace_all(connection, merged, slot, series_id, meta, "alfred", "alfred", identity)
    stored["windows"] = windows
    stored["partial"] = failed
    return stored


def _cftc(connection) -> list[dict]:
    reports = []
    wrote = False
    for year in range(2006, 2027):
        for family, prefix in (("disagg", "fut_disagg_txt"), ("tff", "fut_fin_txt")):
            name = f"{prefix}_{year}.zip"
            dest = RAW_DIR / "cftc" / name
            url = f"https://www.cftc.gov/files/dea/history/{name}"
            state = _download_zip(url, dest)
            if state.startswith("http") or state == "failed":
                print(f"{name} {state} rows=0", flush=True)
                reports.append({"file": name, "status": state, "rows": 0})
                continue
            try:
                frame = parse_cot_zip(dest.read_bytes(), family, dest.name)
            except (OSError, ValueError, zipfile.BadZipFile, csv.Error, UnicodeError) as exc:
                print(f"{name} parse_failed rows=0", flush=True)
                reports.append({"file": name, "status": "parse_failed", "rows": 0, "detail": type(exc).__name__})
                continue
            if frame.height == 0:
                print(f"{name} empty rows=0", flush=True)
                reports.append({"file": name, "status": "empty", "rows": 0})
                continue
            connection.execute("BEGIN")
            try:
                connection.execute("DELETE FROM cftc_positions WHERE source_file = ?", [dest.name])
                _insert_rows(connection, "cftc_positions", frame)
                connection.execute("COMMIT")
            except Exception:
                connection.execute("ROLLBACK")
                raise
            wrote = True
            print(f"{name} stored rows={frame.height}", flush=True)
            reports.append({"file": name, "status": state, "rows": int(frame.height)})
    if wrote:
        positions = pl.from_arrow(connection.execute("SELECT * FROM cftc_positions").to_arrow_table())
        write_parquet(positions, PARQUET_DIR / "cftc" / "positions.parquet")
    return reports


def reparse_early() -> int:
    """Load cached 2010–2012 COT files. Their date column is labeled MM_DD_YYYY but the cells are ISO dates."""
    if os.environ.get("QUANTRISKLAB_PUBLIC") == "1":
        print("公网部署只提供演示快照，不请求 FRED。", flush=True)
        return 2
    ensure_dirs()
    connection = duckdb.connect(str(DB_PATH))
    wrote = False
    try:
        for year in (2010, 2011, 2012):
            for family, prefix in (("disagg", "fut_disagg_txt"), ("tff", "fut_fin_txt")):
                name = f"{prefix}_{year}.zip"
                dest = RAW_DIR / "cftc" / name
                if not dest.exists():
                    print(f"{name} missing rows=0", flush=True)
                    continue
                try:
                    frame = parse_cot_zip(dest.read_bytes(), family, dest.name)
                except (OSError, ValueError, zipfile.BadZipFile, csv.Error, UnicodeError) as exc:
                    print(f"{name} parse_failed rows=0 {type(exc).__name__}", flush=True)
                    continue
                if frame.height == 0:
                    print(f"{name} empty rows=0", flush=True)
                    continue
                connection.execute("BEGIN")
                try:
                    connection.execute("DELETE FROM cftc_positions WHERE source_file = ?", [dest.name])
                    _insert_rows(connection, "cftc_positions", frame)
                    connection.execute("COMMIT")
                except Exception:
                    connection.execute("ROLLBACK")
                    raise
                wrote = True
                print(f"{name} stored rows={frame.height}", flush=True)
        if wrote:
            positions = pl.from_arrow(connection.execute("SELECT * FROM cftc_positions").to_arrow_table())
            write_parquet(positions, PARQUET_DIR / "cftc" / "positions.parquet")
    finally:
        connection.close()
    return 0


def main() -> int:
    if os.environ.get("QUANTRISKLAB_PUBLIC") == "1":
        print("公网部署只提供演示快照，不请求 FRED。", flush=True)
        return 2
    ensure_dirs()
    if not DB_PATH.exists():
        print("no database", flush=True)
        return 1
    client = FredClient()
    client.timeout_seconds = 180
    connection = duckdb.connect(str(DB_PATH))
    report: dict = {"history_start": HISTORY_START}
    try:
        equity_id, equity_meta, equity_notes = _choose_equity(client)
        report["equity_candidates"] = equity_notes
        if equity_id is None:
            report["equity"] = {"status": "unselected", "rows": 0}
            print("no long equity series", flush=True)
        else:
            report["equity"] = _store_daily(
                client, connection, equity_id, _equity_slot(equity_id, equity_meta), equity_meta, False
            )
            report["equity"]["selected"] = equity_id
        credit_meta, credit_exc = _metadata(client, CREDIT_ID)
        if credit_exc is not None:
            report["baa10y"] = _failure(CREDIT_ID, credit_exc)
        else:
            official = str(credit_meta.get("observation_start") or "")[:10]
            print(f"BAA10Y official {official} {str(credit_meta.get('observation_end') or '')[:10]}", flush=True)
            report["baa10y"] = _store_daily(
                client, connection, CREDIT_ID, _credit_slot(credit_meta), credit_meta, False
            )
        report["daily"] = {}
        for series_id in DAILY_EXISTING:
            report["daily"][series_id] = _store_daily(client, connection, series_id, _slot(series_id), None, True)
        report["unrate"] = _alfred(client, connection, "UNRATE")
        report["cpi"] = _alfred(client, connection, "CPIAUCSL")
        report["cftc"] = _cftc(connection)
    finally:
        connection.close()
        client.close()
    path = DB_PATH.parent / "v22_series_status.json"
    path.write_text(
        json.dumps({"written_at_utc": datetime.now(timezone.utc).isoformat(), **report}, ensure_ascii=False, indent=2, default=str),
        encoding="utf-8",
    )
    print("status file written", flush=True)
    equity_ok = report.get("equity", {}).get("status") in {"stored", "merged"}
    credit_ok = report.get("baa10y", {}).get("status") in {"stored", "merged"}
    return 0 if equity_ok and credit_ok else 1


if __name__ == "__main__":
    raise SystemExit(main())
