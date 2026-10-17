"""V0.4 studio views reuse the verified transforms and point-in-time filter."""

from datetime import date

import pandas as pd

from quantrisklab.metrics.structure import _window_return
from quantrisklab.paths import DB_PATH
from quantrisklab.store.database import connect_readonly
from quantrisklab.studio import TRANSFORMS, compare_windows, explore_pair, replay_track, tail_laboratory


def test_price_and_yield_transforms_stay_distinct():
    assert TRANSFORMS["SP500"] == "simple_return"
    assert TRANSFORMS["DGS10"] == "difference"
    assert TRANSFORMS["VIXCLS"] == "level"
    assert TRANSFORMS["T10Y2Y"] == "difference"


def test_negative_price_window_is_not_a_compound_return():
    frame = pd.DataFrame(
        {
            "observation_date": pd.to_datetime(["2020-04-17", "2020-04-20", "2020-04-21"]),
            "value": [18.27, -36.98, 10.0],
        }
    )
    result = _window_return(frame, date(2020, 4, 17), date(2020, 4, 21))
    assert result["value"] is None
    assert result["status"] == "not_computable"


def test_tail_lab_refuses_a_yield_level():
    assert DB_PATH.exists()
    connection = connect_readonly()
    try:
        payload = tail_laboratory(connection, date(2026, 10, 17), "DGS10", "SP500", 0.05)
    finally:
        connection.close()
    assert payload["eligible"] is False


def test_replay_cannot_see_past_the_selected_date():
    assert DB_PATH.exists()
    connection = connect_readonly()
    try:
        early = replay_track(connection, date(2012, 1, 3), 63)
        late = compare_windows(connection, date(2012, 1, 3), ["covid", "taper"])
        pair = explore_pair(connection, date(2026, 10, 17), "T10Y2Y", "DGS10", 63)
    finally:
        connection.close()
    assert all(point["date"] <= "2012-01-03" for point in early["points"])
    assert "covid" not in {row["id"] for row in late["windows"]}
    assert pair["mechanical"] is True
    assert "恒等式" in pair["interpretation"]
