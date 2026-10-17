"""Read the point-in-time store and shape chart payloads. No synthetic series."""

from __future__ import annotations

import math
from datetime import date, datetime

import numpy as np
import pandas as pd
import polars as pl

from quantrisklab.metrics.risk import (
    change_correlation_matrix,
    correlation_matrix,
    quarterly_realized_vol,
    summarize_level,
    summarize_price,
)
from quantrisklab.store.pit import query_series

LEVEL_ROLES = {"yield", "spread", "volatility_index"}


def sanitize(value):
    if isinstance(value, dict):
        return {str(key): sanitize(item) for key, item in value.items()}
    if isinstance(value, (list, tuple)):
        return [sanitize(item) for item in value]
    if isinstance(value, (datetime, date)):
        return value.isoformat()
    if isinstance(value, (np.integer,)):
        return int(value)
    if isinstance(value, (np.bool_,)):
        return bool(value)
    if isinstance(value, (float, np.floating)):
        number = float(value)
        if not math.isfinite(number):
            return None
        return number
    if isinstance(value, pd.Timestamp):
        return value.date().isoformat()
    return value


def filter_window(frame: pl.DataFrame, start: date | None, end: date | None) -> pl.DataFrame:
    if frame.is_empty():
        return frame
    out = frame
    if start is not None:
        out = out.filter(pl.col("observation_date") >= start)
    if end is not None:
        out = out.filter(pl.col("observation_date") <= end)
    return out


def visible_series(connection, series_id: str, as_of: date, start: date | None, end: date | None) -> pl.DataFrame:
    return filter_window(query_series(connection, series_id, as_of), start, end)


def all_meta(connection) -> list[dict]:
    arrow = connection.execute("SELECT * FROM series_meta ORDER BY series_id").to_arrow_table()
    frame = pl.from_arrow(arrow)
    if frame.is_empty():
        return []
    rows = []
    for row in frame.to_dicts():
        row["price_metrics"] = bool(row.get("price_metrics"))
        row["stale"] = bool(row.get("stale"))
        rows.append(row)
    return rows


def one_meta(connection, series_id: str) -> dict | None:
    for row in all_meta(connection):
        if row["series_id"] == series_id:
            return row
    return None


def observations_payload(connection, series_id: str, as_of: date, start: date | None, end: date | None) -> dict | None:
    meta = one_meta(connection, series_id)
    if meta is None:
        return None
    frame = visible_series(connection, series_id, as_of, start, end)
    points = []
    if frame.height:
        for row in frame.select(["observation_date", "value", "release_date"]).iter_rows(named=True):
            points.append(
                {
                    "observation_date": row["observation_date"].isoformat(),
                    "value": None if row["value"] is None else float(row["value"]),
                    "release_date": row["release_date"].isoformat(),
                }
            )
    return {
        "series_id": series_id,
        "title_zh": meta["title_zh"],
        "unit": meta["unit"],
        "frequency": meta["frequency"],
        "source": meta["source"],
        "role": meta["role"],
        "price_metrics": meta["price_metrics"],
        "stale": meta["stale"],
        "as_of": as_of.isoformat(),
        "caveat": meta["notes"],
        "release_rule": meta["release_rule"],
        "observations": points,
    }


def metrics_payload(
    connection,
    series_id: str,
    as_of: date,
    start: date | None,
    end: date | None,
    window: int,
    alpha: float,
) -> dict | None:
    meta = one_meta(connection, series_id)
    if meta is None:
        return None
    frame = visible_series(connection, series_id, as_of, start, end)
    if meta["price_metrics"]:
        try:
            summary = summarize_price(frame, window, alpha)
        except Exception as exc:
            summary = {"eligible": False, "reason": str(exc)}
    else:
        summary = summarize_level(frame)
    summary["series_id"] = series_id
    summary["title_zh"] = meta["title_zh"]
    summary["stale"] = meta["stale"]
    summary["as_of"] = as_of.isoformat()
    if meta["stale"]:
        summary["stale_note"] = "序列已滞后或停更。指标只覆盖真实观测，末端之后没有外推。"
    return summary


def _frames(connection, ids: list[str], as_of: date, start: date | None, end: date | None) -> dict[str, pl.DataFrame]:
    return {series_id: visible_series(connection, series_id, as_of, start, end) for series_id in ids}


def _rolling(series: dict[str, pl.DataFrame], left: str, right: str, window: int, mode: str) -> dict:
    if left not in series or right not in series:
        return {"eligible": False, "reason": "滚动相关缺少序列"}
    left_frame = _to_pdf(series[left])
    right_frame = _to_pdf(series[right])
    if left_frame.empty or right_frame.empty:
        return {"eligible": False, "reason": "滚动相关没有重叠样本"}
    left_frame = left_frame.copy()
    right_frame = right_frame.copy()
    if mode == "return":
        left_frame["metric"] = left_frame["value"].pct_change()
        right_frame["metric"] = right_frame["value"].pct_change()
        note = "滚动相关使用价格简单收益。"
    else:
        left_frame["metric"] = left_frame["value"].diff()
        right_frame["metric"] = right_frame["value"].diff()
        note = "滚动相关使用水平值一阶差分，不是资产收益。"
    merged = left_frame[["observation_date", "metric"]].merge(
        right_frame[["observation_date", "metric"]],
        on="observation_date",
        suffixes=("_left", "_right"),
    )
    merged = merged.dropna()
    if merged.shape[0] < window:
        return {"eligible": False, "reason": "重叠样本短于滚动窗口", "note": note}
    merged["rolling"] = merged["metric_left"].rolling(window).corr(merged["metric_right"])
    points = []
    for row in merged.dropna(subset=["rolling"]).itertuples(index=False):
        points.append(
            {
                "observation_date": pd.Timestamp(row.observation_date).date().isoformat(),
                "value": float(row.rolling),
            }
        )
    return {
        "eligible": bool(points),
        "left": left,
        "right": right,
        "window": window,
        "mode": mode,
        "note": note,
        "points": points,
    }


def _to_pdf(frame: pl.DataFrame) -> pd.DataFrame:
    if frame.is_empty():
        return pd.DataFrame(columns=["observation_date", "value"])
    pdf = frame.select(["observation_date", "value"]).to_pandas()
    pdf["observation_date"] = pd.to_datetime(pdf["observation_date"])
    return pdf.dropna(subset=["value"]).sort_values("observation_date")


def correlation_payload(connection, as_of: date, start: date | None, end: date | None, window: int) -> dict:
    metas = all_meta(connection)
    price_ids = [row["series_id"] for row in metas if row["price_metrics"]]
    level_ids = [row["series_id"] for row in metas if row["role"] in LEVEL_ROLES]
    labels = {row["series_id"]: row["title_zh"] for row in metas}
    price = correlation_matrix(_frames(connection, price_ids, as_of, start, end), window)
    level = change_correlation_matrix(_frames(connection, level_ids, as_of, start, end), window)
    price["labels_zh"] = [labels.get(item, item) for item in price.get("labels") or []]
    level["labels_zh"] = [labels.get(item, item) for item in level.get("labels") or []]
    rolling = {"eligible": False, "reason": "没有足够序列"}
    if "DGS10" in level_ids and "DGS2" in level_ids:
        rolling = _rolling(_frames(connection, ["DGS10", "DGS2"], as_of, start, end), "DGS10", "DGS2", window, "difference")
    elif len(price_ids) >= 2:
        rolling = _rolling(
            _frames(connection, price_ids[:2], as_of, start, end),
            price_ids[0],
            price_ids[1],
            window,
            "return",
        )
    return {"as_of": as_of.isoformat(), "window": window, "price_returns": price, "level_changes": level, "rolling": rolling}


def _quarter_map(rows: list[dict], value_key: str) -> dict[str, float | None]:
    return {row["quarter"]: row.get(value_key) for row in rows}


def quarterly_difference_scale(frame: pl.DataFrame) -> list[dict]:
    pdf = _to_pdf(frame)
    if pdf.empty:
        return []
    pdf = pdf.copy()
    pdf["delta"] = pdf["value"].diff()
    pdf = pdf.dropna(subset=["delta"])
    pdf["quarter"] = pdf["observation_date"].dt.to_period("Q").astype(str)
    rows = []
    for quarter, part in pdf.groupby("quarter", sort=True):
        scale = None
        if len(part) >= 40:
            scale = float(part["delta"].std(ddof=1))
        rows.append({"quarter": str(quarter), "scale": scale, "n": int(len(part))})
    return rows


def _align(columns: list[str], mapping: dict[str, float | None]) -> list[float | None]:
    return [mapping.get(column) for column in columns]


def heatmap_payload(connection, as_of: date, start: date | None, end: date | None) -> dict:
    metas = all_meta(connection)
    price_rows = []
    level_rows = []
    price_quarters: set[str] = set()
    level_quarters: set[str] = set()
    price_maps = []
    level_maps = []
    for meta in metas:
        frame = visible_series(connection, meta["series_id"], as_of, start, end)
        if meta["price_metrics"]:
            rows = quarterly_realized_vol(frame)
            mapping = _quarter_map(rows, "realized_vol")
            price_maps.append((meta, mapping))
            price_quarters.update(mapping)
        elif str(meta.get("frequency") or "").lower().startswith("daily") and meta["role"] in LEVEL_ROLES:
            rows = quarterly_difference_scale(frame)
            mapping = _quarter_map(rows, "scale")
            level_maps.append((meta, mapping))
            level_quarters.update(mapping)
    price_columns = _tail(sorted(price_quarters), 24)
    level_columns = _tail(sorted(level_quarters), 24)
    for meta, mapping in price_maps:
        price_rows.append(
            {
                "series_id": meta["series_id"],
                "label": meta["title_zh"],
                "stale": meta["stale"],
                "values": _align(price_columns, mapping),
            }
        )
    for meta, mapping in level_maps:
        level_rows.append(
            {
                "series_id": meta["series_id"],
                "label": meta["title_zh"],
                "stale": meta["stale"],
                "values": _align(level_columns, mapping),
            }
        )
    return {
        "as_of": as_of.isoformat(),
        "price_vol": {
            "title": "价格实现波动率",
            "unit": "年化简单收益标准差",
            "caveat": "由季度内价格简单收益估计，年化系数 252。不是期权隐含波动率，不含费用或股息。停更序列只画到最后真实观测。",
            "columns": price_columns,
            "rows": price_rows,
        },
        "level_scale": {
            "title": "水平值变动尺度",
            "unit": "季度内一阶差分的标准差（原序列单位）",
            "caveat": "这不是资产波动率，也不是久期调整后的债券风险。利率、利差和 VIX 都保持各自单位。",
            "columns": level_columns,
            "rows": level_rows,
        },
    }


def _tail(values: list[str], limit: int) -> list[str]:
    if len(values) <= limit:
        return values
    return values[-limit:]


def positions_payload(connection, as_of: date, start: date | None, end: date | None) -> dict:
    clauses = ["release_date <= ?", "observation_date <= ?"]
    params: list = [as_of, as_of]
    if start is not None:
        clauses.append("observation_date >= ?")
        params.append(start)
    if end is not None:
        clauses.append("observation_date <= ?")
        params.append(end)
    sql = f"""
        SELECT market_id, title_zh, observation_date, release_date, net_positions, open_interest
        FROM cftc_positions
        WHERE {' AND '.join(clauses)}
        ORDER BY market_id, observation_date
    """
    arrow = connection.execute(sql, params).to_arrow_table()
    frame = pl.from_arrow(arrow)
    grouped: dict[str, dict] = {}
    if frame.height:
        for row in frame.iter_rows(named=True):
            item = grouped.setdefault(
                row["market_id"],
                {"market_id": row["market_id"], "title_zh": row["title_zh"], "points": []},
            )
            item["points"].append(
                {
                    "observation_date": row["observation_date"].isoformat()
                    if hasattr(row["observation_date"], "isoformat")
                    else str(row["observation_date"])[:10],
                    "release_date": row["release_date"].isoformat()
                    if hasattr(row["release_date"], "isoformat")
                    else str(row["release_date"])[:10],
                    "net_positions": None if row["net_positions"] is None else float(row["net_positions"]),
                    "open_interest": None if row["open_interest"] is None else float(row["open_interest"]),
                }
            )
    return {
        "as_of": as_of.isoformat(),
        "caveat": "净持仓 = 多头合约减空头合约。观测日通常是周二，公布日更晚。观测日当天查不到本期仓位。持仓不是价格，不计算收益或 VaR。",
        "series": list(grouped.values()),
    }


def vintage_dates(connection, series_id: str) -> list[str]:
    arrow = connection.execute(
        """
        SELECT DISTINCT release_date
        FROM observations
        WHERE series_id = ?
        ORDER BY release_date
        """,
        [series_id],
    ).to_arrow_table()
    frame = pl.from_arrow(arrow)
    if frame.is_empty():
        return []
    values = []
    for item in frame["release_date"].to_list():
        if hasattr(item, "isoformat"):
            values.append(item.isoformat() if not isinstance(item, datetime) else item.date().isoformat())
        else:
            values.append(str(item)[:10])
    return values


def descriptive_yield_link(connection, as_of: date, start: date | None, end: date | None) -> dict:
    needed = {"DGS10", "DGS2"}
    have = {row["series_id"] for row in all_meta(connection)}
    if not needed <= have:
        return {"available": False, "reason": "缺少 DGS10 或 DGS2，不做描述性回归。"}
    frames = _frames(connection, ["DGS10", "DGS2"], as_of, start, end)
    left = _to_pdf(frames["DGS10"])
    right = _to_pdf(frames["DGS2"])
    if left.empty or right.empty:
        return {"available": False, "reason": "收益率样本为空。"}
    merged = left.rename(columns={"value": "dgs10"}).merge(
        right.rename(columns={"value": "dgs2"}),
        on="observation_date",
        how="inner",
    )
    changes = merged[["dgs10", "dgs2"]].diff().dropna()
    if len(changes) < 30:
        return {"available": False, "reason": "差分样本少于 30，不做回归。"}
    import statsmodels.api as sm

    model = sm.OLS(changes["dgs10"], sm.add_constant(changes["dgs2"])).fit()
    params = [float(value) for value in model.params]
    pvalues = [float(value) for value in model.pvalues]
    return {
        "available": True,
        "y": "DGS10",
        "x": "DGS2",
        "spec": "ΔDGS10 = a + b ΔDGS2 + e",
        "n": int(model.nobs),
        "beta": params[1],
        "r2": float(model.rsquared),
        "beta_pvalue": pvalues[1],
        "sample_start": pd.Timestamp(merged["observation_date"].iloc[0]).date().isoformat(),
        "sample_end": pd.Timestamp(merged["observation_date"].iloc[-1]).date().isoformat(),
        "caveat": "这是样本内描述统计，不是因果识别，不是预测，也不构成买卖建议。",
    }
