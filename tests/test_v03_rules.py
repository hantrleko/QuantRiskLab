"""V0.3 correctness checks that do not need the raw download cache."""

import numpy as np
import pandas as pd

from quantrisklab.metrics.risk import summarize_price
from quantrisklab.pit_clock import availability_catalog
from quantrisklab.sources.calendar import cftc_release_date as calendar_release
from quantrisklab.sources.cftc import cftc_release_date


def test_nonpositive_prices_do_not_get_a_percent_drawdown():
    values = [20.0 + (index % 7) for index in range(80)]
    values[40] = -5.0
    frame = pd.DataFrame(
        {
            "observation_date": pd.bdate_range("2020-01-02", periods=80),
            "release_date": pd.bdate_range("2020-01-02", periods=80),
            "value": values,
        }
    )
    import polars as pl

    summary = summarize_price(pl.from_pandas(frame), window=20, alpha=0.05)
    assert summary["max_drawdown_eligible"] is False
    assert summary["max_drawdown"] is None
    assert summary["price_level_change"] == values[-1] - values[0]


def test_window_containing_negative_wti_does_not_compound():
    from quantrisklab.metrics.structure import _window_return

    frame = pd.DataFrame(
        {
            "observation_date": pd.to_datetime(["2020-04-17", "2020-04-20", "2020-04-21"]),
            "value": [18.27, -36.98, 8.0],
        }
    )
    result = _window_return(frame, pd.Timestamp("2020-04-17").date(), pd.Timestamp("2020-04-21").date())
    assert result["status"] == "not_computable"
    assert result["value"] is None


def test_calendar_and_parser_agree_on_a_forward_delay():
    from datetime import date

    observation = date(2026, 6, 16)
    assert calendar_release(observation) == cftc_release_date(observation) == date(2026, 6, 22)


def test_availability_clock_does_not_invent_timestamps():
    catalog = availability_catalog()
    for row in catalog["series"]:
        assert row["available_at_utc"] is None
        assert row["availability_quality"]
    qualities = {row["series_id"]: row["availability_quality"] for row in catalog["series"]}
    assert qualities["DFF"] == "date_approximate"
    assert "9:00" in next(row["availability_rule"] for row in catalog["series"] if row["series_id"] == "DFF")


def test_block_bootstrap_interval_stays_inside_zero_one():
    from quantrisklab.metrics.structure import _block_bootstrap_interval

    flags = np.array([0, 1, 0, 0, 1, 0] * 20, dtype=float)
    low, high = _block_bootstrap_interval(flags, block=5, reps=50, seed=3)
    assert 0 <= low <= high <= 1