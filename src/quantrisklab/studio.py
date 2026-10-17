"""Interactive research views. Numeric definitions come from the verified V0.3 functions."""

from __future__ import annotations

import json
from datetime import date, datetime, timezone
from pathlib import Path

import pandas as pd

from quantrisklab import __version__
from quantrisklab.metrics.risk import simple_returns
from quantrisklab.metrics.structure import (
    CRISIS_WINDOWS,
    _level_frame,
    _window_change,
    _window_return,
    lower_tail_dependence,
)
from quantrisklab.paths import DATA_DIR
from quantrisklab.pit_clock import snapshot_status

EXPERIMENT_DIR = DATA_DIR / "experiments"
PRICE_IDS = {"SP500", "DCOILWTICO"}
DIFF_IDS = {"DGS2", "DGS10", "DFF", "T10Y2Y", "BAMLC0A0CM"}
LEVEL_IDS = {"VIXCLS", "CPIAUCSL"}
TRANSFORMS = {
    "SP500": "simple_return",
    "DCOILWTICO": "simple_return",
    "DGS2": "difference",
    "DGS10": "difference",
    "DFF": "difference",
    "T10Y2Y": "difference",
    "BAMLC0A0CM": "difference",
    "VIXCLS": "level",
    "CPIAUCSL": "level",
}


def _coverage(frame: pd.DataFrame) -> dict:
    if frame.empty:
        return {"rows": 0, "start": None, "end": None}
    return {
        "rows": int(len(frame)),
        "start": pd.Timestamp(frame["observation_date"].iloc[0]).date().isoformat(),
        "end": pd.Timestamp(frame["observation_date"].iloc[-1]).date().isoformat(),
    }


def _transform(frame: pd.DataFrame, series_id: str, requested: str) -> pd.Series:
    allowed = TRANSFORMS.get(series_id)
    if allowed is None:
        raise ValueError(f"没有为 {series_id} 规定转换类型")
    if requested != allowed:
        raise ValueError(f"{series_id} 只能使用 {allowed}，不能使用 {requested}")
    indexed = frame.set_index("observation_date")["value"]
    if allowed == "simple_return":
        return simple_returns(indexed).dropna()
    if allowed == "difference":
        return indexed.diff().dropna()
    return indexed.dropna()


def replay_track(connection, as_of: date, window: int = 63) -> dict:
    frames = {series_id: _level_frame(connection, series_id, as_of) for series_id in ("DGS10", "VIXCLS", "SP500", "DCOILWTICO")}
    coverage = {series_id: _coverage(frame) for series_id, frame in frames.items()}
    ends = [item["end"] for item in coverage.values() if item["end"]]
    actual_end = max(ends) if ends else None
    if frames["DGS10"].empty:
        return {
            "as_of": as_of.isoformat(),
            "actual_end": actual_end,
            "beyond_coverage": actual_end is None or as_of.isoformat() > actual_end,
            "coverage": coverage,
            "points": [],
            "events": [dict(item) for item in CRISIS_WINDOWS if item["end"] <= as_of],
            "note": "所选日期早于快照中的 10 年期收益率，没有可回放的点。",
        }
    dgs = frames["DGS10"].set_index("observation_date")["value"]
    panel = pd.DataFrame({"dgs10": dgs, "dgs10_change": dgs.diff(window)})
    for series_id, column, kind in (
        ("VIXCLS", "vix", "level"),
        ("SP500", "sp500_return", "return"),
        ("DCOILWTICO", "wti_return", "return"),
    ):
        frame = frames[series_id]
        if frame.empty:
            panel[column] = float("nan")
            continue
        series = frame.set_index("observation_date")["value"]
        panel[column] = series if kind == "level" else simple_returns(series)
    if "sp500_return" in panel and "wti_return" in panel:
        panel["sp_wti_corr"] = pd.to_numeric(panel["sp500_return"], errors="coerce").rolling(window).corr(
            pd.to_numeric(panel["wti_return"], errors="coerce")
        )
    points = []
    for stamp, row in panel.sort_index().iterrows():
        day = pd.Timestamp(stamp).date().isoformat()
        if day > as_of.isoformat():
            continue
        points.append(
            {
                "date": day,
                "dgs10": _num(row.get("dgs10")),
                "dgs10_change": _num(row.get("dgs10_change")),
                "vix": _num(row.get("vix")),
                "sp500_return": _num(row.get("sp500_return")),
                "wti_return": _num(row.get("wti_return")),
                "sp_wti_corr": _num(row.get("sp_wti_corr")),
            }
        )
    events = []
    for item in CRISIS_WINDOWS:
        if item["start"] > as_of:
            continue
        end = item["end"] if item["end"] <= as_of else as_of
        events.append({"id": item["id"], "title": item["title"], "start": item["start"].isoformat(), "end": end.isoformat(), "partial": end < item["end"]})
    return {
        "as_of": as_of.isoformat(),
        "window": window,
        "actual_end": actual_end,
        "beyond_coverage": bool(actual_end and as_of.isoformat() > actual_end),
        "coverage": coverage,
        "points": points,
        "events": events,
        "snapshot": snapshot_status(),
        "note": "回放只包含 release_date 与 observation_date 都不晚于 as_of 的记录。相关是价格简单收益的滚动相关，不是因果传染。",
    }


def explore_pair(connection, as_of: date, left: str, right: str, window: int) -> dict:
    frames = {left: _level_frame(connection, left, as_of), right: _level_frame(connection, right, as_of)}
    try:
        left_values = _transform(frames[left], left, TRANSFORMS[left])
        right_values = _transform(frames[right], right, TRANSFORMS[right])
    except ValueError as exc:
        return {"eligible": False, "reason": str(exc), "as_of": as_of.isoformat()}
    paired = pd.concat([left_values.rename("left"), right_values.rename("right")], axis=1).dropna()
    if len(paired) > window:
        paired = paired.iloc[-window:]
    if len(paired) < 20:
        return {"eligible": False, "reason": "重叠样本少于 20", "n": int(len(paired)), "as_of": as_of.isoformat()}
    corr = float(paired["left"].corr(paired["right"]))
    mechanical = {left, right} <= {"DGS10", "DGS2", "T10Y2Y"} and "T10Y2Y" in {left, right}
    rolling = paired["left"].rolling(min(window, 63)).corr(paired["right"]).dropna()
    scatter = [
        {"date": pd.Timestamp(stamp).date().isoformat(), "left": float(row.left), "right": float(row.right)}
        for stamp, row in paired.iterrows()
    ]
    return {
        "eligible": True,
        "as_of": as_of.isoformat(),
        "left": left,
        "right": right,
        "left_transform": TRANSFORMS[left],
        "right_transform": TRANSFORMS[right],
        "window": window,
        "n": int(len(paired)),
        "sample_start": pd.Timestamp(paired.index[0]).date().isoformat(),
        "sample_end": pd.Timestamp(paired.index[-1]).date().isoformat(),
        "correlation": corr,
        "mechanical": mechanical,
        "interpretation": "会计恒等式 T10Y2Y = DGS10 - DGS2，不是独立风险传导。" if mechanical else "样本相关，不是因果传染。",
        "scatter": scatter[-400:],
        "rolling": [
            {"date": pd.Timestamp(stamp).date().isoformat(), "value": float(value)}
            for stamp, value in rolling.iloc[-400:].items()
        ],
        "method": "Pearson correlation of the allowed transform. Prices use simple returns and skip non-positive prices.",
    }


def tail_laboratory(connection, as_of: date, left: str, right: str, alpha: float) -> dict:
    if left not in PRICE_IDS or right not in PRICE_IDS:
        return {"eligible": False, "reason": "尾部共现只对有简单收益的价格序列估计", "as_of": as_of.isoformat()}
    frames = {left: _level_frame(connection, left, as_of), right: _level_frame(connection, right, as_of)}
    left_returns = simple_returns(frames[left].set_index("observation_date")["value"]) if not frames[left].empty else pd.Series(dtype=float)
    right_returns = simple_returns(frames[right].set_index("observation_date")["value"]) if not frames[right].empty else pd.Series(dtype=float)
    try:
        summary = lower_tail_dependence(left_returns, right_returns, alpha)
    except ValueError as exc:
        return {"eligible": False, "reason": str(exc), "as_of": as_of.isoformat()}
    summary["as_of"] = as_of.isoformat()
    summary["left"] = left
    summary["right"] = right
    summary["label"] = "有限样本阈值共现，不是渐近尾部依赖系数"
    if not summary.get("eligible"):
        summary["events"] = []
        summary["sensitivity"] = []
        return summary
    paired = pd.concat([left_returns.rename("left"), right_returns.rename("right")], axis=1).dropna()
    events = paired[(paired["left"] <= summary["left_quantile"]) & (paired["right"] <= summary["right_quantile"])]
    summary["events"] = [pd.Timestamp(stamp).date().isoformat() for stamp in events.index]
    sensitivity = []
    for probe in (0.01, 0.05, 0.1):
        try:
            item = lower_tail_dependence(left_returns, right_returns, probe)
        except ValueError as exc:
            sensitivity.append({"alpha": probe, "eligible": False, "reason": str(exc)})
            continue
        sensitivity.append(
            {
                "alpha": probe,
                "eligible": item.get("eligible", False),
                "reason": item.get("reason"),
                "n_joint_tail": item.get("n_joint_tail"),
                "coexceedance": item.get("coexceedance"),
                "lift": item.get("lift"),
            }
        )
    summary["sensitivity"] = sensitivity
    return summary


def compare_windows(connection, as_of: date, window_ids: list[str]) -> dict:
    selected = [item for item in CRISIS_WINDOWS if item["id"] in window_ids and item["start"] <= as_of]
    missing_ids = [item for item in window_ids if item not in {row["id"] for row in CRISIS_WINDOWS}]
    rows = []
    for item in selected:
        end = item["end"] if item["end"] <= as_of else as_of
        row = {"id": item["id"], "title": item["title"], "start": item["start"].isoformat(), "end": end.isoformat(), "partial": end < item["end"]}
        for series_id, key, kind in (
            ("DGS10", "dgs10_change", "change"),
            ("VIXCLS", "vix_change", "change"),
            ("SP500", "sp500_return", "return"),
            ("DCOILWTICO", "wti_return", "return"),
        ):
            frame = _level_frame(connection, series_id, as_of)
            if frame.empty or pd.Timestamp(frame["observation_date"].iloc[-1]).date() < item["start"]:
                row[key] = None
                row[f"{key}_status"] = "missing"
                continue
            if kind == "change":
                row[key] = _window_change(frame, item["start"], end)
                row[f"{key}_status"] = "level_change" if row[key] is not None else "missing"
            else:
                result = _window_return(frame, item["start"], end)
                row[key] = result["value"]
                row[f"{key}_status"] = result["status"]
        rows.append(row)
    return {
        "as_of": as_of.isoformat(),
        "windows": rows,
        "unknown_ids": missing_ids,
        "note": "同一套窗口函数。序列在该窗口没有观测时记为 missing，不填入替代值。收益不是因果效应。",
    }


def save_experiment(payload: dict) -> dict:
    EXPERIMENT_DIR.mkdir(parents=True, exist_ok=True)
    stamp = datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%SZ")
    record = {
        "experiment_id": stamp,
        "saved_at_utc": datetime.now(timezone.utc).isoformat(),
        "version": __version__,
        "snapshot": snapshot_status(),
        **payload,
    }
    path = EXPERIMENT_DIR / f"{stamp}.json"
    path.write_text(json.dumps(record, ensure_ascii=False, indent=2), encoding="utf-8")
    return {"experiment_id": stamp, "path": str(Path("data") / "experiments" / path.name)}


def _num(value) -> float | None:
    try:
        number = float(value)
    except (TypeError, ValueError):
        return None
    if pd.isna(number):
        return None
    return number
