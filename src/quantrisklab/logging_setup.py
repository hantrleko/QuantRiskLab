"""Logging that records failures and redacts the FRED API key."""

from __future__ import annotations

import logging
import os
import re

from quantrisklab.paths import LOG_DIR, ensure_dirs

_REDACT = re.compile(r"(api_key=)[^&\s\"']+", re.IGNORECASE)


def _redact_text(text: str) -> str:
    key = os.environ.get("FRED_API_KEY", "").strip()
    if key and key in text:
        text = text.replace(key, "[REDACTED]")
    return _REDACT.sub(r"\1[REDACTED]", text)


class RedactFilter(logging.Filter):
    def filter(self, record: logging.LogRecord) -> bool:
        message = record.getMessage()
        redacted = _redact_text(message)
        if redacted != message:
            record.msg = redacted
            record.args = ()
        if record.exc_info:
            import traceback

            record.exc_text = _redact_text("".join(traceback.format_exception(*record.exc_info)))
            record.exc_info = None
        elif record.exc_text:
            record.exc_text = _redact_text(record.exc_text)
        return True


def setup_logging() -> logging.Logger:
    ensure_dirs()
    logger = logging.getLogger("quantrisklab")
    logger.setLevel(logging.INFO)
    logger.handlers.clear()
    logger.propagate = False
    formatter = logging.Formatter(
        "%(asctime)s %(levelname)s %(name)s %(message)s",
        datefmt="%Y-%m-%d %H:%M:%S",
    )
    redact = RedactFilter()
    file_handler = logging.FileHandler(LOG_DIR / "quantrisklab.log", encoding="utf-8")
    file_handler.setFormatter(formatter)
    file_handler.addFilter(redact)
    stream_handler = logging.StreamHandler()
    stream_handler.setFormatter(formatter)
    stream_handler.addFilter(redact)
    logger.addHandler(file_handler)
    logger.addHandler(stream_handler)
    return logger
