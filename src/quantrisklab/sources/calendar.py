"""CFTC 公布日规则与美国联邦假日。

文件里的 As of Date 是仓位观测日（通常为周二），不是公布日。
CFTC 常规在同一周周五美东 15:30 公布。若该周五为联邦假日，则提前到前一个工作日。
这是文档化规则，不是文件内字段。Good Friday 等非联邦假日未计入。
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
    """观测日所在周的周五；遇联邦假日或周末则向前移到工作日。"""
    friday = observation_date + timedelta(days=(4 - observation_date.weekday()) % 7)
    if friday <= observation_date:
        friday += timedelta(days=7)
    holidays = holiday_set(friday)
    release = friday
    for _ in range(5):
        if release.weekday() < 5 and release not in holidays:
            return release
        release -= timedelta(days=1)
    return release


RELEASE_RULE = "cftc_same_week_friday_1530ET_prior_business_day_if_federal_holiday"
