"""Structure measures use cached observations and do not invent prices."""

from datetime import date

import pandas as pd

from quantrisklab.metrics.structure import (
    distinct_threshold_episodes,
    lower_tail_dependence,
    structure_payload,
)
from quantrisklab.paths import DB_PATH
from quantrisklab.store.database import connect_readonly


def test_threshold_breaches_collapse_into_two_episodes():
    index = pd.bdate_range("2010-01-04", periods=220)
    changes = pd.Series(0.0, index=index)
    changes.iloc[80:91] = 0.8
    changes.iloc[170:176] = -0.9
    episodes = distinct_threshold_episodes(changes, horizon=63, threshold=0.5)
    assert len(episodes) == 2
    assert episodes[0]["direction"] == "上升"
    assert "T" not in episodes[0]["start"]
    assert "T" not in episodes[0]["end"]
    assert episodes[1]["direction"] == "下降"
    assert episodes[0]["n_breach_days"] == 11
    assert episodes[1]["end"] > episodes[0]["end"]


def test_identical_series_have_elevated_lower_tail_dependence():
    index = pd.bdate_range("2016-01-04", periods=400)
    values = pd.Series(range(400), index=index).astype(float)
    values.iloc[::20] = -10
    result = lower_tail_dependence(values, values, alpha=0.05)
    assert result["eligible"] is True
    assert result["coexceedance"] > result["independence_coexceedance"]
    assert result["lift"] > result["independence_lift"]
    assert result["n_joint_tail"] >= 10
    assert result["joint_probability_ci95"][0] <= result["joint_probability"] <= result["joint_probability_ci95"][1]


def test_similar_dates_cluster_in_time_not_by_distance_rank():
    from quantrisklab.metrics.structure import cluster_similar_dates

    stamps = [pd.Timestamp("2024-06-01"), pd.Timestamp("2018-01-01"), pd.Timestamp("2018-01-20")]
    distances = {
        pd.Timestamp("2024-06-01"): 0.1,
        pd.Timestamp("2018-01-01"): 0.2,
        pd.Timestamp("2018-01-20"): 0.3,
    }
    clusters = cluster_similar_dates(stamps, distances, horizon_days=63)
    assert len(clusters) == 2
    assert clusters[0]["date"] == "2018-01-01"
    assert clusters[0]["cluster_size"] == 2
    assert clusters[1]["date"] == "2024-06-01"


def test_real_store_hides_future_crisis_windows():
    assert DB_PATH.exists()
    connection = connect_readonly()
    try:
        early = structure_payload(connection, date(2012, 1, 3), window=63)
        late = structure_payload(connection, date(2026, 10, 13), window=63)
    finally:
        connection.close()
    early_ids = {item["id"] for item in early["crises"]["windows"]}
    late_ids = {item["id"] for item in late["crises"]["windows"]}
    assert "covid" not in early_ids
    assert "hike2022" not in early_ids
    assert "covid" in late_ids
    assert late["episodes"]["count"] >= 1
    assert all(item["end"] <= "2026-10-13" for item in late["episodes"]["items"])
    assert "交易信号" in late["answer"]
    assert early["as_of"] == "2012-01-03"
