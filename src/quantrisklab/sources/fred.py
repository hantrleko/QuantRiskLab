"""FRED latest-vintage downloads. realtime_start on these pulls is not a release date."""

from __future__ import annotations

import json
import logging
import os
import urllib.error
import urllib.parse
import urllib.request
from datetime import date, datetime
from urllib.parse import urlencode

import polars as pl

from quantrisklab.fred_key import require_fred_api_key
from quantrisklab.paths import RAW_DIR, ROOT
from quantrisklab.sources.http_util import (
    ManifestRecord,
    relpath,
    sha256_bytes,
    write_bytes,
)

logger = logging.getLogger("quantrisklab.fred")

FRED_SERIES_URL = "https://api.stlouisfed.org/fred/series"
FRED_OBS_URL = "https://api.stlouisfed.org/fred/series/observations"
PAGE_LIMIT = 10000


def public_series_url(series_id: str) -> str:
    return f"{FRED_SERIES_URL}?{urlencode({'series_id': series_id, 'file_type': 'json'})}"


def public_observations_url(
    series_id: str,
    observation_start: str,
    observation_end: str,
    realtime_start: str | None = None,
    realtime_end: str | None = None,
    offset: int | None = None,
) -> str:
    query = {
        "series_id": series_id,
        "file_type": "json",
        "observation_start": observation_start,
        "observation_end": observation_end,
    }
    if realtime_start:
        query["realtime_start"] = realtime_start
        query["realtime_end"] = realtime_end or date.today().isoformat()
    if offset:
        query["offset"] = str(offset)
        query["limit"] = str(PAGE_LIMIT)
    return f"{FRED_OBS_URL}?{urlencode(query)}"


def _parse_value(raw: str | None) -> float | None:
    if raw is None or raw in {"", "."}:
        return None
    return float(raw)


def observations_frame(
    rows: list[dict],
    series_id: str,
    source: str,
    pit_mode: str,
) -> pl.DataFrame:
    """Build the observation table.

    pit_mode=observation_date: market and yield series without vintages.
    pit_mode=alfred: each row's realtime_start is the release date.
    """
    schema = {
        "series_id": pl.Utf8,
        "source": pl.Utf8,
        "observation_date": pl.Date,
        "release_date": pl.Date,
        "value": pl.Float64,
        "realtime_start": pl.Date,
        "realtime_end": pl.Date,
    }
    parsed: list[dict] = []
    for row in rows:
        obs = datetime.strptime(row["date"], "%Y-%m-%d").date()
        realtime_start = datetime.strptime(row["realtime_start"], "%Y-%m-%d").date()
        realtime_end = datetime.strptime(row["realtime_end"], "%Y-%m-%d").date()
        if pit_mode == "alfred":
            release = realtime_start
            stored_start = realtime_start
            stored_end = realtime_end
        elif pit_mode == "observation_date":
            release = obs
            stored_start = None
            stored_end = None
        else:
            raise ValueError(f"未知 pit_mode: {pit_mode}")
        parsed.append(
            {
                "series_id": series_id,
                "source": source,
                "observation_date": obs,
                "release_date": release,
                "value": _parse_value(row.get("value")),
                "realtime_start": stored_start,
                "realtime_end": stored_end,
            }
        )
    if not parsed:
        return pl.DataFrame(schema=schema)
    return pl.DataFrame(parsed, schema=schema).sort(["observation_date", "release_date"])


class _HttpResult:
    def __init__(self, status_code: int, content: bytes) -> None:
        self.status_code = status_code
        self.content = content


class FredClient:
    def __init__(self, api_key: str | None = None) -> None:
        self.api_key = api_key or require_fred_api_key()

    def close(self) -> None:
        return None

    def __enter__(self) -> FredClient:
        return self

    def __exit__(self, exc_type, exc, traceback) -> None:
        self.close()

    def _get(self, url: str, params: dict):
        import shutil
        import subprocess
        import tempfile
        import time

        query = dict(params)
        query["api_key"] = self.api_key
        target = f"{url}?{urllib.parse.urlencode(query)}"
        curl = shutil.which("curl.exe") or shutil.which("curl")
        if curl:
            return self._curl(curl, target, str(params.get("series_id") or ""))
        last_error: Exception | None = None
        for attempt in range(2):
            request = urllib.request.Request(
                target,
                headers={"Accept": "application/json", "User-Agent": "QuantRiskLab/0.1 research"},
            )
            try:
                with urllib.request.urlopen(request, timeout=90) as response:
                    return _HttpResult(response.status, response.read())
            except urllib.error.HTTPError as exc:
                body = exc.read()
                if exc.code in {429, 500, 502, 503, 504} and attempt == 0:
                    time.sleep(2)
                    continue
                return _HttpResult(exc.code, body)
            except (urllib.error.URLError, TimeoutError, ConnectionError) as exc:
                last_error = exc
                logger.error("FRED 连接失败 attempt=%s detail=%s", attempt + 1, _REDACT_INLINE(str(exc)))
                time.sleep(1)
        raise FredError(str(params.get("series_id") or ""), url, 0, _REDACT_INLINE(str(last_error)))

    def _curl(self, curl: str, target: str, series_id: str):
        import subprocess
        import tempfile

        descriptor, path_name = tempfile.mkstemp(suffix=".json")
        os.close(descriptor)
        config = f'url = "{target}"\n'
        try:
            completed = subprocess.run(
                [
                    curl,
                    "--max-time",
                    "90",
                    "-sS",
                    "-A",
                    "QuantRiskLab/0.1 research",
                    "-o",
                    path_name,
                    "-w",
                    "%{http_code}",
                    "-K",
                    "-",
                ],
                input=config.encode("utf-8"),
                capture_output=True,
                check=False,
            )
            with open(path_name, "rb") as handle:
                content = handle.read()
            status_text = completed.stdout.decode("ascii", "replace").strip() or "0"
            status = int(status_text) if status_text.isdigit() else 0
            if completed.returncode != 0 and status == 0:
                detail = _REDACT_INLINE(completed.stderr.decode("utf-8", "replace")[:300])
                raise FredError(series_id, target.split("?")[0], status, detail or "curl failed")
            return _HttpResult(status, content)
        finally:
            try:
                os.remove(path_name)
            except OSError:
                pass

    def fetch_metadata(self, series_id: str) -> tuple[dict, ManifestRecord]:
        url = public_series_url(series_id)
        response = self._get(FRED_SERIES_URL, {"series_id": series_id, "file_type": "json"})
        payload = response.content
        path = RAW_DIR / "fred" / f"{series_id}.meta.json"
        if response.status_code != 200:
            detail = _error_text(payload)
            write_bytes(RAW_DIR / "fred" / f"{series_id}.meta.error.json", detail.encode("utf-8"))
            raise FredError(series_id, url, response.status_code, detail)
        write_bytes(path, payload)
        body = json.loads(payload)
        series = body.get("seriess") or []
        if not series:
            raise FredError(series_id, url, response.status_code, "响应中没有 seriess")
        meta = series[0]
        record = ManifestRecord(
            path=relpath(path, ROOT),
            url=url,
            access_date=date.today().isoformat(),
            sha256=sha256_bytes(payload),
            original_unit=str(meta.get("units") or ""),
            original_frequency=str(meta.get("frequency") or ""),
            observation_date_min=meta.get("observation_start"),
            observation_date_max=meta.get("observation_end"),
            release_date_rule="元数据文件，不含观测发布日。",
            license="FRED series metadata. https://fred.stlouisfed.org/legal",
            series_id=series_id,
            source="fred",
            http_status=response.status_code,
            row_count=1,
            notes=(meta.get("title") or "")[:500],
        )
        return meta, record

    def fetch_observations(
        self,
        series_id: str,
        observation_start: str,
        observation_end: str,
        source: str,
        pit_mode: str,
        realtime_start: str | None = None,
        realtime_end: str | None = None,
        release_rule: str = "",
        license_text: str = "",
        raw_subdir: str = "fred",
    ) -> tuple[pl.DataFrame, list[ManifestRecord], dict]:
        rows: list[dict] = []
        records: list[ManifestRecord] = []
        offset = 0
        total = None
        pages = 0
        while True:
            params = {
                "series_id": series_id,
                "file_type": "json",
                "observation_start": observation_start,
                "observation_end": observation_end,
                "limit": PAGE_LIMIT,
                "offset": offset,
                "sort_order": "asc",
            }
            if realtime_start:
                params["realtime_start"] = realtime_start
                params["realtime_end"] = realtime_end or observation_end
            url = public_observations_url(
                series_id,
                observation_start,
                observation_end,
                realtime_start,
                params.get("realtime_end"),
                offset if offset else None,
            )
            response = self._get(FRED_OBS_URL, params)
            payload = response.content
            page_name = f"{series_id}.observations.offset{offset}.json"
            path = RAW_DIR / raw_subdir / page_name
            if response.status_code != 200:
                detail = _error_text(payload)
                write_bytes(path, detail.encode("utf-8"))
                raise FredError(series_id, url, response.status_code, detail)
            write_bytes(path, payload)
            body = json.loads(payload)
            batch = body.get("observations") or []
            total = int(body.get("count") or len(batch))
            rows.extend(batch)
            records.append(
                ManifestRecord(
                    path=relpath(path, ROOT),
                    url=url,
                    access_date=date.today().isoformat(),
                    sha256=sha256_bytes(payload),
                    original_unit=str(body.get("units") or ""),
                    original_frequency="",
                    observation_date_min=batch[0]["date"] if batch else None,
                    observation_date_max=batch[-1]["date"] if batch else None,
                    release_date_rule=release_rule,
                    license=license_text,
                    series_id=series_id,
                    source=source,
                    http_status=response.status_code,
                    row_count=len(batch),
                    notes=f"offset={offset}; count={total}",
                )
            )
            pages += 1
            offset += len(batch)
            logger.info(
                "fetched %s page rows=%s offset=%s count=%s status=%s",
                series_id,
                len(batch),
                offset,
                total,
                response.status_code,
            )
            if not batch or offset >= total or pages > 50:
                break
        if total is not None and len(rows) < total:
            raise FredError(
                series_id,
                public_observations_url(series_id, observation_start, observation_end, realtime_start, realtime_end),
                200,
                f"分页不完整：得到 {len(rows)} 行，count={total}",
            )
        frame = observations_frame(rows, series_id, source, pit_mode)
        summary = {"count": len(rows), "nonnull": int(frame["value"].drop_nulls().len()) if frame.height else 0}
        return frame, records, summary


class FredError(RuntimeError):
    def __init__(self, series_id: str, url: str, status: int, detail: str) -> None:
        self.series_id = series_id
        self.url = url
        self.status = status
        self.detail = detail
        super().__init__(f"{series_id} HTTP {status}: {detail}")


def _error_text(payload: bytes) -> str:
    text = payload.decode("utf-8", errors="replace")[:500]
    return _REDACT_INLINE(text)


def _REDACT_INLINE(text: str) -> str:
    import os
    import re

    key = os.environ.get("FRED_API_KEY", "")
    if key:
        text = text.replace(key, "[REDACTED]")
    return re.sub(r"(api_key=)[^&\s\"']+", r"\1[REDACTED]", text, flags=re.IGNORECASE)
