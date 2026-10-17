"""Manifest hashes are the SHA256 of the saved file bytes."""

import hashlib
from datetime import date

from quantrisklab.sources.http_util import ManifestRecord, sha256_bytes, sha256_file


def test_sha256_file_matches_hashlib(tmp_path):
    payload = b"official-bytes-not-a-secret"
    path = tmp_path / "sample.bin"
    path.write_bytes(payload)
    assert sha256_file(path) == hashlib.sha256(payload).hexdigest()
    assert sha256_bytes(payload) == hashlib.sha256(payload).hexdigest()


def test_manifest_record_stores_sha256(tmp_path):
    payload = b'{"observations":[]}'
    path = tmp_path / "DGS10.observations.offset0.json"
    path.write_bytes(payload)
    record = ManifestRecord(
        path=path.name,
        url="https://api.stlouisfed.org/fred/series/observations?series_id=DGS10&file_type=json",
        access_date=date.today().isoformat(),
        sha256=sha256_file(path),
        original_unit="Percent",
        original_frequency="Daily",
        observation_date_min=None,
        observation_date_max=None,
        release_date_rule="test",
        license="FRED terms",
        series_id="DGS10",
        source="fred",
        http_status=200,
        row_count=0,
    )
    assert record.sha256 == hashlib.sha256(payload).hexdigest()
    assert "api_key" not in record.url
