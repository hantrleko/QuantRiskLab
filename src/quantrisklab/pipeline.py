"""Download a small real sample, then build the DuckDB point-in-time store."""

from __future__ import annotations

import json
import logging
import zipfile
from datetime import date
from pathlib import Path

import polars as pl

from quantrisklab.catalog import (
    ALFRED_SLOTS,
    CFTC_FILES,
    CFTC_LICENSE,
    CFTC_MARKETS,
    CFTC_YEARS,
    FRED_LICENSE,
    FRED_SLOTS,
)
from quantrisklab.fred_key import ensure_fred_api_key
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
from quantrisklab.quality.checks import build_quality_report
from quantrisklab.sources.bis import BisSdmxClient
from quantrisklab.sources.cftc import cftc_release_date, parse_cot_zip
from quantrisklab.sources.fred import FredClient, FredError, public_observations_url
from quantrisklab.sources.http_util import (
    DownloadFailure,
    ManifestRecord,
    iso,
    redact,
    relpath,
    request_bytes,
    sha256_bytes,
    sha256_file,
    write_bytes,
)
from quantrisklab.store.database import connect_readonly, rebuild_database, write_parquet

logger = logging.getLogger("quantrisklab.pipeline")


def _cached_pages(series_id: str, subdir: str) -> list[Path] | None:
    meta_path = RAW_DIR / "fred" / f"{series_id}.meta.json"
    pages = sorted((RAW_DIR / subdir).glob(f"{series_id}.observations.offset*.json"))
    if not meta_path.exists() or not pages:
        return None
    got = 0
    total = 0
    for page in pages:
        try:
            body = json.loads(page.read_text(encoding="utf-8"))
        except json.JSONDecodeError:
            return None
        batch = body.get("observations") or []
        got += len(batch)
        total = int(body.get("count") or total)
    if got < total or got == 0:
        return None
    return pages


def _bundle_from_cache(slot: dict, series_id: str, subdir: str, source: str, pit_mode: str) -> dict:
    from quantrisklab.sources.fred import observations_frame, public_observations_url, public_series_url

    meta_path = RAW_DIR / "fred" / f"{series_id}.meta.json"
    meta = json.loads(meta_path.read_text(encoding="utf-8"))["seriess"][0]
    pages = _cached_pages(series_id, subdir) or []
    rows: list[dict] = []
    records: list[ManifestRecord] = []
    frequency = str(meta.get("frequency") or "")
    unit = str(meta.get("units") or "")
    records.append(
        ManifestRecord(
            path=relpath(meta_path, ROOT),
            url=public_series_url(series_id),
            access_date=date.fromtimestamp(meta_path.stat().st_mtime).isoformat(),
            sha256=sha256_file(meta_path),
            original_unit=unit,
            original_frequency=frequency,
            observation_date_min=meta.get("observation_start"),
            observation_date_max=meta.get("observation_end"),
            release_date_rule="元数据文件，不含观测发布日。",
            license=FRED_LICENSE,
            series_id=series_id,
            source=source,
            http_status=200,
            row_count=1,
            notes=(meta.get("title") or "")[:500],
        )
    )
    for page in pages:
        body = json.loads(page.read_text(encoding="utf-8"))
        batch = body.get("observations") or []
        rows.extend(batch)
        records.append(
            ManifestRecord(
                path=relpath(page, ROOT),
                url=public_observations_url(series_id, slot["observation_start"], date.today().isoformat()),
                access_date=date.fromtimestamp(page.stat().st_mtime).isoformat(),
                sha256=sha256_file(page),
                original_unit=unit,
                original_frequency=frequency,
                observation_date_min=batch[0]["date"] if batch else None,
                observation_date_max=batch[-1]["date"] if batch else None,
                release_date_rule=slot["release_rule"],
                license=FRED_LICENSE,
                series_id=series_id,
                source=source,
                http_status=200,
                row_count=len(batch),
                notes="resumed from saved response",
            )
        )
    frame = observations_frame(rows, series_id, source, pit_mode)
    present = frame.filter(pl.col("value").is_not_null())
    first = present["observation_date"].min()
    last = present["observation_date"].max()
    stale = (date.today() - last).days > _fresh_limit(frequency)
    return {
        "series_id": series_id,
        "meta": meta,
        "meta_record": records[0],
        "frame": frame,
        "records": records[1:],
        "stale": stale,
        "first": first,
        "last": last,
        "frequency": frequency,
        "unit": unit,
    }

EQUITY_TITLES = {
    "SP500": "标普500价格指数",
    "WILL5000PRFC": "威尔希尔5000全市值价格指数",
    "WILL5000PR": "威尔希尔5000价格指数",
    "NASDAQCOM": "纳斯达克综合指数",
    "DJIA": "道琼斯工业平均指数",
}
GOLD_TITLES = {
    "GOLDAMGBD228NLBM": "伦敦金上午定盘价",
    "GOLDPMGBD228NLBM": "伦敦金下午定盘价",
}
CREDIT_TITLES = {
    "BAMLC0A0CM": "美国公司债 OAS",
    "BAA10Y": "Baa 与 10 年国债利差",
}
SERIES_LIMITATIONS = {
    "SP500": "标普道琼斯指数的价格指数，不含股息。FRED 转载受指数供应商条款约束。",
    "WILL5000PRFC": "威尔希尔5000全市值价格指数，不是全收益指数。",
    "WILL5000PR": "威尔希尔5000价格指数。若官方已停更，样本止于最后观测日。",
    "NASDAQCOM": "纳斯达克综合价格指数，不含股息。",
    "DJIA": "道琼斯工业平均价格指数，不含股息。",
    "GOLDAMGBD228NLBM": "伦敦金银市场上午定盘价（美元/金衡盎司）。",
    "GOLDPMGBD228NLBM": "伦敦金银市场下午定盘价（美元/金衡盎司）。",
    "DCOILWTICO": "库欣 WTI 现货，美元/桶。现货收益不含期货展期。",
    "BAMLC0A0CM": "ICE BofA 美国公司债期权调整利差，百分点。",
    "BAA10Y": "穆迪 Baa 公司债收益率减去 10 年国债收益率，百分点。",
}


def _fresh_limit(frequency: str) -> int:
    freq = (frequency or "").lower()
    if freq.startswith("daily") or freq.startswith("week"):
        return 21
    if freq.startswith("month"):
        return 75
    return 120


def _title_zh(slot: dict, series_id: str) -> str:
    return EQUITY_TITLES.get(series_id) or GOLD_TITLES.get(series_id) or CREDIT_TITLES.get(series_id) or slot["title_zh"]


def _failure_from_exception(source: str, series_id: str, url: str, exc: Exception) -> DownloadFailure:
    status = exc.status if isinstance(exc, FredError) else None
    return DownloadFailure(source, series_id, url, status, str(exc)[:500])


def _select_fred_slot(client: FredClient, slot: dict, observation_end: str) -> tuple[dict | None, list[dict]]:
    attempts: list[dict] = []
    stale_best: dict | None = None
    for series_id in slot["candidates"]:
        url = public_observations_url(series_id, slot["observation_start"], observation_end)
        logger.info("requesting fred slot=%s series=%s", slot["slot"], series_id)
        if _cached_pages(series_id, "fred"):
            bundle = _bundle_from_cache(slot, series_id, "fred", "fred", "observation_date")
            logger.info(
                "resume fred series=%s rows=%s %s -> %s stale=%s",
                series_id,
                bundle["frame"].height,
                bundle["first"],
                bundle["last"],
                bundle["stale"],
            )
            attempts.append(
                {
                    "series_id": series_id,
                    "ok": True,
                    "stale": bundle["stale"],
                    "start": bundle["first"].isoformat(),
                    "end": bundle["last"].isoformat(),
                    "rows": int(bundle["frame"].height),
                    "frequency": bundle["frequency"],
                    "unit": bundle["unit"],
                    "url": url,
                    "resumed": True,
                }
            )
            if not bundle["stale"] or not slot["prefer_fresh"]:
                return bundle, attempts
            if stale_best is None or bundle["last"] > stale_best["last"]:
                stale_best = bundle
            continue
        error_meta = RAW_DIR / "fred" / f"{series_id}.meta.json"
        if error_meta.exists():
            try:
                saved = json.loads(error_meta.read_text(encoding="utf-8"))
            except json.JSONDecodeError:
                saved = {}
            if saved.get("error_code"):
                message = str(saved.get("error_message") or "官方接口拒绝该序列")
                attempts.append(
                    {
                        "series_id": series_id,
                        "ok": False,
                        "error": message,
                        "url": url,
                        "http_status": int(saved.get("error_code") or 0),
                    }
                )
                logger.error("FRED 已记录的失败不再重试 series=%s status=%s", series_id, saved.get("error_code"))
                continue
        try:
            meta, meta_record = client.fetch_metadata(series_id)
            frame, records, _summary = client.fetch_observations(
                series_id=series_id,
                observation_start=slot["observation_start"],
                observation_end=observation_end,
                source="fred",
                pit_mode="observation_date",
                release_rule=slot["release_rule"],
                license_text=FRED_LICENSE,
            )
        except Exception as exc:
            logger.exception("FRED 序列下载失败 slot=%s series=%s", slot["slot"], series_id)
            attempts.append(
                {
                    "series_id": series_id,
                    "ok": False,
                    "error": str(exc)[:400],
                    "url": getattr(exc, "url", url),
                    "http_status": getattr(exc, "status", None),
                }
            )
            continue
        frequency = str(meta.get("frequency") or "")
        unit = str(meta.get("units") or "")
        for record in records:
            record.original_frequency = frequency
            record.original_unit = unit or record.original_unit
        present = frame.filter(pl.col("value").is_not_null())
        if present.is_empty():
            attempts.append({"series_id": series_id, "ok": False, "error": "官方响应没有非缺失观测", "url": url})
            continue
        last = present["observation_date"].max()
        first = present["observation_date"].min()
        stale = (date.today() - last).days > _fresh_limit(frequency)
        attempts.append(
            {
                "series_id": series_id,
                "ok": True,
                "stale": stale,
                "start": first.isoformat(),
                "end": last.isoformat(),
                "rows": int(present.height),
                "frequency": frequency,
                "unit": unit,
                "url": url,
            }
        )
        bundle = {
            "series_id": series_id,
            "meta": meta,
            "meta_record": meta_record,
            "frame": frame,
            "records": records,
            "stale": stale,
            "first": first,
            "last": last,
            "frequency": frequency,
            "unit": unit,
        }
        if not stale or not slot["prefer_fresh"]:
            return bundle, attempts
        if stale_best is None or last > stale_best["last"]:
            stale_best = bundle
    if stale_best is not None:
        return stale_best, attempts
    return None, attempts


def _meta_row(slot: dict, bundle: dict, source: str, pit_mode: str) -> dict:
    series_id = bundle["series_id"]
    notes = slot["notes"]
    if series_id != slot.get("candidates", [series_id])[0]:
        notes += f" 本槽位实际采用 {series_id}。"
    limitation = SERIES_LIMITATIONS.get(series_id)
    if limitation:
        notes += " " + limitation
    if bundle["stale"]:
        notes += " 官方序列已滞后或停更。只使用已发布的真实观测，不向前填充。"
    fred_notes = (bundle["meta"].get("notes") or "").replace("\n", " ")
    if fred_notes:
        notes += " FRED notes: " + fred_notes[:280]
    return {
        "series_id": series_id,
        "title_zh": _title_zh(slot, series_id),
        "title_en": str(bundle["meta"].get("title") or ""),
        "source": source,
        "role": slot["role"],
        "unit": bundle["unit"],
        "frequency": bundle["frequency"],
        "price_metrics": bool(slot["price_metrics"]),
        "pit_mode": pit_mode,
        "release_rule": slot["release_rule"],
        "stale": bool(bundle["stale"]),
        "notes": notes.strip(),
        "license": FRED_LICENSE,
        "seasonal_adjustment": str(bundle["meta"].get("seasonal_adjustment") or ""),
        "observation_start": bundle["first"].isoformat(),
        "observation_end": bundle["last"].isoformat(),
    }


def download_fred(client: FredClient, observation_end: str) -> tuple[list[pl.DataFrame], list[dict], list[ManifestRecord], list[dict], list[DownloadFailure]]:
    frames: list[pl.DataFrame] = []
    meta_rows: list[dict] = []
    records: list[ManifestRecord] = []
    decisions: list[dict] = []
    failures: list[DownloadFailure] = []
    for slot in FRED_SLOTS:
        bundle, attempts = _select_fred_slot(client, slot, observation_end)
        decisions.append({"slot": slot["slot"], "chosen": None if bundle is None else bundle["series_id"], "attempts": attempts})
        if bundle is None:
            for attempt in attempts:
                failures.append(
                    DownloadFailure(
                        "fred",
                        attempt["series_id"],
                        attempt.get("url") or "",
                        attempt.get("http_status"),
                        attempt.get("error") or "候选序列不可用",
                    )
                )
            logger.error("FRED 槽位没有可用序列 slot=%s", slot["slot"])
            continue
        for attempt in attempts:
            if not attempt.get("ok"):
                failures.append(
                    DownloadFailure(
                        "fred",
                        attempt["series_id"],
                        attempt.get("url") or "",
                        attempt.get("http_status"),
                        attempt.get("error") or "下载失败",
                    )
                )
        frames.append(bundle["frame"])
        records.append(bundle["meta_record"])
        records.extend(bundle["records"])
        meta_rows.append(_meta_row(slot, bundle, "fred", "observation_date"))
        logger.info(
            "selected fred slot=%s series=%s rows=%s %s -> %s stale=%s",
            slot["slot"],
            bundle["series_id"],
            bundle["frame"].height,
            bundle["first"],
            bundle["last"],
            bundle["stale"],
        )
    return frames, meta_rows, records, decisions, failures


def download_alfred(client: FredClient, observation_end: str) -> tuple[list[pl.DataFrame], list[dict], list[ManifestRecord], list[dict], list[DownloadFailure]]:
    frames: list[pl.DataFrame] = []
    meta_rows: list[dict] = []
    records: list[ManifestRecord] = []
    decisions: list[dict] = []
    failures: list[DownloadFailure] = []
    for slot in ALFRED_SLOTS:
        series_id = slot["series_id"]
        url = public_observations_url(
            series_id,
            slot["observation_start"],
            observation_end,
            slot["realtime_start"],
            observation_end,
        )
        cached = _cached_pages(series_id, "alfred")
        if cached:
            loaded = _bundle_from_cache(slot, series_id, "alfred", "alfred", "alfred")
            meta = loaded["meta"]
            meta_record = loaded["meta_record"]
            frame = loaded["frame"]
            obs_records = loaded["records"]
            logger.info("resume alfred series=%s rows=%s", series_id, frame.height)
        else:
            try:
                meta, meta_record = client.fetch_metadata(series_id)
                frame, obs_records, _summary = client.fetch_observations(
                    series_id=series_id,
                    observation_start=slot["observation_start"],
                    observation_end=observation_end,
                    source="alfred",
                    pit_mode="alfred",
                    realtime_start=slot["realtime_start"],
                    realtime_end=observation_end,
                    release_rule=slot["release_rule"],
                    license_text=FRED_LICENSE,
                    raw_subdir="alfred",
                )
            except Exception as exc:
                logger.exception("ALFRED 下载失败 series=%s", series_id)
                failures.append(_failure_from_exception("alfred", series_id, getattr(exc, "url", url), exc))
                decisions.append({"slot": slot["slot"], "chosen": None, "error": str(exc)[:400], "url": getattr(exc, "url", url)})
                continue
        frequency = str(meta.get("frequency") or "")
        unit = str(meta.get("units") or "")
        for record in obs_records:
            record.original_frequency = frequency
            record.original_unit = unit or record.original_unit
            record.source = "alfred"
        meta_record.source = "alfred"
        present = frame.filter(pl.col("value").is_not_null())
        if present.is_empty():
            failures.append(DownloadFailure("alfred", series_id, url, 200, "vintage 响应没有非缺失观测"))
            decisions.append({"slot": slot["slot"], "chosen": None, "error": "empty"})
            continue
        revised = (
            present.group_by("observation_date")
            .agg(pl.col("value").n_unique().alias("n_values"))
            .filter(pl.col("n_values") > 1)
            .height
        )
        bundle = {
            "series_id": series_id,
            "meta": meta,
            "stale": False,
            "first": present["observation_date"].min(),
            "last": present["observation_date"].max(),
            "frequency": frequency,
            "unit": unit,
        }
        slot_for_meta = dict(slot)
        slot_for_meta["candidates"] = [series_id]
        meta_rows.append(_meta_row(slot_for_meta, bundle, "alfred", "alfred"))
        if revised == 0:
            meta_rows[-1]["notes"] += " 警告：下载到的 vintage 里没有看到同一观测月的不同数值，点时修订检验可能缺少材料。"
            logger.error("ALFRED series=%s 没有检测到修订", series_id)
        frames.append(frame)
        records.append(meta_record)
        records.extend(obs_records)
        decisions.append(
            {
                "slot": slot["slot"],
                "chosen": series_id,
                "rows": int(frame.height),
                "revised_observations": int(revised),
                "start": bundle["first"].isoformat(),
                "end": bundle["last"].isoformat(),
                "url": url,
            }
        )
        logger.info("selected alfred series=%s vintage_rows=%s revised_months=%s", series_id, frame.height, revised)
    return frames, meta_rows, records, decisions, failures


def download_cftc() -> tuple[pl.DataFrame, list[ManifestRecord], list[DownloadFailure], dict]:
    records: list[ManifestRecord] = []
    failures: list[DownloadFailure] = []
    frames: list[pl.DataFrame] = []
    try:
        for family, template in CFTC_FILES.items():
            for year in CFTC_YEARS:
                url = template.format(year=year)
                filename = url.rsplit("/", 1)[-1]
                path = RAW_DIR / "cftc" / filename
                if path.exists() and zipfile.is_zipfile(path):
                    payload = path.read_bytes()
                    status = 200
                    logger.info("resume cftc file=%s bytes=%s", filename, len(payload))
                else:
                    try:
                        response = request_bytes(url, timeout=180.0)
                    except Exception as exc:
                        logger.exception("CFTC 下载失败 url=%s", url)
                        failures.append(DownloadFailure("cftc", filename, url, None, redact(str(exc))[:400]))
                        continue
                    payload = response.content
                    status = response.status_code
                    write_bytes(path, payload)
                record = ManifestRecord(
                    path=relpath(path, ROOT),
                    url=url,
                    access_date=date.fromtimestamp(path.stat().st_mtime).isoformat(),
                    sha256=sha256_bytes(payload),
                    original_unit="contracts",
                    original_frequency="Weekly",
                    observation_date_min=None,
                    observation_date_max=None,
                    release_date_rule=(
                        "观测日是持仓报告日（通常为周二），不是公布日。"
                        "公布日按 CFTC 规则取同周周五；若周三至周五遇美国联邦假日，则顺延到下一个营业日。"
                        "规则已对照 2026 年官方发布日历。"
                    ),
                    license=CFTC_LICENSE,
                    series_id=filename,
                    source="cftc",
                    http_status=status,
                    row_count=0,
                    notes=family,
                )
                if status != 200:
                    record.notes = f"{family}; HTTP {status}"
                    records.append(record)
                    failures.append(DownloadFailure("cftc", filename, url, status, str(status)))
                    continue
                try:
                    frame = parse_cot_zip(payload, family, filename)
                except Exception as exc:
                    logger.exception("CFTC 解析失败 file=%s", filename)
                    record.notes = f"{family}; 解析失败: {exc}"[:500]
                    records.append(record)
                    failures.append(DownloadFailure("cftc", filename, url, status, str(exc)[:400]))
                    continue
                record.row_count = int(frame.height)
                if frame.height:
                    record.observation_date_min = iso(frame["observation_date"].min())
                    record.observation_date_max = iso(frame["observation_date"].max())
                records.append(record)
                if frame.height:
                    frames.append(frame)
    finally:
        pass

    if not frames:
        positions = pl.DataFrame(
            schema={
                "market_id": pl.Utf8,
                "market_name": pl.Utf8,
                "title_zh": pl.Utf8,
                "report_family": pl.Utf8,
                "position_group": pl.Utf8,
                "position_group_zh": pl.Utf8,
                "observation_date": pl.Date,
                "release_date": pl.Date,
                "open_interest": pl.Float64,
                "long_positions": pl.Float64,
                "short_positions": pl.Float64,
                "net_positions": pl.Float64,
                "net_over_oi": pl.Float64,
                "source_file": pl.Utf8,
            }
        )
    else:
        positions = pl.concat(frames, how="vertical")
        positions = positions.sort(["market_id", "observation_date", "source_file"]).unique(
            subset=["market_id", "observation_date"],
            keep="last",
        )
    if positions.height:
        leaked = positions.filter(pl.col("release_date") <= pl.col("observation_date"))
        if leaked.height:
            raise RuntimeError(f"CFTC 发布日没有晚于观测日的行数：{leaked.height}")
    found = set(positions["market_id"].unique().to_list()) if positions.height else set()
    for market_id, spec in CFTC_MARKETS.items():
        if market_id not in found:
            failures.append(
                DownloadFailure(
                    "cftc",
                    market_id,
                    "https://www.cftc.gov/files/dea/history/",
                    200,
                    f"压缩包已处理，但没有匹配到 {spec['title_zh']}。不填充假持仓。",
                )
            )
    decision = {
        "markets": sorted(found),
        "rows": int(positions.height),
        "start": iso(positions["observation_date"].min()) if positions.height else None,
        "end": iso(positions["observation_date"].max()) if positions.height else None,
    }
    return positions, records, failures, decision


def _clear_derived_parquet() -> None:
    for folder in (PARQUET_DIR / "observations", PARQUET_DIR / "cftc"):
        folder.mkdir(parents=True, exist_ok=True)
        for path in folder.glob("*.parquet"):
            path.unlink()


def run() -> int:
    setup_logging()
    ensure_dirs()
    ensure_fred_api_key()
    observation_end = date.today().isoformat()
    logger.info("QuantRiskLab download start observation_end=%s", observation_end)
    bis_note = BisSdmxClient().describe()
    failures: list[DownloadFailure] = []
    decisions: dict = {"bis": bis_note}
    try:
        with FredClient() as client:
            fred_frames, fred_meta, fred_records, fred_decisions, fred_failures = download_fred(client, observation_end)
            alfred_frames, alfred_meta, alfred_records, alfred_decisions, alfred_failures = download_alfred(
                client, observation_end
            )
    except Exception:
        logger.exception("数据下载过程失败")
        raise
    failures.extend(fred_failures)
    failures.extend(alfred_failures)
    decisions["fred"] = fred_decisions
    decisions["alfred"] = alfred_decisions
    positions, cftc_records, cftc_failures, cftc_decision = download_cftc()
    failures.extend(cftc_failures)
    decisions["cftc"] = cftc_decision

    frames = fred_frames + alfred_frames
    if not frames:
        FAILURES_JSON.write_text(
            json.dumps([item.to_dict() for item in failures], ensure_ascii=False, indent=2),
            encoding="utf-8",
        )
        DECISIONS_JSON.write_text(json.dumps(decisions, ensure_ascii=False, indent=2), encoding="utf-8")
        logger.error("没有任何真实序列被写入")
        return 1

    observations = pl.concat(frames, how="vertical")
    meta = pl.DataFrame(fred_meta + alfred_meta)
    _clear_derived_parquet()
    for series_id in observations["series_id"].unique().to_list():
        frame = observations.filter(pl.col("series_id") == series_id)
        write_parquet(frame, PARQUET_DIR / "observations" / f"{series_id}.parquet")
    if positions.height:
        write_parquet(positions, PARQUET_DIR / "cftc" / "positions.parquet")
    manifest = fred_records + alfred_records + cftc_records
    rebuild_database(observations, positions, meta, manifest)
    connection = connect_readonly()
    try:
        quality = build_quality_report(connection, date.today())
    finally:
        connection.close()
    QUALITY_JSON.write_text(json.dumps(quality, ensure_ascii=False, indent=2, default=str), encoding="utf-8")
    FAILURES_JSON.write_text(
        json.dumps([item.to_dict() for item in failures], ensure_ascii=False, indent=2),
        encoding="utf-8",
    )
    DECISIONS_JSON.write_text(json.dumps(decisions, ensure_ascii=False, indent=2, default=str), encoding="utf-8")
    logger.info(
        "store ready series=%s observation_rows=%s cftc_rows=%s failures=%s",
        meta.height,
        observations.height,
        positions.height,
        len(failures),
    )
    for row in meta.iter_rows(named=True):
        logger.info(
            "series %s %s %s %s -> %s freq=%s",
            row["series_id"],
            row["title_zh"],
            row["source"],
            row["observation_start"],
            row["observation_end"],
            row["frequency"],
        )
    return 0


def main() -> int:
    try:
        return run()
    except Exception:
        logging.getLogger("quantrisklab.pipeline").exception("reproduce failed")
        return 1
