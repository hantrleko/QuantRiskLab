"""Fail if the FRED key is written into the project or raw downloads."""

import os
from pathlib import Path

import pytest

pytestmark = pytest.mark.integration

from quantrisklab.fred_key import ensure_fred_api_key

ROOT = Path(__file__).resolve().parents[1]
SKIP = {".venv", "node_modules", "dist", "__pycache__", ".git"}
SUFFIXES = {".py", ".md", ".json", ".txt", ".csv", ".ts", ".tsx", ".css", ".html", ".toml", ".ini", ".log"}


def test_key_is_not_stored_in_the_project():
    ensure_fred_api_key()
    key = os.environ["FRED_API_KEY"].encode()
    assert len(key) >= 16
    leaked: list[str] = []
    roots = [ROOT / "src", ROOT / "tests", ROOT / "frontend", ROOT / "scripts", ROOT / "data" / "raw", ROOT / "logs"]
    extra = [ROOT / "README.md", ROOT / "ARCHITECTURE.md", ROOT / "DATA_SOURCES.md", ROOT / "pyproject.toml"]
    files = [path for path in extra if path.exists()]
    for root in roots:
        if not root.exists():
            continue
        for path in root.rglob("*"):
            if not path.is_file() or SKIP.intersection(path.parts):
                continue
            if path.suffix.lower() not in SUFFIXES or path.stat().st_size > 40_000_000:
                continue
            files.append(path)
    assert any(path.parts[-2:] == ("data", "raw") or "raw" in path.parts for path in files), "还没有原始下载可扫描"
    for path in files:
        if key in path.read_bytes():
            leaked.append(str(path.relative_to(ROOT)))
    assert not leaked, "密钥写入了这些文件: " + ", ".join(leaked)
