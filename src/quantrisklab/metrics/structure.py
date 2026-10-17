"""Cross-asset structure around fast Treasury yield moves.

Every input frame must already be filtered by as_of. This module does not
download data and does not turn yield levels into asset returns.
"""

from __future__ import annotations

import logging
import math
from datetime import date

import numpy as np
import pandas as pd

from quantrisklab.metrics.risk import simple_returns
from quantrisklab.store.pit import query_series

logger = logging.getLogger("quantrisklab.structure")

HORIZON = 63
RATE_MOVE_THRESHOLD = 0.50
TAIL_ALPHA = 0.05
NETWORK_THRESHOLD = 0.35
SIMILAR_DISTANCE = 0.75

CRISIS_WINDOWS = (
    {"id": "taper", "title": "2013 年缩减讨论", "start": date(2013, 5, 22), "end": date(2013, 9, 18)},
    {"id": "calm2017", "title": "2017 年对照", "start": date(2017, 1, 3), "end": date(2017, 12, 29)},
    {"id": "covid", "title": "2020 年 3 月", "start": date(2020, 2, 20), "end": date(2020, 3, 23)},
    {"id": "hike2022", "title": "2022 年加息", "start": date(2022, 3, 16), "end": date(2022, 10, 31)},
)

PRICE_IDS = ("SP500", "DCOILWTICO")
LEVEL_IDS = ("DGS10", "DGS2", "DFF", "T10Y2Y", "VIXCLS", "BAMLC0A0CM")


def distinct_threshold_episodes(
    changes: pd.Series,
    horizon: int = HORIZON,
    threshold: float = RATE_MOVE_THRESHOLD,
) -> list[dict]:
    """Collapse consecutive threshold breaches into non-overlapping episodes.

    ``changes`` is indexed by observation date. A breach is |change| >= threshold.
    Breaches closer than ``horizon`` observations belong to one episode. The
    episode ends on the observation with the largest absolute change.
    """
    if horizon < 1:
        raise ValueError("horizon 必须为正")
    clean = changes.dropna()
    hits: list[tuple[int, float]] = []
    values = clean.to_numpy(dtype=float)
    index = list(clean.index)
    for position, value in enumerate(values):
        magnitude = abs(float(value))
        if math.isfinite(magnitude) and magnitude >= threshold:
            hits.append((position, magnitude))
    clusters: list[list[tuple[int, float]]] = []
    for hit in hits:
        if not clusters or hit[0] - clusters[-1][-1][0] > horizon:
            clusters.append([hit])
        else:
            clusters[-1].append(hit)
    episodes = []
    for cluster in clusters:
        end_pos, _magnitude = max(cluster, key=lambda item: item[1])
        start_pos = max(0, end_pos - horizon)
        change = float(values[end_pos])
        episodes.append(
            {
                "start": _iso(index[start_pos]),
                "end": _iso(index[end_pos]),
                "change": change,
                "abs_change": abs(change),
                "direction": "上升" if change > 0 else "下降",
                "n_breach_days": len(cluster),
            }
        )
    return episodes


def lower_tail_dependence(left: pd.Series, right: pd.Series, alpha: float = TAIL_ALPHA) -> dict:
    """Empirical lower-tail co-exceedance λ = P(X<qα, Y<qα) / α."""
    if not 0 < alpha < 0.5:
        raise ValueError("alpha 必须在 (0, 0.5) 内")
    paired = pd.concat([left.rename("left"), right.rename("right")], axis=1).dropna()
    if len(paired) < 40:
        return {"eligible": False, "reason": "尾部相关的重叠样本少于 40", "n": int(len(paired))}
    left_q = float(np.quantile(paired["left"], alpha))
    right_q = float(np.quantile(paired["right"], alpha))
    both = (paired["left"] <= left_q) & (paired["right"] <= right_q)
    return {
        "eligible": True,
        "reason": None,
        "alpha": alpha,
        "n": int(len(paired)),
        "lambda": float(both.mean() / alpha),
        "left_quantile": left_q,
        "right_quantile": right_q,
    }


def conditional_coexceedance(condition: pd.Series, target: pd.Series, alpha: float = TAIL_ALPHA) -> dict:
    """P(target < q_α | condition > q_{1-α}). Describes co-movement, not causality."""
    paired = pd.concat([condition.rename("condition"), target.rename("target")], axis=1).dropna()
    if len(paired) < 40:
        return {"eligible": False, "reason": "条件共超的重叠样本少于 40", "n": int(len(paired))}
    high = float(np.quantile(paired["condition"], 1 - alpha))
    low = float(np.quantile(paired["target"], alpha))
    subset = paired.loc[paired["condition"] >= high, "target"]
    if subset.empty:
        return {"eligible": False, "reason": "条件尾部没有样本", "n": int(len(paired))}
    return {
        "eligible": True,
        "reason": None,
        "alpha": alpha,
        "n": int(len(paired)),
        "n_condition": int(len(subset)),
        "probability": float((subset <= low).mean()),
        "condition_quantile": high,
        "target_quantile": low,
    }


def correlation_network(frame: pd.DataFrame, labels: dict[str, str], threshold: float = NETWORK_THRESHOLD) -> dict:
    columns = [column for column in frame.columns if frame[column].notna().sum() >= 20]
    if len(columns) < 2 or len(frame) < 20:
        return {"eligible": False, "reason": "网络样本不足", "nodes": [], "links": []}
    corr = frame[columns].corr()
    nodes = []
    links = []
    degree = {column: 0 for column in columns}
    for i, left in enumerate(columns):
        for right in columns[i + 1 :]:
            value = corr.loc[left, right]
            if not np.isfinite(value) or abs(float(value)) < threshold:
                continue
            degree[left] += 1
            degree[right] += 1
            links.append({"source": left, "target": right, "value": float(value)})
    for column in columns:
        nodes.append({"id": column, "name": labels.get(column, column), "degree": degree[column]})
    return {
        "eligible": True,
        "reason": None,
        "threshold": threshold,
        "n": int(len(frame)),
        "nodes": nodes,
        "links": links,
    }


def _iso(value) -> str:
    timestamp = pd.Timestamp(value)
    return timestamp.date().isoformat()


def _level_frame(connection, series_id: str, as_of: date) -> pd.DataFrame:
    frame = query_series(connection, series_id, as_of)
    if frame.is_empty():
        return pd.DataFrame(columns=["observation_date", "value"])
    pdf = frame.select(["observation_date", "value"]).to_pandas()
    pdf["observation_date"] = pd.to_datetime(pdf["observation_date"])
    pdf = pdf.dropna(subset=["value"]).sort_values("observation_date")
    return pdf.drop_duplicates("observation_date", keep="last")


def _window_change(levels: pd.DataFrame, start: date, end: date) -> float | None:
    part = levels[(levels["observation_date"] >= pd.Timestamp(start)) & (levels["observation_date"] <= pd.Timestamp(end))]
    if len(part) < 2:
        return None
    return float(part["value"].iloc[-1] - part["value"].iloc[0])


def _window_return(levels: pd.DataFrame, start: date, end: date) -> float | None:
    part = levels[(levels["observation_date"] >= pd.Timestamp(start)) & (levels["observation_date"] <= pd.Timestamp(end))]
    if len(part) < 2:
        return None
    returns = simple_returns(part["value"]).dropna()
    if returns.empty:
        return None
    return float((1.0 + returns).prod() - 1.0)


def _titles(connection) -> dict[str, str]:
    try:
        rows = connection.execute("SELECT series_id, title_zh FROM series_meta").fetchall()
    except Exception:
        logger.exception("读取序列中文名失败")
        return {}
    return {row[0]: row[1] for row in rows}


def _variance_regime(changes: pd.Series) -> dict:
    """High-variance spells from a rolling variance threshold.

    A two-state Markov MLE on this Treasury sample did not return inside an
    interactive request, so it is not reported as a smoothed probability.
    """
    weekly = changes.dropna().resample("W-FRI").sum()
    weekly = weekly.replace([np.inf, -np.inf], np.nan).dropna()
    roll = weekly.rolling(12).var()
    if roll.notna().sum() < 40:
        return {"eligible": False, "reason": "周度利率变动不足以划分方差状态", "method": "rolling_variance_median"}
    median = float(roll.median())
    flags = (roll >= median).fillna(False).to_numpy(dtype=bool)
    spells = _binary_spells(list(roll.index), list(flags), gap=4)
    return {
        "eligible": True,
        "reason": None,
        "method": "rolling_variance_median",
        "n_weeks": int(len(weekly)),
        "high_variance_spells": len(spells),
        "latest_in_high_variance": bool(flags[-1]),
        "latest_spell_end": None if not spells else spells[-1]["end"],
        "caveat": "高方差段指 12 周滚动方差不低于样本中位数，相邻间隔不超过 4 周的命中并成一段。这不是 Markov switching 的平滑概率。全样本两状态 MLE 在交互时限内没有返回，因此没有写成状态概率。",
    }


def _binary_spells(index, flags: list[bool], gap: int) -> list[dict]:
    spells = []
    start = None
    last = None
    for position, flag in enumerate(flags):
        if flag and start is None:
            start = position
            last = position
        elif flag:
            last = position
        elif start is not None and last is not None and position - last > gap:
            spells.append({"start": _iso(index[start]), "end": _iso(index[last])})
            start = None
            last = None
    if start is not None and last is not None:
        spells.append({"start": _iso(index[start]), "end": _iso(index[last])})
    return spells


def _similar_episodes(features: pd.DataFrame, as_of: date, horizon: int) -> dict:
    usable = features.dropna()
    if usable.empty:
        return {"eligible": False, "reason": "相似状态缺少同时可见的利率、VIX 和价格", "count": 0, "nearest": []}
    current_rows = usable[usable.index <= pd.Timestamp(as_of)]
    if current_rows.empty:
        return {"eligible": False, "reason": "as_of 之前没有完整特征向量", "count": 0, "nearest": []}
    current = current_rows.iloc[-1]
    current_date = pd.Timestamp(current.name)
    history = usable[usable.index <= current_date - pd.Timedelta(days=int(horizon * 1.6))]
    if len(history) < 8:
        return {"eligible": False, "reason": "可用于对照的历史状态少于 8 个", "count": 0, "nearest": []}
    scale = history.std(ddof=1).replace(0, np.nan)
    centered = (history - history.mean()) / scale
    current_z = (current - history.mean()) / scale
    valid = centered.columns[scale.notna() & current_z.notna()]
    if len(valid) < 3:
        return {"eligible": False, "reason": "可标准化的特征少于 3 个", "count": 0, "nearest": []}
    distance = np.sqrt(((centered[valid] - current_z[valid]) ** 2).mean(axis=1))
    ranked = distance.sort_values()
    nearest = []
    for stamp, value in ranked.head(8).items():
        nearest.append({"date": _iso(stamp), "distance": float(value)})
    close_dates = [pd.Timestamp(item) for item in ranked.index[ranked <= SIMILAR_DISTANCE]]
    episodes = []
    for stamp in close_dates:
        if not episodes or (stamp - episodes[-1]).days > horizon:
            episodes.append(stamp)
    return {
        "eligible": True,
        "reason": None,
        "distance_rule": f"历史均值和标准差只用来自当前窗口之前的状态。距离是标准化特征的均方根，阈值 {SIMILAR_DISTANCE}。相距 {horizon} 天以内的命中并成一次。",
        "current_date": _iso(current_date),
        "current": {column: float(current[column]) for column in valid},
        "count": len(episodes),
        "nearest": nearest,
        "caveat": "距离近只说明这几个描述统计接近，不说明宏观机制相同。",
    }


def structure_payload(connection, as_of: date, window: int = HORIZON) -> dict:
    titles = _titles(connection)
    levels = {series_id: _level_frame(connection, series_id, as_of) for series_id in (*PRICE_IDS, *LEVEL_IDS)}
    dgs10 = levels["DGS10"].set_index("observation_date")["value"].sort_index()
    changes = dgs10.diff(window)
    episodes = distinct_threshold_episodes(changes, window, RATE_MOVE_THRESHOLD)
    for episode in episodes:
        start = date.fromisoformat(episode["start"])
        end = date.fromisoformat(episode["end"])
        episode["dgs2_change"] = _window_change(levels["DGS2"], start, end)
        episode["vix_change"] = _window_change(levels["VIXCLS"], start, end)
        episode["sp500_return"] = _window_return(levels["SP500"], start, end)
        episode["wti_return"] = _window_return(levels["DCOILWTICO"], start, end)
        episode["credit_change"] = _window_change(levels["BAMLC0A0CM"], start, end)

    panel = _feature_panel(levels, window)
    tail = _tails(panel)
    network = correlation_network(
        panel[
            [
                "sp500_return",
                "wti_return",
                "dgs10_change",
                "dgs2_change",
                "dff_change",
                "curve_change",
                "vix_change",
                "credit_change",
            ]
        ]
        .dropna(how="all")
        .tail(window),
        {
            "sp500_return": titles.get("SP500", "标普 500 收益"),
            "wti_return": titles.get("DCOILWTICO", "WTI 收益"),
            "dgs10_change": titles.get("DGS10", "10 年收益率变动"),
            "dgs2_change": titles.get("DGS2", "2 年收益率变动"),
            "dff_change": titles.get("DFF", "联邦基金利率变动"),
            "curve_change": titles.get("T10Y2Y", "利差变动"),
            "vix_change": titles.get("VIXCLS", "VIX 变动"),
            "credit_change": titles.get("BAMLC0A0CM", "信用利差变动"),
        },
    )
    sampled = panel.dropna(subset=["dgs10_change_window", "vix", "sp500_vol", "sp_wti_corr"])[
        ["dgs10_change_window", "vix", "sp500_vol", "sp_wti_corr"]
    ].iloc[::21]
    similar = _similar_episodes(sampled, as_of, window)
    markov = _variance_regime(dgs10.diff())
    crises = _crises(levels, as_of)
    latest_change = None if changes.dropna().empty else float(changes.dropna().iloc[-1])
    return {
        "as_of": as_of.isoformat(),
        "window": window,
        "threshold": RATE_MOVE_THRESHOLD,
        "latest_dgs10_change": latest_change,
        "answer": _answer(as_of, window, episodes, latest_change, similar, markov),
        "episodes": {
            "count": len(episodes),
            "definition": f"{window} 个观测内 10 年期国债收益率绝对变动达到 {RATE_MOVE_THRESHOLD:.2f} 个百分点。相邻命中合并为一次，不把每个交易日计成独立事件。",
            "items": episodes,
        },
        "tails": tail,
        "network": network,
        "similar": similar,
        "markov": markov,
        "crises": crises,
        "caveat": "全部计算只使用 release_date 和 observation_date 都不晚于 as_of 的记录。利率变动不是债券收益。相关和尾部概率不是因果识别。",
    }


def _feature_panel(levels: dict[str, pd.DataFrame], window: int) -> pd.DataFrame:
    def series(frame: pd.DataFrame, name: str) -> pd.Series:
        if frame.empty:
            return pd.Series(dtype=float, name=name)
        return frame.set_index("observation_date")["value"].rename(name).sort_index()

    dgs10 = series(levels["DGS10"], "dgs10")
    frame = pd.DataFrame(
        {
            "dgs10_change_window": dgs10.diff(window),
            "dgs10_change": dgs10.diff(),
            "dgs2_change": series(levels["DGS2"], "dgs2").diff(),
            "dff_change": series(levels["DFF"], "dff").diff(),
            "curve_change": series(levels["T10Y2Y"], "curve").diff(),
            "vix_change": series(levels["VIXCLS"], "vix").diff(),
            "vix": series(levels["VIXCLS"], "vix"),
            "credit_change": series(levels["BAMLC0A0CM"], "credit").diff(),
        }
    )
    sp_ret = simple_returns(series(levels["SP500"], "sp"))
    wti_ret = simple_returns(series(levels["DCOILWTICO"], "wti"))
    frame["sp500_return"] = sp_ret
    frame["wti_return"] = wti_ret
    frame["sp500_vol"] = sp_ret.rolling(window).std(ddof=1) * math.sqrt(252)
    frame["sp_wti_corr"] = sp_ret.rolling(window).corr(wti_ret)
    return frame.sort_index()


def _tails(panel: pd.DataFrame) -> dict:
    equity_oil = lower_tail_dependence(panel["sp500_return"], panel["wti_return"])
    rate_equity = conditional_coexceedance(panel["dgs10_change"], panel["sp500_return"])
    return {
        "sp500_wti_lower": {
            **equity_oil,
            "note": "标普 500 与 WTI 简单收益同时落入各自 5% 下尾的概率，再除以 0.05。1 表示与独立同边际大致相当的下尾共现，更高表示下尾更常一起出现。",
        },
        "fast_rate_and_equity_loss": {
            **rate_equity,
            "note": "在 10 年收益率单日变动处于最高 5% 时，标普 500 简单收益落入自身最低 5% 的频率。这不是利率冲击的因果效应。",
        },
    }


def _crises(levels: dict[str, pd.DataFrame], as_of: date) -> dict:
    windows = []
    for spec in CRISIS_WINDOWS:
        if as_of < spec["start"]:
            continue
        end = spec["end"] if as_of >= spec["end"] else as_of
        windows.append(
            {
                "id": spec["id"],
                "title": spec["title"],
                "start": spec["start"].isoformat(),
                "end": end.isoformat(),
                "partial": end < spec["end"],
                "dgs10_change": _window_change(levels["DGS10"], spec["start"], end),
                "vix_change": _window_change(levels["VIXCLS"], spec["start"], end),
                "sp500_return": _window_return(levels["SP500"], spec["start"], end),
                "wti_return": _window_return(levels["DCOILWTICO"], spec["start"], end),
            }
        )
    return {
        "note": "对照窗口是预先指定的历史区间。as_of 早于窗口开始时，该窗口不出现。as_of 落在窗口内部时只使用到 as_of 为止的数据。",
        "windows": windows,
    }


def _answer(as_of: date, window: int, episodes: list[dict], latest_change: float | None, similar: dict, markov: dict) -> str:
    change_text = "还没有足够的 10 年期收益率变动" if latest_change is None else f"{latest_change:+.2f} 个百分点"
    similar_text = (
        f"与当前特征相近、且彼此不重叠的历史片段有 {similar['count']} 次。"
        if similar.get("eligible")
        else f"相似历史片段这次没有计算：{similar.get('reason')}。"
    )
    markov_text = (
        f"按滚动方差中位数划分，高方差周度变动出现过 {markov['high_variance_spells']} 段，当前{'处于' if markov['latest_in_high_variance'] else '不处于'}高方差段。"
        if markov.get("eligible")
        else f"方差状态这次没有结果：{markov.get('reason')}。"
    )
    return (
        f"截至 {as_of.isoformat()}，只使用当时已发布的数据：{window} 个观测内 10 年期国债收益率绝对变动达到 "
        f"{RATE_MOVE_THRESHOLD:.2f} 个百分点的独立片段有 {len(episodes)} 次。最近这一窗口的收益率变动是 {change_text}。"
        f"{similar_text}{markov_text}这是描述统计，不是因果识别，也不是交易信号。"
    )
