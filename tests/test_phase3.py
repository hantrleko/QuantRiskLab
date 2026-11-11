"""Offline two-state states, CPI vintages side by side, and page-sized responses."""

from datetime import date

import numpy as np
import pandas as pd
from fastapi.testclient import TestClient

from quantrisklab.api.app import app
from quantrisklab.paths import DB_PATH
from quantrisklab.regimes import align_states, fit_two_state, _label_high, regime_payload
from quantrisklab.research import vintage_comparison
from quantrisklab.store.database import connect_readonly

client = TestClient(app)


def test_two_state_fit_labels_the_higher_variance():
    rng = np.random.default_rng(3)
    values = np.concatenate([rng.normal(0.0, 0.04, 180), rng.normal(0.0, 0.25, 180)])
    fitted = _label_high(fit_two_state(values), "variance")
    assert fitted["converged"]
    assert fitted["variance_high"] > fitted["variance_low"]
    high = fitted["filtered"][:, fitted["high"]]
    assert np.isfinite(high).all()
    assert high.min() >= -1e-6
    assert high.max() <= 1.0 + 1e-6


def test_alignment_does_not_use_an_estimate_from_after_as_of():
    panel = pd.DataFrame(
        {
            "model_id": ["dgs10_weekly_diff"] * 4,
            "estimation_end": ["2008-09-12", "2008-09-12", "2009-03-31", "2009-03-31"],
            "observation_date": ["2008-09-05", "2008-09-12", "2008-09-05", "2009-03-27"],
            "filtered_high": [0.2, 0.8, 0.9, 0.1],
            "smoothed_high": [0.2, 0.8, 0.9, 0.1],
        }
    )
    dates = pd.Series(["2008-09-12", "2008-09-15", "2009-03-31"])
    early = align_states(panel, dates, "dgs10_weekly_diff", date(2008, 9, 15))
    assert early.iloc[0]["filtered_high"] == 0.8
    assert early.iloc[1]["filtered_high"] == 0.8
    assert pd.isna(early.iloc[2]["filtered_high"])
    later = align_states(panel, dates, "dgs10_weekly_diff", date(2009, 3, 31))
    assert later.iloc[0]["filtered_high"] == 0.9
    assert later.iloc[2]["filtered_high"] == 0.1


def test_cpi_comparison_keeps_the_same_months_and_labels_later_releases():
    assert DB_PATH.exists()
    connection = connect_readonly()
    try:
        body = vintage_comparison(connection, "CPIAUCSL", date(2008, 9, 15))
    finally:
        connection.close()
    assert body["status"] == "available"
    assert body["then"] and len(body["then"]) == len(body["now"])
    assert [row["observation_date"] for row in body["then"]] == [row["observation_date"] for row in body["now"]]
    assert all(row["release_date"] <= "2008-09-15" for row in body["then"])
    assert body["revised_count"] > 0
    assert body["later_release_count"] > 0


def test_replay_view_skips_the_full_workbench_and_sets_a_cache_header():
    response = client.get("/api/view", params={"page": "replay", "as_of": "2008-09-15", "window": 63})
    assert response.status_code == 200
    assert "max-age=300" in response.headers.get("cache-control", "")
    body = response.json()
    assert body["page"] == "replay"
    assert body["as_of"] == "2008-09-15"
    assert body["visible_end"] <= "2008-09-15"
    assert "research" not in body
    assert "series" not in body
    assert "structure" not in body
    rejected = client.get("/api/view", params={"page": "missing", "as_of": "2008-09-15"})
    assert rejected.status_code == 422


def test_stored_states_do_not_look_past_the_selected_date():
    connection = connect_readonly()
    try:
        body = regime_payload(connection, date(2008, 9, 15))
        later = regime_payload(connection, date(2009, 3, 31))
    finally:
        connection.close()
    for model in body["models"]:
        assert model["eligible"]
        assert model["estimation_end"] <= "2008-09-15"
        assert model["points"]
        assert all(point["observation_date"] <= model["estimation_end"] for point in model["points"])
        assert all(0.0 <= point["filtered_high"] <= 1.0 for point in model["points"])
        assert all(0.0 <= point["smoothed_high"] <= 1.0 for point in model["points"])
    assert later["models"][0]["estimation_end"] == "2009-03-31"