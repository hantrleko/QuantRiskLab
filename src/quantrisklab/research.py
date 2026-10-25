"""Descriptive V1.0 calculations. Missing series stay missing."""

from __future__ import annotations

from datetime import date, datetime

import numpy as np
import pandas as pd

from quantrisklab import __version__
from quantrisklab.metrics.risk import simple_returns
from quantrisklab.store.pit import query_series

REAL_YIELD = "DFII10"
BREAKEVEN = "T10YIE"
NOMINAL = "DGS10"
DOLLAR = "DTWEXBGS"
OAS = "BAMLC0A0CM"


def _iso(value) -> str | None:
    if value is None or (isinstance(value, float) and np.isnan(value)):
        return None
    if isinstance(value, datetime):
        return value.date().isoformat()
    if isinstance(value, date):
        return value.isoformat()
    stamp = pd.Timestamp(value)
    if pd.isna(stamp):
        return None
    return stamp.date().isoformat()


def _level(connection, series_id: str, as_of: date) -> pd.Series:
    frame = query_series(connection, series_id, as_of)
    if frame.height == 0:
        return pd.Series(dtype=float)
    indexed = frame.to_pandas().set_index("observation_date")["value"]
    indexed.index = pd.to_datetime(indexed.index)
    return pd.to_numeric(indexed, errors="coerce").sort_index()


def _unavailable(reason: str) -> dict:
    return {"status": "unavailable", "reason": reason, "latest": None, "residual": None}


def nominal_decomposition(connection, as_of: date) -> dict:
    """DGS10 against the real yield and breakeven when both series are stored."""
    nominal = _level(connection, NOMINAL, as_of)
    real = _level(connection, REAL_YIELD, as_of)
    breakeven = _level(connection, BREAKEVEN, as_of)
    dollar = _level(connection, DOLLAR, as_of)
    if real.empty or breakeven.empty:
        missing = [name for name, series in ((REAL_YIELD, real), (BREAKEVEN, breakeven)) if series.empty]
        payload = _unavailable(
            "本地库没有 " + "、".join(missing) + "。名义利率分解不使用替代序列，也不把残差填成 0。"
        )
    else:
        aligned = pd.concat(
            [nominal.rename("nominal"), real.rename("real"), breakeven.rename("breakeven")],
            axis=1,
        ).dropna()
        if aligned.empty:
            payload = _unavailable("三列在同一观测日上没有重叠。")
        else:
            aligned["residual"] = aligned["nominal"] - aligned["real"] - aligned["breakeven"]
            tail = aligned.iloc[-180:]
            latest = tail.iloc[-1]
            payload = {
                "status": "available",
                "reason": None,
                "identity": "residual = DGS10 - DFII10 - T10YIE",
                "latest": {
                    "date": _iso(tail.index[-1]),
                    "nominal": float(latest["nominal"]),
                    "real": float(latest["real"]),
                    "breakeven": float(latest["breakeven"]),
                    "residual": float(latest["residual"]),
                },
                "residual": float(latest["residual"]),
                "points": [
                    {
                        "date": _iso(stamp),
                        "nominal": float(row.nominal),
                        "real": float(row.real),
                        "breakeven": float(row.breakeven),
                        "residual": float(row.residual),
                    }
                    for stamp, row in tail.iterrows()
                ],
                "note": "残差是三条公开收益率的差，不是已识别的期限溢价。",
            }
    if dollar.empty:
        payload["dollar"] = {"status": "unavailable", "reason": "本地库没有 DTWEXBGS。"}
    else:
        change = None if len(dollar.dropna()) < 64 else float(dollar.dropna().iloc[-1] - dollar.dropna().iloc[-64])
        payload["dollar"] = {
            "status": "available",
            "date": _iso(dollar.dropna().index[-1]),
            "level": float(dollar.dropna().iloc[-1]),
            "change_63": change,
            "note": "美元指数按水平差报告，不换算成资产收益。",
        }
    return payload


def euler_allocation(connection, as_of: date, window: int = 252) -> dict:
    """Equal-weight variance shares for the two stored price series."""
    sp = simple_returns(_level(connection, "SP500", as_of)).dropna()
    wti = simple_returns(_level(connection, "DCOILWTICO", as_of)).dropna()
    paired = pd.concat([sp.rename("SP500"), wti.rename("DCOILWTICO")], axis=1).dropna()
    if len(paired) > window:
        paired = paired.iloc[-window:]
    if len(paired) < 60:
        return {
            "eligible": False,
            "reason": "等权方差贡献至少需要 60 个同时有效的简单收益",
            "n": int(len(paired)),
            "weights": [0.5, 0.5],
        }
    cov = paired.cov().to_numpy()
    weights = np.array([0.5, 0.5])
    variance = float(weights @ cov @ weights)
    if not np.isfinite(variance) or variance <= 0:
        return {"eligible": False, "reason": "组合方差不是正数", "n": int(len(paired)), "weights": [0.5, 0.5]}
    component = weights * (cov @ weights)
    shares = component / variance
    return {
        "eligible": True,
        "reason": None,
        "n": int(len(paired)),
        "sample_start": _iso(paired.index[0]),
        "sample_end": _iso(paired.index[-1]),
        "weights": [0.5, 0.5],
        "names": ["SP500", "DCOILWTICO"],
        "variance": variance,
        "shares": [float(shares[0]), float(shares[1])],
        "note": "份额来自等权组合的方差分解，加总为 1。这不是最优权重，也不是交易建议。非正价格不进入简单收益。",
    }


def local_projection(connection, as_of: date) -> dict:
    """Jordà local projections of equity returns on a yield change. Reduced form only."""
    label = "约达局部投影，约化式。10年收益率的一阶差分不是已识别的货币政策冲击。"
    shock = _level(connection, NOMINAL, as_of).diff()
    response = simple_returns(_level(connection, "SP500", as_of))
    panel = pd.concat([shock.rename("shock"), response.rename("response")], axis=1).dropna()
    horizons = []
    if len(panel) < 80:
        return {
            "eligible": False,
            "label": label,
            "reason": "收益率变动与标普简单收益的重叠样本少于 80",
            "horizons": horizons,
        }
    import statsmodels.api as sm

    for horizon in (1, 5, 21):
        future = sum(panel["response"].shift(-step) for step in range(1, horizon + 1))
        sample = pd.concat([panel["shock"].rename("shock"), future.rename("future")], axis=1).dropna()
        if len(sample) < 80:
            horizons.append({"horizon": horizon, "eligible": False, "reason": "该期限的有效样本少于 80"})
            continue
        fitted = sm.OLS(sample["future"], sm.add_constant(sample["shock"])).fit(
            cov_type="HAC",
            cov_kwds={"maxlags": horizon},
        )
        beta = float(fitted.params["shock"])
        se = float(fitted.bse["shock"])
        horizons.append(
            {
                "horizon": horizon,
                "eligible": True,
                "n": int(fitted.nobs),
                "beta": beta,
                "se": se,
                "pvalue": float(fitted.pvalues["shock"]),
                "response": f"之后 {horizon} 个交易日的标普简单收益之和",
                "covariance": "Newey-West HAC",
            }
        )
    return {"eligible": any(item.get("eligible") for item in horizons), "label": label, "reason": None, "horizons": horizons}


def crowding_snapshot(connection, as_of: date) -> dict:
    frame = connection.execute(
        """
        SELECT market_id, title_zh, observation_date, release_date, net_over_oi, open_interest
        FROM cftc_positions
        WHERE release_date <= ? AND observation_date <= ?
        ORDER BY market_id, observation_date
        """,
        [as_of, as_of],
    ).fetchdf()
    if frame.empty:
        return {"status": "unavailable", "reason": "这个 as_of 看不到 CFTC 持仓。", "markets": []}
    markets = []
    for market_id, group in frame.groupby("market_id", sort=False):
        values = pd.to_numeric(group["net_over_oi"], errors="coerce").dropna()
        if values.empty:
            continue
        latest = group.iloc[-1]
        std = float(values.std(ddof=1)) if len(values) >= 8 else None
        zscore = None if std is None or std == 0 or not np.isfinite(std) else float((values.iloc[-1] - values.mean()) / std)
        markets.append(
            {
                "market_id": market_id,
                "title_zh": latest["title_zh"],
                "observation_date": _iso(latest["observation_date"]),
                "release_date": _iso(latest["release_date"]),
                "net_over_oi": None if pd.isna(latest["net_over_oi"]) else float(latest["net_over_oi"]),
                "open_interest": None if pd.isna(latest["open_interest"]) else float(latest["open_interest"]),
                "zscore": zscore,
                "n": int(len(values)),
            }
        )
    return {
        "status": "available" if markets else "unavailable",
        "reason": None if markets else "持仓记录里没有净持仓占未平仓量的比值。",
        "markets": markets,
        "note": "z 分数只和该市场自己的可见历史比较。它不是拥挤交易的因果结论。",
    }


def funding_stress(connection, as_of: date) -> dict:
    oas = _level(connection, OAS, as_of).dropna()
    if oas.empty:
        return {"status": "unavailable", "reason": "本地库没有公司债 OAS。", "latest": None}
    std = float(oas.std(ddof=1)) if len(oas) >= 30 else None
    latest = float(oas.iloc[-1])
    zscore = None if std is None or std == 0 else (latest - float(oas.mean())) / std
    change = None if len(oas) < 22 else latest - float(oas.iloc[-22])
    return {
        "status": "available",
        "latest": {
            "date": _iso(oas.index[-1]),
            "oas": latest,
            "change_21": None if change is None else float(change),
            "zscore": None if zscore is None else float(zscore),
        },
        "note": "这是信用利差的水平、21 个观测的变动和自身历史 z 分数，不是融资利率。",
    }


def research_payload(connection, as_of: date, window: int = 252) -> dict:
    return {
        "as_of": as_of.isoformat(),
        "version": __version__,
        "decomposition": nominal_decomposition(connection, as_of),
        "euler": euler_allocation(connection, as_of, window),
        "local_projection": local_projection(connection, as_of),
        "crowding": crowding_snapshot(connection, as_of),
        "funding": funding_stress(connection, as_of),
        "note": "描述性计算。局部投影是约化式。持仓占比和信用利差都不是因果证据。",
    }
