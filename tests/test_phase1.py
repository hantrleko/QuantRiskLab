"""Public deploy closes writes, and replay states what the selected date can see."""

from datetime import date

from fastapi.testclient import TestClient

from quantrisklab.api.app import app
from quantrisklab.paths import DB_PATH
from quantrisklab.research import crowding_snapshot
from quantrisklab.store.database import connect_readonly
from quantrisklab.studio import EXPERIMENT_DIR, replay_track

client = TestClient(app)


def test_public_deploy_rejects_experiment_writes_and_hides_docs(monkeypatch):
    monkeypatch.setenv("QUANTRISKLAB_PUBLIC", "1")
    before = set(EXPERIMENT_DIR.glob("*.json")) if EXPERIMENT_DIR.exists() else set()
    saved = client.post("/api/experiments", json={"as_of": "2016-01-04", "window": 126})
    assert saved.status_code == 403
    assert "不保存" in saved.json()["detail"]
    after = set(EXPERIMENT_DIR.glob("*.json")) if EXPERIMENT_DIR.exists() else set()
    assert after == before
    assert client.get("/docs").status_code == 404
    assert client.get("/redoc").status_code == 404
    assert client.get("/openapi.json").status_code == 404


def test_future_as_of_is_rejected():
    response = client.get("/api/replay", params={"as_of": "2030-01-01"})
    assert response.status_code == 422
    assert "今天" in response.json()["detail"]


def test_replay_names_a_series_that_starts_after_the_selected_date():
    assert DB_PATH.exists()
    connection = connect_readonly()
    try:
        early = replay_track(connection, date(2016, 1, 4), 126)
        later = replay_track(connection, date(2020, 6, 30), 63)
        holdings = crowding_snapshot(connection, date(2016, 1, 4))
    finally:
        connection.close()
    coverage = early["coverage"]["SP500"]
    assert coverage["rows"] == 0
    assert coverage["start"] is not None
    assert coverage["start"] > "2016-01-04"
    assert coverage["start"].startswith("2016-10")
    assert coverage["title_zh"]
    finite = [point["date"] for point in later["points"] if point["sp_wti_corr"] is not None]
    may = [day for day in finite if "2020-05-01" <= day <= "2020-05-29"]
    assert may, f"2020-05 没有股油相关。有限样本 {finite[:3]} … {finite[-3:]}"
    assert "起可见" in holdings["reason"]
