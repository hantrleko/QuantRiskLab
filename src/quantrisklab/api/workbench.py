"""Single dashboard payload. The numeric definitions stay in the existing modules."""

from __future__ import annotations

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
from quantrisklab.pit_clock import availability_catalog, snapshot_status
from quantrisklab.quality.checks import build_quality_report
from quantrisklab.research import research_payload
from quantrisklab.sources.bis import BisSdmxClient

LEVEL_ROLES = {"yield", "spread", "volatility_index", "macro", "index"}


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
