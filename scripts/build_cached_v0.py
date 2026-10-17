"""Build the local store from cached FRED files. Does not rerun the full download."""

from __future__ import annotations

import logging

from quantrisklab.assemble_cache import assemble_cached
from quantrisklab.logging_setup import setup_logging
from quantrisklab.reporting import write_outputs


def main() -> int:
    setup_logging()
    logger = logging.getLogger("quantrisklab.build_cached")
    assemble_cached()
    try:
        return write_outputs()
    except Exception:
        logger.exception("缓存建库后的报告失败")
        return 1


if __name__ == "__main__":
    raise SystemExit(main())
