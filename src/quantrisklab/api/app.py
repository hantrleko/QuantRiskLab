"""Local research API. Default bind is 127.0.0.1:8876.

8765 is often already taken on this machine, so the documented port is 8876.
"""

from __future__ import annotations

import json
import logging
from datetime import date

from fastapi import FastAPI, HTTPException, Query
from fastapi.middleware.cors import CORSMiddleware
from fastapi.staticfiles import StaticFiles
from starlette.exceptions import HTTPException as StarletteHTTPException
from starlette.responses import JSONResponse

from quantrisklab import __version__
from quantrisklab.api.queries import (
    all_meta,
    correlation_payload,
    descriptive_yield_link,
    heatmap_payload,
    metrics_payload,
    observations_payload,
    positions_payload,
    sanitize,
    vintage_dates,
)
from quantrisklab.logging_setup import setup_logging
from quantrisklab.metrics.structure import structure_payload
from quantrisklab.paths import DB_PATH, FAILURES_JSON, ROOT
from quantrisklab.quality.checks import build_quality_report
from quantrisklab.sources.bis import BisSdmxClient
from quantrisklab.store.database import connect_readonly

logger = logging.getLogger("quantrisklab.api")
setup_logging()

app = FastAPI(title="QuantRiskLab", version=__version__)
app.add_middleware(
    CORSMiddleware,
    allow_origin_regex=r"https?://(localhost|127\.0\.0\.1)(:\d+)?",
    allow_methods=["GET", "OPTIONS"],
    allow_headers=["*"],
)


@app.exception_handler(Exception)
async def unhandled(request, exc: Exception):
    if isinstance(exc, StarletteHTTPException):
        return JSONResponse(status_code=exc.status_code, content={"detail": exc.detail})
    logger.exception("API 失败 path=%s", request.url.path)
    return JSONResponse(status_code=500, content={"detail": "服务器内部错误"})


def _day(value: str | None, default: date | None = None) -> date | None:
    if value is None or value == "":
        return default
    try:
        return date.fromisoformat(value)
    except ValueError as exc:
        raise HTTPException(status_code=422, detail="日期格式应为 YYYY-MM-DD") from exc


def _db():
    if not DB_PATH.exists():
        raise HTTPException(status_code=503, detail="数据库尚未构建，请先运行 scripts/reproduce_v0.py")
    return connect_readonly()


@app.get("/health")
@app.get("/api/health")
def health() -> dict:
    return {"status": "ok", "version": __version__, "database": DB_PATH.exists()}


@app.get("/api/catalog")
def catalog() -> dict:
    connection = _db()
    try:
        series = all_meta(connection)
    finally:
        connection.close()
    return sanitize({"series": series, "bis": BisSdmxClient().describe()})


@app.get("/api/quality")
def quality(as_of: str | None = None) -> dict:
    day = _day(as_of, date.today())
    assert day is not None
    connection = _db()
    try:
        series = build_quality_report(connection, day)
    finally:
        connection.close()
    failures = []
    if FAILURES_JSON.exists():
        failures = json.loads(FAILURES_JSON.read_text(encoding="utf-8"))
    return sanitize(
        {
            "as_of": day.isoformat(),
            "series": series,
            "failures": failures,
            "rules": [
                "as_of 只能看到 release_date 与 observation_date 都不晚于 as_of 的记录。",
                "同一观测日若有多版，只保留当时已发布的最新一版。",
                "CFTC 观测日不是公布日。",
                "利率水平不计算成资产收益。",
            ],
        }
    )


@app.get("/api/series/{series_id}")
def series(
    series_id: str,
    as_of: str | None = None,
    start: str | None = None,
    end: str | None = None,
) -> dict:
    day = _day(as_of, date.today())
    assert day is not None
    connection = _db()
    try:
        payload = observations_payload(connection, series_id, day, _day(start), _day(end))
    finally:
        connection.close()
    if payload is None:
        raise HTTPException(status_code=404, detail=f"没有序列 {series_id}")
    return sanitize(payload)


@app.get("/api/vintages/{series_id}")
def vintages(series_id: str) -> dict:
    connection = _db()
    try:
        dates = vintage_dates(connection, series_id)
    finally:
        connection.close()
    if not dates:
        raise HTTPException(status_code=404, detail=f"没有序列 {series_id} 的发布日")
    return {"series_id": series_id, "release_dates": dates}


@app.get("/api/metrics/{series_id}")
def metrics(
    series_id: str,
    as_of: str | None = None,
    start: str | None = None,
    end: str | None = None,
    window: int = Query(default=63, ge=5, le=756),
    alpha: float = Query(default=0.05, gt=0, lt=1),
) -> dict:
    day = _day(as_of, date.today())
    assert day is not None
    connection = _db()
    try:
        payload = metrics_payload(connection, series_id, day, _day(start), _day(end), window, alpha)
    except Exception:
        logger.exception("指标计算失败 series=%s", series_id)
        raise
    finally:
        connection.close()
    if payload is None:
        raise HTTPException(status_code=404, detail=f"没有序列 {series_id}")
    return sanitize(payload)


@app.get("/api/correlation")
def correlation(
    as_of: str | None = None,
    start: str | None = None,
    end: str | None = None,
    window: int = Query(default=60, ge=20, le=756),
) -> dict:
    day = _day(as_of, date.today())
    assert day is not None
    connection = _db()
    try:
        payload = correlation_payload(connection, day, _day(start), _day(end), window)
    finally:
        connection.close()
    return sanitize(payload)


@app.get("/api/heatmap")
def heatmap(as_of: str | None = None, start: str | None = None, end: str | None = None) -> dict:
    day = _day(as_of, date.today())
    assert day is not None
    connection = _db()
    try:
        payload = heatmap_payload(connection, day, _day(start), _day(end))
    finally:
        connection.close()
    return sanitize(payload)


@app.get("/api/positions")
def positions(as_of: str | None = None, start: str | None = None, end: str | None = None) -> dict:
    day = _day(as_of, date.today())
    assert day is not None
    connection = _db()
    try:
        payload = positions_payload(connection, day, _day(start), _day(end))
    finally:
        connection.close()
    return sanitize(payload)


@app.get("/api/descriptive")
def descriptive(as_of: str | None = None, start: str | None = None, end: str | None = None) -> dict:
    day = _day(as_of, date.today())
    assert day is not None
    connection = _db()
    try:
        payload = descriptive_yield_link(connection, day, _day(start), _day(end))
    except Exception:
        logger.exception("描述性回归失败")
        raise
    finally:
        connection.close()
    return sanitize(payload)


@app.get("/api/bis")
def bis() -> dict:
    return BisSdmxClient().describe()


@app.get("/api/structure")
def structure(
    as_of: str | None = None,
    window: int = Query(default=63, ge=21, le=252),
) -> dict:
    day = _day(as_of, date.today())
    assert day is not None
    connection = _db()
    try:
        payload = structure_payload(connection, day, window)
    except Exception:
        logger.exception("风险结构计算失败")
        raise
    finally:
        connection.close()
    return sanitize(payload)


_DIST = ROOT / "frontend" / "dist"
if _DIST.is_dir():
    app.mount("/", StaticFiles(directory=_DIST, html=True), name="frontend")


def main() -> None:
    import os

    import uvicorn

    port = int(os.environ.get("PORT", "8876"))
    host = "0.0.0.0" if os.environ.get("PORT") else "127.0.0.1"
    uvicorn.run("quantrisklab.api.app:app", host=host, port=port, log_level="info")
