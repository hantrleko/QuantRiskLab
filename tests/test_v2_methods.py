"""V2 methods stay descriptive and do not fill missing vintages."""

from datetime import date

import numpy as np
import pandas as pd

from quantrisklab.paths import DB_PATH
from quantrisklab.research import (
    delta_covar,
    euler_allocation,
    replay_cross_section,
    research_payload,
    revision_wedge,
    shrunk_covariance,
)
from quantrisklab.store.database import connect_readonly


def test_shrinkage_intensity_stays_inside_the_unit_interval():
    values = np.random.default_rng(13).normal(size=(200, 2))
    covariance, intensity = shrunk_covariance(values)
    assert covariance.shape == (2, 2)
    assert 0.0 <= intensity <= 1.0
    paired = pd.DataFrame(values, columns=["SP500", "DCOILWTICO"])
    from quantrisklab.research import _allocation

    allocated = _allocation(paired, np.array([0.4, 0.6]), covariance)
    assert allocated is not None
    assert abs(sum(allocated["shares"]) - 1) < 1e-6


def test_weights_that_do_not_sum_to_one_are_ineligible():
    result = euler_allocation(None, date(2020, 1, 1), 63, (0.7, 0.7))
    assert result["eligible"] is False


def test_identical_series_quantile_difference_is_negative():
    values = pd.Series(np.random.default_rng(13).normal(size=400))
    result = delta_covar(values, values)
    assert result["eligible"] is True
    assert result["delta_covar"] < 0
    assert "因果" in result["label"]


def test_projection_interval_and_replay_do_not_look_ahead():
    assert DB_PATH.exists()
    connection = connect_readonly()
    try:
        payload = research_payload(connection, date(2026, 10, 17), 252)
        section = replay_cross_section(connection, date(2016, 1, 4), 63)
        wedge = revision_wedge(connection, "UNRATE", date(2016, 1, 4))
    finally:
        connection.close()
    projection = payload["local_projection"]
    assert "约化" in projection["label"]
    ready = [item for item in projection["horizons"] if item.get("eligible")]
    if projection["eligible"]:
        assert ready
        low, high = ready[0]["ci95"]
        assert low <= ready[0]["beta"] <= high
    euler = payload["euler"]
    if euler["eligible"]:
        assert abs(sum(euler["shrinkage"]["shares"]) - 1) < 1e-6
        assert 0.0 <= euler["shrinkage"]["intensity"] <= 1.0
    for market in section["crowding"]["markets"]:
        assert market["release_date"] <= "2016-01-04"
        assert market["observation_date"] <= "2016-01-04"
    if wedge["status"] == "unavailable":
        assert "visible_value" not in wedge
    else:
        assert wedge["status"] in {"unchanged", "revised"}
