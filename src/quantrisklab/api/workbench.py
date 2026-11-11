"""Dashboard payloads. Each page asks only for the blocks it draws."""

from __future__ import annotations

import json
from datetime import date

from quantrisklab.api.queries import (
    all_meta,
    correlation_payload,
    heatmap_payload,
    metrics_payload,
    observations_payload,
    positions_payload,
)
from quantrisklab.metrics.structure import structure_payload
from quantrisklab.paths import FAILURES_JSON
from quantrisklab.pit_clock import availability_catalog, snapshot_status
from quantrisklab.quality.checks import build_quality_report
from quantrisklab.research import research_payload
from quantrisklab.sources.bis import BisSdmxClient

LEVEL_ROLES = {"yield", "spread", "volatility_index", "macro", "index"}
VIEW_PAGES = ("overview", "pit", "audit", "research", "replay", "explore", "tails", "compare", "export")
OVERVIEW_ROLES = {"yield", "spread", "volatility_index"}


def workbench_payload(connection, as_of: date, window: int, today: date) -> dict:
    series = all_meta(connection)
    points = {}
    latest = {}
    metrics = []
    for item in series:
        series_id = item["series_id"]
        if item["role"] in LEVEL_ROLES:
            body = observations_payload(connection, series_id, as_of, None, None)
            points[series_id] = [] if body is None else body["observations"]
        if item["role"] == "macro":
            body = observations_payload(connection, series_id, today, None, None)
            latest[series_id] = [] if body is None else body["observations"]
        if item["price_metrics"]:
            metric = metrics_payload(connection, series_id, as_of, None, None, window, 0.05)
            if metric is not None:
                metrics.append(metric)
    return {
        "as_of": as_of.isoformat(),
        "window": window,
        "catalog": {"series": series, "bis": BisSdmxClient().describe()},
        "snapshot": snapshot_status(),
        "availability": availability_catalog(),
        "quality": build_quality_report(connection, as_of),
        "heatmap": heatmap_payload(connection, as_of, None, None),
        "correlation": correlation_payload(connection, as_of, None, None, window),
        "positions": positions_payload(connection, as_of, None, None),
        "structure": structure_payload(connection, as_of, window),
        "research": research_payload(connection, as_of, window),
        "series": points,
        "latest_macro": latest,
        "metrics": metrics,
    }


def _visible_end(connection, as_of: date) -> str | None:
    row = connection.execute(
        """
        SELECT MAX(observation_date)
        FROM observations
        WHERE value IS NOT NULL AND release_date <= ? AND observation_date <= ?
        """,
        [as_of, as_of],
    ).fetchone()
    if row is None or row[0] is None:
        return None
    return str(row[0])[:10]


def _series_lists(connection, as_of: date, roles: set[str]) -> dict:
    points = {}
    for item in all_meta(connection):
        if item["role"] not in roles:
            continue
        body = observations_payload(connection, item["series_id"], as_of, None, None)
        points[item["series_id"]] = [] if body is None else body["observations"]
    return points


def _metric_list(connection, as_of: date, window: int) -> list:
    metrics = []
    for item in all_meta(connection):
        if not item["price_metrics"]:
            continue
        metric = metrics_payload(connection, item["series_id"], as_of, None, None, window, 0.05)
        if metric is not None:
            metrics.append(metric)
    return metrics


def view_payload(connection, page: str, as_of: date, window: int, today: date) -> dict:
    if page not in VIEW_PAGES:
        raise ValueError(page)
    payload = {
        "as_of": as_of.isoformat(),
        "window": window,
        "page": page,
        "catalog": {"series": all_meta(connection), "bis": BisSdmxClient().describe()},
        "snapshot": snapshot_status(),
        "availability": availability_catalog(),
        "visible_end": _visible_end(connection, as_of),
    }
    if page == "overview":
        payload["series"] = _series_lists(connection, as_of, OVERVIEW_ROLES)
        payload["correlation"] = correlation_payload(connection, as_of, None, None, window)
        payload["metrics"] = _metric_list(connection, as_of, window)
    elif page == "pit":
        payload["series"] = _series_lists(connection, as_of, {"macro"})
        payload["latest_macro"] = _series_lists(connection, today, {"macro"})
    elif page == "audit":
        payload["quality"] = build_quality_report(connection, as_of)
        payload["failures"] = json.loads(FAILURES_JSON.read_text(encoding="utf-8")) if FAILURES_JSON.exists() else []
    elif page == "research":
        payload["structure"] = structure_payload(connection, as_of, window)
        payload["research"] = research_payload(connection, as_of, window)
        payload["heatmap"] = heatmap_payload(connection, as_of, None, None)
        payload["correlation"] = correlation_payload(connection, as_of, None, None, window)
        payload["positions"] = positions_payload(connection, as_of, None, None)
        payload["metrics"] = _metric_list(connection, as_of, window)
    return payload
