"""Exported notes repeat the research payload and leave ineligible coefficients empty."""

import csv
import io
from datetime import date

from fastapi.testclient import TestClient

from quantrisklab.api.app import app
from quantrisklab.note import note_csv, note_latex, note_markdown, note_rows
from quantrisklab.paths import DB_PATH
from quantrisklab.research import research_payload
from quantrisklab.store.database import connect_readonly

client = TestClient(app)


def _sample() -> dict:
    return {
        "as_of": "2026-10-17",
        "local_projection": {
            "eligible": True,
            "horizons": [
                {"horizon": 1, "eligible": True, "beta": 0.006, "se": 0.009, "n": 644, "ci95": [-0.011, 0.023]},
                {"horizon": 42, "eligible": False, "reason": "该期限的有效样本少于 80"},
            ],
        },
        "euler": {"eligible": False, "reason": "样本不足"},
        "covar": {
            "equity_on_oil": {"eligible": False, "reason": "样本不足"},
            "equity_on_yield_change": {"eligible": True, "delta_covar": -0.0025, "n": 100},
        },
    }


def test_ineligible_horizon_exports_an_empty_coefficient():
    rows = {row["item"]: row for row in note_rows(_sample(), 63)}
    assert rows["lp_1d"]["estimate"] == 0.006
    assert rows["lp_1d"]["ci95_low"] == -0.011
    assert rows["lp_1d"]["ci95_high"] == 0.023
    assert rows["lp_42d"]["estimate"] is None
    assert rows["lp_42d"]["se"] is None
    assert rows["lp_42d"]["reason"] == "该期限的有效样本少于 80"
    parsed = list(csv.DictReader(io.StringIO(note_csv(_sample(), 63))))
    exported = {row["item"]: row for row in parsed}
    assert exported["lp_42d"]["estimate"] == ""
    assert exported["lp_1d"]["estimate"] == format(0.006, ".16g")
    assert "约化式，不是因果估计，也不是交易结果。" in note_markdown(_sample(), 63)
    assert "约化式，不是因果估计，也不是交易结果。" in note_latex(_sample(), 63)


def test_note_matches_the_research_payload_for_the_fixed_date():
    assert DB_PATH.exists()
    connection = connect_readonly()
    try:
        payload = research_payload(connection, date(2026, 10, 17), 63)
    finally:
        connection.close()
    rows = {row["item"]: row for row in note_rows(payload, 63)}
    horizon = next(item for item in payload["local_projection"]["horizons"] if item["horizon"] == 1)
    assert horizon["eligible"] is True
    assert rows["lp_1d"]["estimate"] == horizon["beta"]
    assert rows["lp_1d"]["ci95_low"] == horizon["ci95"][0]
    assert rows["lp_1d"]["ci95_high"] == horizon["ci95"][1]
    for item in payload["local_projection"]["horizons"]:
        row = rows[f"lp_{item['horizon']}d"]
        if item["eligible"]:
            assert row["estimate"] == item["beta"]
        else:
            assert row["estimate"] is None
            assert row["reason"]
    assert format(horizon["beta"], ".16g") in note_csv(payload, 63)


def test_note_route_rejects_a_window_outside_the_page():
    rejected = client.get("/api/note", params={"as_of": "2026-10-17", "window": 10, "format": "csv"})
    assert rejected.status_code == 422
    unknown = client.get("/api/note", params={"as_of": "2026-10-17", "window": 63, "format": "pdf"})
    assert unknown.status_code == 422
