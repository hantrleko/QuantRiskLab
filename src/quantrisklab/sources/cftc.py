"""CFTC COT parser.

Publication rule, checked against the 2026 official release calendar
(https://www.cftc.gov/MarketReports/CommitmentsofTraders/ReleaseSchedule/index.htm):

The report date in the file is the position observation date, usually Tuesday.
The public release is Friday 15:30 US Eastern of that week. If a US federal
holiday falls on Wednesday, Thursday, or Friday of that week, the release moves
to the next business day, and one further business day if that day is also a
holiday. The observation date is never used as the release date.
"""

from __future__ import annotations

import csv
import io
import logging
import zipfile
from datetime import date, datetime, timedelta

import polars as pl

from quantrisklab.catalog import CFTC_MARKETS

logger = logging.getLogger("quantrisklab.cftc")

POSITION_COLUMNS = {
    "managed_money": ("m_money_positions_long_all", "m_money_positions_short_all"),
    "leveraged_funds": ("lev_money_positions_long_all", "lev_money_positions_short_all"),
}


def _nth_weekday(year: int, month: int, weekday: int, n: int) -> date:
    first = date(year, month, 1)
    shift = (weekday - first.weekday()) % 7
    return first + timedelta(days=shift + 7 * (n - 1))


def _last_weekday(year: int, month: int, weekday: int) -> date:
    if month == 12:
        cursor = date(year + 1, 1, 1) - timedelta(days=1)
    else:
        cursor = date(year, month + 1, 1) - timedelta(days=1)
    while cursor.weekday() != weekday:
        cursor -= timedelta(days=1)
    return cursor


def _observed(day: date) -> date:
    if day.weekday() == 5:
        return day - timedelta(days=1)
    if day.weekday() == 6:
        return day + timedelta(days=1)
    return day


def us_federal_holidays(year: int) -> set[date]:
    holidays = {
        _observed(date(year, 1, 1)),
        _nth_weekday(year, 1, 0, 3),
        _nth_weekday(year, 2, 0, 3),
        _last_weekday(year, 5, 0),
        _observed(date(year, 7, 4)),
        _nth_weekday(year, 9, 0, 1),
        _nth_weekday(year, 10, 0, 2),
        _observed(date(year, 11, 11)),
        _nth_weekday(year, 11, 3, 4),
        _observed(date(year, 12, 25)),
    }
    if year >= 2021:
        holidays.add(_observed(date(year, 6, 19)))
    return holidays


def is_us_federal_holiday(day: date) -> bool:
    holidays: set[date] = set()
    for year in (day.year - 1, day.year, day.year + 1):
        holidays |= us_federal_holidays(year)
    return day in holidays


def next_business_day(day: date) -> date:
    cursor = day + timedelta(days=1)
    while cursor.weekday() >= 5 or is_us_federal_holiday(cursor):
        cursor += timedelta(days=1)
    return cursor


def cftc_release_date(observation_date: date) -> date:
    """Map a COT position date to its public release date. Never returns the observation date."""
    if observation_date.weekday() > 4:
        raise ValueError(f"COT 观测日不是工作日：{observation_date.isoformat()}")
    friday = observation_date + timedelta(days=(4 - observation_date.weekday()))
    if friday <= observation_date:
        raise ValueError(f"无法从观测日推出同周周五：{observation_date.isoformat()}")
    wednesday = friday - timedelta(days=2)
    thursday = friday - timedelta(days=1)
    if any(is_us_federal_holiday(day) for day in (wednesday, thursday, friday)):
        release = next_business_day(friday)
        if is_us_federal_holiday(release):
            release = next_business_day(release)
        if release == observation_date:
            raise ValueError("发布日被错误地算成了观测日")
        return release
    return friday


def classify_market(name: str) -> str | None:
    compact = " ".join(name.upper().replace("–", "-").split())
    if "MICRO" in compact or "SPREAD" in compact or "OPTION" in compact:
        return None
    if compact.startswith("GOLD - COMMODITY EXCHANGE"):
        return "gold"
    if "CRUDE OIL, LIGHT SWEET" in compact and "BRENT" not in compact and "CALENDAR" not in compact:
        return "wti"
    if "E-MINI S&P 500" in compact:
        return "sp500"
    if "ULTRA" in compact:
        return None
    if (
        "10-YEAR U.S. TREASURY NOTES" in compact
        or "UST 10Y NOTE" in compact
        or "10-YEAR UST NOTE" in compact
        or "10 YEAR U.S. TREASURY NOTE" in compact
    ):
        return "ust10y"
    return None


def _norm_header(name: str) -> str:
    return name.strip().lstrip("\ufeff").lower().replace(" ", "_")


def _to_float(raw: str | None) -> float | None:
    if raw is None:
        return None
    text = raw.strip().replace(",", "")
    if text in {"", ".", "NA", "null"}:
        return None
    return float(text)


def parse_cot_zip(payload: bytes, report_family: str, source_name: str) -> pl.DataFrame:
    with zipfile.ZipFile(io.BytesIO(payload)) as archive:
        text_names = [name for name in archive.namelist() if name.lower().endswith(".txt")]
        if not text_names:
            raise ValueError(f"{source_name} 压缩包里没有 txt")
        member = max(text_names, key=lambda name: archive.getinfo(name).file_size)
        raw_text = archive.read(member)
    try:
        text = raw_text.decode("utf-8-sig")
    except UnicodeDecodeError:
        text = raw_text.decode("cp1252")
    reader = csv.DictReader(io.StringIO(text))
    if not reader.fieldnames:
        raise ValueError(f"{source_name} 没有表头")
    field_map = {_norm_header(name): name for name in reader.fieldnames}
    date_key = (
        field_map.get("report_date_as_yyyy-mm-dd")
        or field_map.get("as_of_date_in_form_yyyy-mm-dd")
        or next((original for key, original in field_map.items() if "yyyy-mm-dd" in key), None)
    )
    name_key = field_map.get("market_and_exchange_names")
    oi_key = field_map.get("open_interest_all")
    if not date_key or not name_key or not oi_key:
        raise ValueError(f"{source_name} 缺少日期、市场名称或未平仓列：{list(field_map)}")

    kept: list[dict] = []
    seen_names: dict[str, str] = {}
    samples: list[str] = []
    for row in reader:
        market_name = (row.get(name_key) or "").strip()
        upper_name = market_name.upper()
        if any(token in upper_name for token in ("GOLD", "CRUDE OIL", "S&P 500", "TREASURY", "UST 10")):
            if market_name not in samples and len(samples) < 40:
                samples.append(market_name)
        market_id = classify_market(market_name)
        if market_id is None:
            continue
        if CFTC_MARKETS[market_id]["report"] != report_family:
            continue
        seen_names[market_id] = market_name
        observation = datetime.strptime(row[date_key].strip(), "%Y-%m-%d").date()
        release = cftc_release_date(observation)
        group = CFTC_MARKETS[market_id]["group"]
        long_col, short_col = POSITION_COLUMNS[group]
        if long_col not in field_map or short_col not in field_map:
            raise ValueError(f"{source_name} 缺少持仓列 {long_col}/{short_col}")
        long_pos = _to_float(row.get(field_map[long_col]))
        short_pos = _to_float(row.get(field_map[short_col]))
        open_interest = _to_float(row.get(oi_key))
        net = None if long_pos is None or short_pos is None else long_pos - short_pos
        ratio = None
        if net is not None and open_interest not in (None, 0):
            ratio = net / open_interest
        kept.append(
            {
                "market_id": market_id,
                "market_name": market_name,
                "title_zh": CFTC_MARKETS[market_id]["title_zh"],
                "report_family": report_family,
                "position_group": group,
                "position_group_zh": CFTC_MARKETS[market_id]["group_zh"],
                "observation_date": observation,
                "release_date": release,
                "open_interest": open_interest,
                "long_positions": long_pos,
                "short_positions": short_pos,
                "net_positions": net,
                "net_over_oi": ratio,
                "source_file": source_name,
            }
        )
    logger.info("parsed %s markets=%s rows=%s name_samples=%s", source_name, sorted(seen_names), len(kept), samples)
    if not kept:
        return pl.DataFrame(
            schema={
                "market_id": pl.Utf8,
                "market_name": pl.Utf8,
                "title_zh": pl.Utf8,
                "report_family": pl.Utf8,
                "position_group": pl.Utf8,
                "position_group_zh": pl.Utf8,
                "observation_date": pl.Date,
                "release_date": pl.Date,
                "open_interest": pl.Float64,
                "long_positions": pl.Float64,
                "short_positions": pl.Float64,
                "net_positions": pl.Float64,
                "net_over_oi": pl.Float64,
                "source_file": pl.Utf8,
            }
        )
    return pl.DataFrame(kept)
