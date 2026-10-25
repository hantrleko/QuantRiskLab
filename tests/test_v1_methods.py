"""V1.0 methods stay descriptive and do not invent missing series."""

from datetime import date

from quantrisklab.paths import DB_PATH
from quantrisklab.store.database import connect_readonly
from quantrisklab.studio import compare_windows, explore_pair
from quantrisklab.research import research_payload


def test_rolling_correlation_uses_history_before_the_display_window():
    assert DB_PATH.exists()
    connection = connect_readonly()
    try:
        pair = explore_pair(connection, date(2026, 10, 17), "SP500", "DCOILWTICO", 63)
    finally:
        connection.close()
    assert pair["eligible"] is True
    assert pair["n"] <= 63
    assert len(pair["rolling"]) > pair["n"]
    assert pair["rolling_on"] == "full_visible_history"


def test_custom_compare_cannot_pass_the_as_of_date():
    assert DB_PATH.exists()
    connection = connect_readonly()
    try:
        payload = compare_windows(
            connection,
            date(2020, 3, 1),
            [],
            custom=(date(2020, 2, 20), date(2020, 3, 23)),
        )
    finally:
        connection.close()
    row = payload["windows"][0]
    assert row["id"] == "custom"
    assert row["end"] == "2020-03-01"
    assert row["partial"] is True


def test_research_blocks_do_not_fill_missing_inputs():
    assert DB_PATH.exists()
    connection = connect_readonly()
    try:
        payload = research_payload(connection, date(2026, 10, 17), 252)
    finally:
        connection.close()
    decomposition = payload["decomposition"]
    assert decomposition["status"] in {"available", "unavailable"}
    if decomposition["status"] == "unavailable":
        assert decomposition["residual"] is None
    else:
        latest = decomposition["latest"]
        assert abs(latest["residual"] - (latest["nominal"] - latest["real"] - latest["breakeven"])) < 1e-8
    euler = payload["euler"]
    assert euler["weights"] == [0.5, 0.5]
    if euler["eligible"]:
        assert abs(sum(euler["shares"]) - 1) < 1e-6
    assert "约化" in payload["local_projection"]["label"]
    for market in payload["crowding"]["markets"]:
        assert market["release_date"] <= "2026-10-17"
        assert market["observation_date"] <= "2026-10-17"
