"""Repository paths. Raw data and caches stay outside git."""

from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
DATA_DIR = ROOT / "data"
RAW_DIR = DATA_DIR / "raw"
PARQUET_DIR = DATA_DIR / "parquet"
LOG_DIR = ROOT / "logs"
DB_PATH = DATA_DIR / "quantrisklab.duckdb"
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
