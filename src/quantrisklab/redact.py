"""从日志、异常和落盘文本中去掉 API key。"""

from __future__ import annotations

import os
import re

_KEY_RE = re.compile(r"(?i)(api[_-]?key\s*[=:]\s*)([A-Za-z0-9]+)")


def redact(text: str) -> str:
    if not text:
        return text
    cleaned = _KEY_RE.sub(r"\1REDACTED", text)
    key = os.environ.get("FRED_API_KEY", "")
    if key and len(key) >= 8 and key in cleaned:
        cleaned = cleaned.replace(key, "REDACTED")
    return cleaned
