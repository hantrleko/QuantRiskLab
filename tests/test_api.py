"""The API serves the stored public data."""

from fastapi.testclient import TestClient

from quantrisklab.api.app import app
from quantrisklab.paths import DB_PATH

client = TestClient(app)


def test_health_catalog_series_and_risk_endpoints():
    assert DB_PATH.exists(), "缺少数据库，先运行 scripts/reproduce_v0.py"
    health = client.get("/health")
    assert health.status_code == 200
    assert health.json()["status"] == "ok"
    catalog = client.get("/api/catalog")
    assert catalog.status_code == 200
    series = catalog.json()["series"]
    assert series
    quality = client.get("/api/quality")
    assert quality.status_code == 200
    quality_rows = quality.json()["series"]
    assert quality_rows
    series_id = max(quality_rows, key=lambda row: row.get("n_visible") or 0)["series_id"]
    observed = client.get("/api/series/" + series_id)
    assert observed.status_code == 200
    body = observed.json()
    assert body["observations"]
    assert any(point["value"] is not None for point in body["observations"])
    correlation = client.get("/api/correlation", params={"window": 60})
    assert correlation.status_code == 200
    payload = correlation.json()
    usable = payload["price_returns"] if payload["price_returns"].get("eligible") else payload["level_changes"]
    assert usable.get("eligible") is True
    assert usable["matrix"]
    heatmap = client.get("/api/heatmap", params={"start": "2020-01-01"})
    assert heatmap.status_code == 200
    heat = heatmap.json()
    assert heat["price_vol"]["rows"] or heat["level_scale"]["rows"]
