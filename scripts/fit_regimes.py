"""Fit the offline two-state models into the local snapshot.

This does not call FRED. The public demo must not run it.
"""

from __future__ import annotations

import os


def main() -> int:
    if os.environ.get("QUANTRISKLAB_PUBLIC") == "1":
        print("公网部署不估计状态。")
        return 2
    from quantrisklab.regimes import store_regimes

    return store_regimes()


if __name__ == "__main__":
    raise SystemExit(main())