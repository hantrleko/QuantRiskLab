"""路径与固定研究窗口。不读取密钥。"""

from __future__ import annotations

import os
from pathlib import Path

OBSERVATION_START = "2015-01-01"
ALFRED_VINTAGE_START = "2016-01-01"
# 最近若干期全留，更早按步长抽样。漏掉的 vintage 只会让可见时点偏晚，不会提前看到未发布修订。
ALFRED_TAIL_VINTAGES = 18
ALFRED_EARLY_STEP = 6


def project_root() -> Path:
    override = os.environ.get("QUANTRISKLAB_ROOT", "").strip()
    if override:
        return Path(override)
    return Path(__file__).resolve().parents[2]


def data_dir() -> Path:
    return project_root() / "data"


def raw_dir() -> Path:
    return data_dir() / "raw"


def parquet_dir() -> Path:
    return data_dir() / "parquet"


def results_dir() -> Path:
    return data_dir() / "results"


def log_dir() -> Path:
    return project_root() / "logs"


def manifest_path() -> Path:
    return data_dir() / "manifest.json"


def duckdb_path() -> Path:
    return data_dir() / "warehouse.duckdb"


def errors_path() -> Path:
    return data_dir() / "source_errors.json"


def bis_probe_path() -> Path:
    return data_dir() / "bis_probe.json"


def observations_parquet() -> Path:
    return parquet_dir() / "observations.parquet"


def fixture_dir() -> Path:
    return project_root() / "tests" / "fixtures"
