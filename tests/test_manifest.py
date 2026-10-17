"""Manifest hashes must match the stored raw bytes."""

import hashlib
import json
from pathlib import Path

from quantrisklab.paths import MANIFEST_JSON, ROOT
from quantrisklab.sources.http_util import sha256_bytes, sha256_file


def test_sha256_bytes_matches_hashlib():
    payload = b"quantrisklab-hash-check"
    assert sha256_bytes(payload) == hashlib.sha256(payload).hexdigest()


def test_manifest_hashes_match_raw_files():
    assert MANIFEST_JSON.exists(), "缺少 manifest，先运行 scripts/reproduce_v0.py"
    manifest = json.loads(MANIFEST_JSON.read_text(encoding="utf-8"))
    checked = 0
    for row in manifest:
        if int(row.get("http_status") or 0) != 200:
            continue
        path = ROOT / row["path"]
        assert path.exists(), row["path"]
        assert sha256_file(path) == row["sha256"]
        assert "api_key=" not in row.get("url", "")
        checked += 1
    assert checked > 0
