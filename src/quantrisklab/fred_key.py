"""Inject FRED_API_KEY into the process environment. The value is never logged."""

from __future__ import annotations

import os
import re
import zipfile
from pathlib import Path

_KEY = re.compile(r"[a-f0-9]{32}")
_LOCAL_DOCX = Path(r"F:\AI\API\FRED.docx")


def _read_docx_key(path: Path) -> str:
    with zipfile.ZipFile(path) as archive:
        xml = archive.read("word/document.xml").decode("utf-8", errors="ignore")
    found = list(dict.fromkeys(_KEY.findall(xml)))
    if len(found) != 1:
        raise RuntimeError(f"FRED 密钥文件无法唯一识别密钥（匹配数 {len(found)}）：{path.name}")
    return found[0]


def ensure_fred_api_key() -> None:
    """Use the existing environment variable, otherwise read the local key file once."""
    if os.environ.get("FRED_API_KEY", "").strip():
        return
    if not _LOCAL_DOCX.is_file():
        raise RuntimeError(
            "未设置环境变量 FRED_API_KEY，且本机不存在 F:\\AI\\API\\FRED.docx。"
            "不要把密钥写入仓库。"
        )
    os.environ["FRED_API_KEY"] = _read_docx_key(_LOCAL_DOCX)


def require_fred_api_key() -> str:
    ensure_fred_api_key()
    return os.environ["FRED_API_KEY"].strip()
