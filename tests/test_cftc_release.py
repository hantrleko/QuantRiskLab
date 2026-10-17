"""CFTC publication dates stay after the position observation date."""

from datetime import date

from quantrisklab.sources.cftc import cftc_release_date

# Checked against the CFTC 2026 release calendar. Starred dates are delayed.
OFFICIAL_2026 = {
    date(2025, 12, 30): date(2026, 1, 5),
    date(2026, 1, 6): date(2026, 1, 9),
    date(2026, 6, 16): date(2026, 6, 22),
    date(2026, 6, 30): date(2026, 7, 6),
    date(2026, 11, 10): date(2026, 11, 16),
    date(2026, 11, 24): date(2026, 11, 30),
    date(2026, 12, 22): date(2026, 12, 28),
}


def test_official_2026_release_dates():
    for observation, release in OFFICIAL_2026.items():
        assert observation.weekday() == 1
        assert cftc_release_date(observation) == release
        assert release > observation


def test_observation_tuesday_is_not_the_release_date():
    observation = date(2026, 1, 6)
    release = cftc_release_date(observation)
    assert release != observation
    assert release.weekday() < 5
