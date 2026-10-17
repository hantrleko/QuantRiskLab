"""CFTC 公布日与美国联邦假日。

发布日只使用 sources/cftc.py 的规则，并与 CFTC 年度官方日历对照。
常规是同周周五美东 15:30。若周三、周四或周五是美国联邦假日，发布日顺延到下一营业日，
而不是提前到周四。Good Friday 等非联邦假日未计入。
"""

from __future__ import annotations

from datetime import date, timedelta


def nth_weekday(year: int, month: int, weekday: int, n: int) -> date:
    first = date(year, month, 1)
    shift = (weekday - first.weekday()) % 7
    return first + timedelta(days=shift + 7 * (n - 1))


def last_weekday(year: int, month: int, weekday: int) -> date:
    if month == 12:
        cursor = date(year + 1, 1, 1) - timedelta(days=1)
    else:
        cursor = date(year, month + 1, 1) - timedelta(days=1)
    return cursor - timedelta(days=(cursor.weekday() - weekday) % 7)


def observed_fixed(day: date) -> date:
    if day.weekday() == 5:
        return day - timedelta(days=1)
    if day.weekday() == 6:
        return day + timedelta(days=1)
    return day


def us_federal_holidays(year: int) -> set[date]:
    days = {
        observed_fixed(date(year, 1, 1)),
        nth_weekday(year, 1, 0, 3),
        nth_weekday(year, 2, 0, 3),
        last_weekday(year, 5, 0),
        observed_fixed(date(year, 7, 4)),
        nth_weekday(year, 9, 0, 1),
        nth_weekday(year, 10, 0, 2),
        observed_fixed(date(year, 11, 11)),
        nth_weekday(year, 11, 3, 4),
        observed_fixed(date(year, 12, 25)),
    }
    if year >= 2021:
        days.add(observed_fixed(date(year, 6, 19)))
    return days


def holiday_set(around: date) -> set[date]:
    days: set[date] = set()
    for year in range(around.year - 1, around.year + 2):
        days |= us_federal_holidays(year)
    return days


def cftc_release_date(observation_date: date) -> date:
    """与 cftc.py 同一实现。节假日导致的延迟向后顺延，不提前。"""
    from quantrisklab.sources.cftc import cftc_release_date as official_release_date

    return official_release_date(observation_date)


RELEASE_RULE = "cftc_same_week_friday_1530ET_next_business_day_if_wed_thu_fri_federal_holiday"
