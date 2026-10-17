"""ALFRED vintages via the FRED observations endpoint. Do not backfill revisions."""

from __future__ import annotations

import polars as pl

from quantrisklab.sources.fred import FredClient
from quantrisklab.sources.http_util import ManifestRecord


def fetch_alfred_vintages(
    client: FredClient,
    series_id: str,
    observation_start: str,
    observation_end: str,
    realtime_start: str,
    release_rule: str,
    license_text: str,
) -> tuple[pl.DataFrame, list[ManifestRecord], dict]:
    return client.fetch_observations(
        series_id=series_id,
        observation_start=observation_start,
        observation_end=observation_end,
        source="alfred",
        pit_mode="alfred",
        realtime_start=realtime_start,
        realtime_end=observation_end,
        release_rule=release_rule,
        license_text=license_text,
        raw_subdir="alfred",
    )
