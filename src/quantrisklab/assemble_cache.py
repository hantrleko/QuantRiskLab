"""Build the store from cached FRED responses. Do not walk the full download chain."""

from __future__ import annotations

import json
import logging
import shutil
import subprocess
from datetime import date
from pathlib import Path

import polars as pl

from quantrisklab.catalog import ALFRED_SLOTS, CFTC_LICENSE, FRED_LICENSE, FRED_SLOTS
from quantrisklab.logging_setup import setup_logging
from quantrisklab.paths import (
    DECISIONS_JSON,
    FAILURES_JSON,
    PARQUET_DIR,
    QUALITY_JSON,
    RAW_DIR,
    ROOT,
    ensure_dirs,
)
from quantrisklab.pipeline import _bundle_from_cache, _cached_pages, _clear_derived_parquet, _meta_row
from quantrisklab.quality.checks import build_quality_report
from quantrisklab.sources.bis import BisSdmxClient
from quantrisklab.sources.cftc import parse_cot_zip
from quantrisklab.sources.fred import observations_frame, public_observations_url, public_series_url
from quantrisklab.sources.http_util import DownloadFailure, ManifestRecord, iso, redact, relpath, sha256_file
from quantrisklab.store.database import connect_readonly, rebuild_database, write_parquet

logger = logging.getLogger("quantrisklab.assemble")

CACHED_SERIES = ("DGS2", "DGS10", "DFF", "T10Y2Y", "VIXCLS")
# These files are already on disk. Read them. Do not request FRED again.
EXTRA_LOCAL_FRED = ("DCOILWTICO", "SP500", "BAMLC0A0CM")
CFTC_LOCAL = (
    ("disagg", "fut_disagg_txt_2025.zip", "https://www.cftc.gov/files/dea/history/fut_disagg_txt_2025.zip"),
    ("disagg", "fut_disagg_txt_2026.zip", "https://www.cftc.gov/files/dea/history/fut_disagg_txt_2026.zip"),
    ("tff", "fut_fin_txt_2025.zip", "https://www.cftc.gov/files/dea/history/fut_fin_txt_2025.zip"),
    ("tff", "fut_fin_txt_2026.zip", "https://www.cftc.gov/files/dea/history/fut_fin_txt_2026.zip"),
)
def _slot(series_id: str) -> dict:
    for slot in FRED_SLOTS:
        if series_id in slot["candidates"]:
            return slot
    raise KeyError(series_id)


def _curl_once(url: str, dest: Path, timeout: int) -> tuple[int | None, str]:
    dest.parent.mkdir(parents=True, exist_ok=True)
    curl = shutil.which("curl.exe") or shutil.which("curl")
    if not curl:
        return None, "本机没有 curl，短请求无法发出"
    config = f'url = "{url}"\noutput = "{dest.as_posix()}"\n'
    try:
        completed = subprocess.run(
            [curl, "--max-time", str(timeout), "-sS", "-A", "QuantRiskLab/0.1 research", "-w", "%{http_code}", "-K", "-"],
            input=config.encode("utf-8"),
            capture_output=True,
            timeout=timeout + 5,
            check=False,
        )
    except subprocess.TimeoutExpired:
        dest.unlink(missing_ok=True)
        return None, f"超过 {timeout} 秒，已放弃，不再重试"
    status_text = completed.stdout.decode("ascii", "replace").strip()
    status = int(status_text) if status_text.isdigit() else None
    detail = redact(completed.stderr.decode("utf-8", "replace")[:300])
    if completed.returncode != 0 or status != 200 or not dest.exists() or dest.stat().st_size == 0:
        dest.unlink(missing_ok=True)
        return status, detail or f"curl exit {completed.returncode}"
    return status, ""


def _probe_alfred(api_key: str) -> tuple[pl.DataFrame | None, list[dict], list[ManifestRecord], list[DownloadFailure]]:
    slot = ALFRED_SLOTS[0]
    series_id = slot["series_id"]
    public = public_observations_url(series_id, "2020-01-01", date.today().isoformat(), "2020-01-01", date.today().isoformat())
    secret = public + f"&api_key={api_key}"
    dest = RAW_DIR / "alfred" / f"{series_id}.observations.offset0.json"
    status, detail = _curl_once(secret, dest, 20)
    if status != 200:
        return None, [], [], [DownloadFailure("alfred", series_id, public, status, detail or "一次短请求失败")]
    payload = json.loads(dest.read_text(encoding="utf-8"))
    rows = payload.get("observations") or []
    starts = {row.get("realtime_start") for row in rows}
    if len(starts) < 2:
        dest.unlink(missing_ok=True)
        return None, [], [], [
            DownloadFailure(
                "alfred",
                series_id,
                public,
                200,
                "一次短请求返回了响应，但 realtime_start 没有区分 vintage。拒绝入库，避免把查询窗口当成发布日。不再重试。",
            )
        ]
    frame = observations_frame(rows, series_id, "alfred", "alfred")
    record = ManifestRecord(
        path=relpath(dest, ROOT),
        url=public,
        access_date=date.today().isoformat(),
        sha256=sha256_file(dest),
        original_unit=str(payload.get("units") or ""),
        original_frequency="Monthly",
        observation_date_min=rows[0]["date"] if rows else None,
        observation_date_max=rows[-1]["date"] if rows else None,
        release_date_rule=slot["release_rule"],
        license=FRED_LICENSE,
        series_id=series_id,
        source="alfred",
        http_status=200,
        row_count=len(rows),
        notes="一次短请求；没有另拉 series 元数据。",
    )
    present = frame.filter(pl.col("value").is_not_null())
    meta_row = {
        "series_id": series_id,
        "title_zh": slot["title_zh"],
        "title_en": series_id,
        "source": "alfred",
        "role": slot["role"],
        "unit": str(payload.get("units") or ""),
        "frequency": "Monthly",
        "price_metrics": False,
        "pit_mode": "alfred",
        "release_rule": slot["release_rule"],
        "stale": False,
        "notes": slot["notes"],
        "license": FRED_LICENSE,
        "seasonal_adjustment": "",
        "observation_start": str(present["observation_date"].min()) if present.height else None,
        "observation_end": str(present["observation_date"].max()) if present.height else None,
    }
    logger.info("alfred one-shot %s rows=%s vintages=%s", series_id, frame.height, len(starts))
    return frame, [meta_row], [record], []


def _probe_cftc() -> tuple[pl.DataFrame | None, list[ManifestRecord], list[DownloadFailure]]:
    url = "https://www.cftc.gov/files/dea/history/fut_disagg_txt_2025.zip"
    dest = RAW_DIR / "cftc" / "fut_disagg_txt_2025.zip"
    status, detail = _curl_once(url, dest, 20)
    if status != 200:
        return None, [], [DownloadFailure("cftc", "fut_disagg_txt_2025.zip", url, status, detail or "一次短请求失败")]
    try:
        frame = parse_cot_zip(dest.read_bytes(), "disagg", dest.name)
    except Exception as exc:
        logger.exception("CFTC 一次短请求已下载，但解析失败")
        return None, [
            ManifestRecord(
                path=relpath(dest, ROOT),
                url=url,
                access_date=date.today().isoformat(),
                sha256=sha256_file(dest),
                original_unit="contracts",
                original_frequency="Weekly",
                observation_date_min=None,
                observation_date_max=None,
                release_date_rule="文件已保存，解析失败，未入库。",
                license=CFTC_LICENSE,
                series_id="fut_disagg_txt_2025.zip",
                source="cftc",
                http_status=200,
                row_count=0,
                notes=str(exc)[:300],
            )
        ], [DownloadFailure("cftc", "fut_disagg_txt_2025.zip", url, 200, str(exc)[:300])]
    record = ManifestRecord(
        path=relpath(dest, ROOT),
        url=url,
        access_date=date.today().isoformat(),
        sha256=sha256_file(dest),
        original_unit="contracts",
        original_frequency="Weekly",
        observation_date_min=iso(frame["observation_date"].min()) if frame.height else None,
        observation_date_max=iso(frame["observation_date"].max()) if frame.height else None,
        release_date_rule="观测日来自文件；公布日按同周周五、遇周三至周五联邦假日顺延的规则计算。",
        license=CFTC_LICENSE,
        series_id="fut_disagg_txt_2025.zip",
        source="cftc",
        http_status=200,
        row_count=int(frame.height),
        notes="只请求了 2025 年 disaggregated 压缩包一次。金融期货文件未请求。",
    )
    if frame.is_empty():
        return None, [record], [DownloadFailure("cftc", "disagg_2025", url, 200, "压缩包里没有匹配到黄金或原油。不填充假持仓。")]
    logger.info("cftc one-shot rows=%s", frame.height)
    return frame, [record], []


def _accept_bundle(frames, meta_rows, records, slot: dict, bundle: dict, source: str, pit_mode: str) -> None:
    frames.append(bundle["frame"])
    records.append(bundle["meta_record"])
    records.extend(bundle["records"])
    meta_rows.append(_meta_row(slot, bundle, source, pit_mode))


def _gold_gaps() -> list[DownloadFailure]:
    """Gold files that are absent or only an error payload stay gaps. No new request."""
    failures: list[DownloadFailure] = []
    specs = (
        ("GOLDAMGBD228NLBM", "本地 meta 是错误响应，没有观测文件。本次不再重试。"),
        ("GOLDPMGBD228NLBM", "没有本地缓存。本次不再重试。"),
    )
    for series_id, missing_reason in specs:
        if _cached_pages(series_id, "fred"):
            continue
        meta_path = RAW_DIR / "fred" / f"{series_id}.meta.json"
        status = None
        reason = missing_reason
        if meta_path.exists():
            try:
                body = json.loads(meta_path.read_text(encoding="utf-8"))
            except json.JSONDecodeError:
                body = {}
            code = body.get("error_code")
            if code is not None and str(code).isdigit():
                status = int(code)
            if code is not None or "seriess" not in body:
                reason = "本地 meta 是错误响应，没有观测文件。本次不再重试。"
            else:
                reason = "只有 series 元数据，没有观测文件。本次不再重试。"
        failures.append(
            DownloadFailure("fred", series_id, public_series_url(series_id), status, reason)
        )
    return failures


def _local_alfred() -> tuple[list, list, list[ManifestRecord], list[DownloadFailure]]:
    frames: list = []
    meta_rows: list = []
    records: list[ManifestRecord] = []
    failures: list[DownloadFailure] = []
    for slot in ALFRED_SLOTS:
        series_id = slot["series_id"]
        public = public_observations_url(
            series_id,
            slot["observation_start"],
            date.today().isoformat(),
            slot["realtime_start"],
            date.today().isoformat(),
        )
        if not _cached_pages(series_id, "alfred"):
            failures.append(
                DownloadFailure(
                    "alfred",
                    series_id,
                    public,
                    0,
                    "没有本地 vintage 观测文件。上一次短请求超时。本次不再重试。",
                )
            )
            continue
        bundle = _bundle_from_cache(slot, series_id, "alfred", "alfred", "alfred")
        vintages = bundle["frame"]["realtime_start"].drop_nulls().n_unique()
        if vintages < 2:
            failures.append(
                DownloadFailure(
                    "alfred",
                    series_id,
                    public,
                    200,
                    "本地文件的 realtime_start 没有区分 vintage。拒绝入库，避免把查询窗口当成发布日。本次不再重试。",
                )
            )
            continue
        _accept_bundle(frames, meta_rows, records, slot, bundle, "alfred", "alfred")
        logger.info("local alfred %s rows=%s vintages=%s", series_id, bundle["frame"].height, vintages)
    return frames, meta_rows, records, failures


def _local_cftc() -> tuple[pl.DataFrame | None, list[ManifestRecord], list[DownloadFailure]]:
    frames: list[pl.DataFrame] = []
    records: list[ManifestRecord] = []
    failures: list[DownloadFailure] = []
    for family, name, url in CFTC_LOCAL:
        dest = RAW_DIR / "cftc" / name
        if not dest.exists() or dest.stat().st_size == 0:
            failures.append(DownloadFailure("cftc", name, url, None, "本地没有这个压缩包。本次不再重试。"))
            continue
        try:
            frame = parse_cot_zip(dest.read_bytes(), family, dest.name)
        except Exception as exc:
            logger.exception("CFTC 本地解析失败 file=%s", dest.name)
            failures.append(DownloadFailure("cftc", name, url, 200, f"本地压缩包解析失败：{exc}"[:300]))
            continue
        records.append(
            ManifestRecord(
                path=relpath(dest, ROOT),
                url=url,
                access_date=date.fromtimestamp(dest.stat().st_mtime).isoformat(),
                sha256=sha256_file(dest),
                original_unit="contracts",
                original_frequency="Weekly",
                observation_date_min=iso(frame["observation_date"].min()) if frame.height else None,
                observation_date_max=iso(frame["observation_date"].max()) if frame.height else None,
                release_date_rule="观测日来自文件；公布日按同周周五、遇周三至周五联邦假日顺延的规则计算。观测日不是公布日。",
                license=CFTC_LICENSE,
                series_id=name,
                source="cftc",
                http_status=200,
                row_count=int(frame.height),
                notes="只读取已经保存在本地的压缩包，没有重新下载。",
            )
        )
        if frame.height:
            frames.append(frame)
        else:
            failures.append(DownloadFailure("cftc", name, url, 200, "压缩包里没有匹配到目标市场。不填充假持仓。"))
    if not frames:
        return None, records, failures
    positions = (
        pl.concat(frames, how="vertical")
        .unique(subset=["market_id", "observation_date"], keep="last")
        .sort(["market_id", "observation_date"])
    )
    logger.info("local cftc rows=%s markets=%s", positions.height, positions["market_id"].unique().to_list())
    return positions, records, failures


def assemble_cached() -> int:
    """Rebuild DuckDB from files already on disk. Does not call FRED, ALFRED, or CFTC."""
    setup_logging()
    ensure_dirs()
    frames = []
    meta_rows = []
    records: list[ManifestRecord] = []
    failures: list[DownloadFailure] = []
    ingested = list(CACHED_SERIES)
    for series_id in CACHED_SERIES:
        slot = _slot(series_id)
        bundle = _bundle_from_cache(slot, series_id, "fred", "fred", "observation_date")
        _accept_bundle(frames, meta_rows, records, slot, bundle, "fred", "observation_date")
        logger.info(
            "cache %s rows=%s %s -> %s",
            series_id,
            bundle["frame"].height,
            bundle["first"],
            bundle["last"],
        )
    for series_id in EXTRA_LOCAL_FRED:
        if not _cached_pages(series_id, "fred"):
            failures.append(
                DownloadFailure(
                    "fred",
                    series_id,
                    public_observations_url(series_id, "2010-01-01", date.today().isoformat()),
                    None,
                    "本地没有完整观测文件。本次不再重试。",
                )
            )
            continue
        slot = _slot(series_id)
        bundle = _bundle_from_cache(slot, series_id, "fred", "fred", "observation_date")
        _accept_bundle(frames, meta_rows, records, slot, bundle, "fred", "observation_date")
        if series_id == "BAMLC0A0CM":
            meta_rows[-1]["notes"] += " 本地文件从 2023-10-10 开始，不是 2010 年以来的全样本。本次不补请求。"
        if series_id == "SP500":
            meta_rows[-1]["notes"] += " 本地 SP500 文件从 2016-10-13 起，短于其他日频序列。本次不补请求。"
        ingested.append(series_id)
        logger.info("local fred %s rows=%s %s -> %s", series_id, bundle["frame"].height, bundle["first"], bundle["last"])
    failures.extend(_gold_gaps())
    alfred_frames, alfred_meta, alfred_records, alfred_failures = _local_alfred()
    frames.extend(alfred_frames)
    meta_rows.extend(alfred_meta)
    records.extend(alfred_records)
    failures.extend(alfred_failures)
    ingested.extend(row["series_id"] for row in alfred_meta)
    positions, cftc_records, cftc_failures = _local_cftc()
    records.extend(cftc_records)
    failures.extend(cftc_failures)
    observations = pl.concat(frames, how="vertical")
    meta = pl.DataFrame(meta_rows)
    _clear_derived_parquet()
    for series_id in observations["series_id"].unique().to_list():
        write_parquet(observations.filter(pl.col("series_id") == series_id), PARQUET_DIR / "observations" / f"{series_id}.parquet")
    if positions is not None and positions.height:
        write_parquet(positions, PARQUET_DIR / "cftc" / "positions.parquet")
    else:
        positions = pl.DataFrame()
    rebuild_database(observations, positions if positions is not None else pl.DataFrame(), meta, records)
    connection = connect_readonly()
    try:
        quality = build_quality_report(connection, date.today())
    finally:
        connection.close()
    QUALITY_JSON.write_text(json.dumps(quality, ensure_ascii=False, indent=2, default=str), encoding="utf-8")
    FAILURES_JSON.write_text(json.dumps([item.to_dict() for item in failures], ensure_ascii=False, indent=2), encoding="utf-8")
    DECISIONS_JSON.write_text(
        json.dumps(
            {
                "mode": "local_cache_only",
                "cached": ingested,
                "blocked_without_retry": [item.series_id for item in failures],
                "previous_five_probe_failures": {
                    "DCOILWTICO": "磁盘上已有完整观测文件，本次只读入库，没有重新请求。",
                    "SP500": "磁盘上已有完整观测文件，本次只读入库，没有重新请求。",
                    "GOLDAMGBD228NLBM": "仍为缺口。本地 meta 不是有效序列响应，没有观测文件。",
                    "GOLDPMGBD228NLBM": "仍为缺口。没有本地文件。",
                    "UNRATE": "仍为缺口。只有 series 元数据，没有 vintage 观测文件。",
                },
                "bis": BisSdmxClient().describe(),
            },
            ensure_ascii=False,
            indent=2,
        ),
        encoding="utf-8",
    )
    logger.info("cache store ready series=%s rows=%s failures=%s", meta.height, observations.height, len(failures))
    return 0
