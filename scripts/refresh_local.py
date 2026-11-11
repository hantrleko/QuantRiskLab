"""Update the local DuckDB from FRED and CFTC.

The public demo does not run this script and does not call FRED. The key stays
in the local environment or in F:\\AI\\API\\FRED.docx. It is not printed.
"""

from __future__ import annotations

import os


def main() -> int:
    if os.environ.get("QUANTRISKLAB_PUBLIC") == "1":
        print("公网部署只提供演示快照，不请求 FRED。")
        return 2
    from extend_v22 import main as extend_main

    code = extend_main()
    if code != 0:
        return code
    from fit_regimes import main as fit_main

    return fit_main()


if __name__ == "__main__":
    raise SystemExit(main())
