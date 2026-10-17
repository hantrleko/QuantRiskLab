"""Download real public data, check integrity, and write the V0.1 ledger."""

from __future__ import annotations

import logging

from quantrisklab.logging_setup import setup_logging
from quantrisklab.pipeline import run
from quantrisklab.reporting import write_outputs


def main() -> int:
    setup_logging()
    logger = logging.getLogger("quantrisklab.reproduce")
    code = run()
    try:
        report_code = write_outputs()
    except Exception:
        logger.exception("报告或完整性检查失败")
        return 1
    return code or report_code


if __name__ == "__main__":
    raise SystemExit(main())
