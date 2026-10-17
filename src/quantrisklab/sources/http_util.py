"""Shared download helpers. Public URLs never contain the API key."""

from __future__ import annotations

import hashlib
import os
import re
from dataclasses import asdict, dataclass
from datetime import date
from pathlib import Path

_KEY_IN_URL = re.compile(r"(api_key=)[^&\s\"']+", re.IGNORECASE)


def redact(text: str | None) -> str:
    value = text or ""
    key = os.environ.get("FRED_API_KEY", "").strip()
    if key:
        value = value.replace(key, "[REDACTED]")
    return _KEY_IN_URL.sub(r"\1[REDACTED]", value)


@dataclass
class ManifestRecord:
    path: str
    url: str
    access_date: str
    sha256: str
    original_unit: str
    original_frequency: str
    observation_date_min: str | None
    observation_date_max: str | None
    release_date_rule: str
    license: str
    series_id: str
    source: str
    http_status: int
    row_count: int
    notes: str = ""

    def to_dict(self) -> dict:
        data = asdict(self)
        data["url"] = redact(data["url"])
        data["notes"] = redact(data["notes"])
        data["license"] = redact(data["license"])
        return data


@dataclass
class DownloadFailure:
    source: str
    series_id: str
    url: str
    http_status: int | None
    error: str

    def to_dict(self) -> dict:
        data = asdict(self)
        data["url"] = redact(data["url"])
        data["error"] = redact(data["error"])
        return data


def sha256_bytes(payload: bytes) -> str:
    return hashlib.sha256(payload).hexdigest()


def sha256_file(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for chunk in iter(lambda: handle.read(1 << 20), b""):
            digest.update(chunk)
    return digest.hexdigest()


def write_bytes(path: Path, payload: bytes) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    temporary = path.with_suffix(path.suffix + ".tmp")
    temporary.write_bytes(payload)
    temporary.replace(path)


class HttpResult:
    def __init__(self, status_code: int, content: bytes) -> None:
        self.status_code = status_code
        self.content = content
        self.reason_phrase = str(status_code)


def request_bytes(url: str, params: dict | None = None, timeout: float = 180.0) -> HttpResult:
    """Download with urllib. httpx stalls against some hosts on this machine."""
    import time
    import urllib.error
    import urllib.request
    from urllib.parse import urlencode

    query = urlencode({key: value for key, value in (params or {}).items() if value is not None})
    if query:
        target = f"{url}&{query}" if "?" in url else f"{url}?{query}"
    else:
        target = url
    headers = {"User-Agent": "QuantRiskLab/0.1 research", "Accept": "*/*"}
    last_error: Exception | None = None
    for attempt in range(4):
        request = urllib.request.Request(target, headers=headers)
        try:
            with urllib.request.urlopen(request, timeout=timeout) as response:
                return HttpResult(response.status, response.read())
        except urllib.error.HTTPError as exc:
            body = exc.read()
            if exc.code in {429, 500, 502, 503, 504} and attempt < 3:
                time.sleep(1.5 * (attempt + 1))
                continue
            return HttpResult(exc.code, body)
        except (urllib.error.URLError, TimeoutError, ConnectionError) as exc:
            last_error = exc
            if attempt == 3:
                raise
            time.sleep(1.5 * (attempt + 1))
    raise last_error or RuntimeError("请求失败")


def relpath(path: Path, root: Path) -> str:
    return path.relative_to(root).as_posix()


def iso(value: date | None) -> str | None:
    return value.isoformat() if value else None
