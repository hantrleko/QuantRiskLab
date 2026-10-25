"""Documented information clocks. These are rules, not reconstructed historical timestamps."""

from __future__ import annotations

from datetime import datetime, timezone

from quantrisklab.paths import DB_PATH

# Standing publication conventions. None of these fields is a verified historical clock
# for each observation. available_at_utc is therefore omitted rather than invented.
RULES = [
    {
        "series_id": "DFF",
        "observation_date": "前一美国营业日",
        "release_at_utc": None,
        "available_at_utc": None,
        "ingested_at_utc": None,
        "vintage_id": None,
        "availability_quality": "date_approximate",
        "source_timezone": "America/New_York",
        "availability_rule": "纽约联储说明有效联邦基金利率在下一营业日上午约 9:00（美东）公布前一营业日数值。库内 release_date 仍等于观测日，这只是日级近似，不是逐笔核实的发布时间。",
    },
    {
        "series_id": "DGS2",
        "observation_date": "H.15 利率所对应的营业日",
        "release_at_utc": None,
        "available_at_utc": None,
        "ingested_at_utc": None,
        "vintage_id": None,
        "availability_quality": "rule_based_intraday_unverified",
        "source_timezone": "America/New_York",
        "availability_rule": "美联储 H.15 选定利率的现行惯例是美东时间 16:15 发布。该时刻没有逐日回填到历史记录。当天美股收盘时不能默认已经看到当日收益率。",
    },
    {
        "series_id": "DGS10",
        "observation_date": "H.15 利率所对应的营业日",
        "release_at_utc": None,
        "available_at_utc": None,
        "ingested_at_utc": None,
        "vintage_id": None,
        "availability_quality": "rule_based_intraday_unverified",
        "source_timezone": "America/New_York",
        "availability_rule": "与 DGS2 相同。库内 release_date 等于观测日，质量标记为未逐日核实的日内惯例。",
    },
    {
        "series_id": "DFII10",
        "observation_date": "H.15 实际收益率所对应的营业日",
        "release_at_utc": None,
        "available_at_utc": None,
        "ingested_at_utc": None,
        "vintage_id": None,
        "availability_quality": "rule_based_intraday_unverified",
        "source_timezone": "America/New_York",
        "availability_rule": "与 DGS10 相同，沿用 H.15 16:15（美东）的现行惯例。该时刻没有逐日回填。",
    },
    {
        "series_id": "T10YIE",
        "observation_date": "H.15 盈亏平衡通胀率所对应的营业日",
        "release_at_utc": None,
        "available_at_utc": None,
        "ingested_at_utc": None,
        "vintage_id": None,
        "availability_quality": "rule_based_intraday_unverified",
        "source_timezone": "America/New_York",
        "availability_rule": "与 DGS10 相同，沿用 H.15 16:15（美东）的现行惯例。该时刻没有逐日回填。",
    },
    {
        "series_id": "DTWEXBGS",
        "observation_date": "美元指数所对应的营业日",
        "release_at_utc": None,
        "available_at_utc": None,
        "ingested_at_utc": None,
        "vintage_id": None,
        "availability_quality": "date_approximate",
        "source_timezone": "America/New_York",
        "availability_rule": "广义美元指数按观测日入库。没有逐日核实的发布时刻，因此 available_at_utc 留空。",
    },
    {
        "series_id": "T10Y2Y",
        "observation_date": "由 DGS10 减 DGS2",
        "release_at_utc": None,
        "available_at_utc": None,
        "ingested_at_utc": None,
        "vintage_id": None,
        "availability_quality": "mechanical_identity",
        "source_timezone": "America/New_York",
        "availability_rule": "利差是两个国债收益率的差，不是独立公布的交易价格。它的可得时间不早于两个分量中较晚的一个。",
    },
    {
        "series_id": "CPIAUCSL",
        "observation_date": "价格指数对应的月份",
        "release_at_utc": None,
        "available_at_utc": None,
        "ingested_at_utc": None,
        "vintage_id": "ALFRED realtime_start",
        "availability_quality": "vintage_date",
        "source_timezone": "America/New_York",
        "availability_rule": "ALFRED 的 realtime_start 是发布日期，不是日内时刻。修订对照只在日期层面有效。",
    },
    {
        "series_id": "CFTC",
        "observation_date": "持仓报告的周二",
        "release_at_utc": None,
        "available_at_utc": None,
        "ingested_at_utc": None,
        "vintage_id": None,
        "availability_quality": "official_calendar_date",
        "source_timezone": "America/New_York",
        "availability_rule": "公布惯例是同周周五美东 15:30。周三至周五遇美国联邦假日则顺延到下一营业日。日期与 cftc.py 及 2026 官方日历样本一致；15:30 没有写成每条记录的 available_at_utc。",
    },
]


def availability_catalog() -> dict:
    return {
        "clock": "v1.0",
        "fields": [
            "observation_date",
            "release_at_utc",
            "available_at_utc",
            "ingested_at_utc",
            "vintage_id",
            "availability_quality",
            "source_timezone",
            "availability_rule",
        ],
        "note": "无法从公开历史文件逐条恢复精确发布时间的记录，不填写 available_at_utc。日级 release_date 仍然保留，供旧接口使用。",
        "series": RULES,
    }


def snapshot_status() -> dict:
    if not DB_PATH.exists():
        return {"available": False, "reason": "没有数据库快照"}
    modified = datetime.fromtimestamp(DB_PATH.stat().st_mtime, tz=timezone.utc)
    return {
        "available": True,
        "snapshot_id": modified.strftime("%Y%m%dT%H%M%SZ"),
        "file_mtime_utc": modified.isoformat(),
        "stale_flag_note": "series_meta.stale 在建库时写入。部署后的静态数据库不会按来源日历自动改写这个标记。",
        "refresh_note": "定期拉取尚未实现。在数据再分发许可确认前，不把自动更新写进生产任务。",
    }