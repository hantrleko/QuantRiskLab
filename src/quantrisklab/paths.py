"""Repository paths. Raw data and caches stay outside git."""

import os
import shutil
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
DATA_DIR = ROOT / "data"
RAW_DIR = DATA_DIR / "raw"
PARQUET_DIR = DATA_DIR / "parquet"
LOG_DIR = ROOT / "logs"


def resolve_db_path() -> Path:
    """Use QUANTRISKLAB_DB when that file exists or can be seeded from the bundled snapshot."""
    bundled = DATA_DIR / "quantrisklab.duckdb"
    override = os.environ.get("QUANTRISKLAB_DB", "").strip()
    if not override:
        return bundled
    path = Path(override)
    if path.is_file() and path.stat().st_size > 0:
        return path
    if bundled.is_file():
        path.parent.mkdir(parents=True, exist_ok=True)
        if not path.exists():
            shutil.copy2(bundled, path)
        if path.is_file():
            return path
    return bundled


DB_PATH = resolve_db_path()
MANIFEST_JSON = DATA_DIR / "manifest.json"
FAILURES_JSON = DATA_DIR / "failures.json"
QUALITY_JSON = DATA_DIR / "quality_report.json"
DECISIONS_JSON = DATA_DIR / "series_decisions.json"

OBS_SCHEMA = {
    "series_id": "str",
    "source": "str",
    "observation_date": "date",
    "release_date": "date",
    "value": "float",
    "realtime_start": "date",
    "realtime_end": "date",
}


def ensure_dirs() -> None:
    for path in (
        RAW_DIR / "fred",
        RAW_DIR / "alfred",
        RAW_DIR / "cftc",
        PARQUET_DIR / "observations",
        PARQUET_DIR / "cftc",
        LOG_DIR,
    ):
        path.mkdir(parents=True, exist_ok=True)
