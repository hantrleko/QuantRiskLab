"""数据源错误。公开 URL 不含密钥。"""

from __future__ import annotations

from quantrisklab.redact import redact


class SourceFailure(Exception):
    def __init__(
        self,
        source: str,
        series_id: str | None,
        url: str,
        status: int | None,
        error: str,
    ) -> None:
        safe = redact(error)
        super().__init__(safe)
        self.source = source
        self.series_id = series_id
        self.url = url
        self.status = status
        self.error = safe

    def as_dict(self) -> dict:
        return {
            "source": self.source,
            "series_id": self.series_id,
            "url": self.url,
            "status": self.status,
            "error": self.error,
        }
