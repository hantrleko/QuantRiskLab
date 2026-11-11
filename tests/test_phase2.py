"""The long sample uses a real index id and a separate Moody spread."""

import math
from datetime import date

from quantrisklab.catalog import active_equity_id
from quantrisklab.metrics.structure import CRISIS_WINDOWS
from quantrisklab.paths import DB_PATH
from quantrisklab.store.database import connect_readonly
from quantrisklab.studio import compare_windows, replay_track


def test_crisis_list_includes_the_prespecified_2008_window():
    found = [item for item in CRISIS_WINDOWS if item["id"] == "gfc"]
    assert len(found) == 1
    assert found[0]["title"] == "2008 年金融危机"
    assert found[0]["start"].isoformat() == "2008-09-15"
    assert found[0]["end"].isoformat() == "2009-03-09"


def test_long_equity_and_baa_cover_2008_without_replacing_sp500():
    assert DB_PATH.exists()
    connection = connect_readonly()
    try:
        equity = active_equity_id(connection)
        assert equity != "SP500"
        equity_title = connection.execute(
            "SELECT title_zh FROM series_meta WHERE series_id = ?",
            [equity],
        ).fetchone()[0]
        assert "标普" not in equity_title
        credit_start = connection.execute(
            "SELECT MIN(observation_date) FROM observations WHERE series_id = 'BAA10Y' AND value IS NOT NULL"
        ).fetchone()[0]
        credit_title = connection.execute(
            "SELECT title_zh FROM series_meta WHERE series_id = 'BAA10Y'"
        ).fetchone()[0]
        sp_start = connection.execute(
            "SELECT MIN(observation_date) FROM observations WHERE series_id = 'SP500' AND value IS NOT NULL"
        ).fetchone()[0]
        oas_rows = connection.execute(
            "SELECT COUNT(*) FROM observations WHERE series_id = 'BAMLC0A0CM' AND value IS NOT NULL"
        ).fetchone()[0]
        unrate_start = connection.execute(
            "SELECT MIN(observation_date) FROM observations WHERE series_id = 'UNRATE' AND value IS NOT NULL"
        ).fetchone()[0]
        library_start = connection.execute(
            "SELECT MIN(observation_date) FROM observations WHERE value IS NOT NULL"
        ).fetchone()[0]
        replay = replay_track(connection, date(2008, 9, 15), 63)
        compared = compare_windows(connection, date(2009, 3, 31), ["gfc"])
    finally:
        connection.close()
    assert str(credit_start)[:10] <= "2008-09-15"
    assert credit_title == "穆迪 Baa 与 10 年国债利差"
    assert "OAS" not in credit_title
    assert str(sp_start)[:10].startswith("2016-10")
    assert oas_rows > 0
    assert unrate_start is not None and str(unrate_start)[:4] <= "2008"
    assert str(library_start)[:4] <= "2000"
    assert replay["equity_id"] == equity
    assert replay["equity_title"] == equity_title
    assert replay["coverage"][equity]["rows"] > 0
    assert replay["coverage"]["SP500"]["rows"] == 0
    assert replay["coverage"]["SP500"]["start"].startswith("2016-10")
    window = compared["windows"][0]
    assert window["id"] == "gfc"
    assert isinstance(window["equity_return"], float)
    assert math.isfinite(window["equity_return"])
