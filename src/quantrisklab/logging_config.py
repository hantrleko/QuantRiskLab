"""标准日志。异常保留，但 traceback 里的密钥会被替换。"""

from __future__ import annotations

import logging
import traceback
from pathlib import Path

from quantrisklab.config import log_dir
from quantrisklab.redact import redact


class RedactFilter(logging.Filter):
    def filter(self, record: logging.LogRecord) -> bool:
        record.msg = redact(str(record.msg))
        if isinstance(record.args, dict):
            record.args = {
                key: redact(value) if isinstance(value, str) else value
                for key, value in record.args.items()
            }
        elif record.args:
            record.args = tuple(
                redact(value) if isinstance(value, str) else value for value in record.args
            )
        if record.exc_info:
            formatted = "".join(traceback.format_exception(*record.exc_info))
            record.exc_text = redact(formatted)
            record.exc_info = None
        elif record.exc_text:
            record.exc_text = redact(record.exc_text)
        return True


def setup_logging() -> None:
    root = logging.getLogger()
    if getattr(root, "_quantrisklab_configured", False):
        return
    log_dir().mkdir(parents=True, exist_ok=True)
    formatter = logging.Formatter(
        "%(asctime)s %(levelname)s %(name)s %(message)s",
        datefmt="%Y-%m-%d %H:%M:%S",
    )
    stream = logging.StreamHandler()
    stream.setFormatter(formatter)
    stream.addFilter(RedactFilter())
    file_handler = logging.FileHandler(Path(log_dir()) / "quantrisklab.log", encoding="utf-8")
    file_handler.setFormatter(formatter)
    file_handler.addFilter(RedactFilter())
    root.handlers.clear()
    root.addHandler(stream)
    root.addHandler(file_handler)
    root.setLevel(logging.INFO)
    logging.getLogger("httpx").setLevel(logging.WARNING)
    logging.getLogger("httpcore").setLevel(logging.WARNING)
    root._quantrisklab_configured = True  # type: ignore[attr-defined]
