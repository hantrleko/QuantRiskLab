"""Descriptive calculations. Missing series stay missing."""

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


def shrunk_covariance(values: np.ndarray) -> tuple[np.ndarray, float]:
    """Ledoit-Wolf intensity toward a scaled identity, applied to the sample covariance."""
    sample = np.asarray(values, dtype=float)
    sample = sample[np.isfinite(sample).all(axis=1)]
    centered = sample - sample.mean(axis=0)
    rows, cols = centered.shape
    if rows < 2 or cols < 1:
        raise ValueError("收缩协方差样本不足")
    population = (centered.T @ centered) / rows
    target_scale = float(np.trace(population) / cols)
    target = target_scale * np.eye(cols)
    dispersion = float(np.sum((population - target) ** 2))
    squared = centered ** 2
    second = float(np.sum((squared.T @ squared) / rows - population ** 2) / rows)
    second = min(max(second, 0.0), dispersion)
    intensity = 0.0 if dispersion <= 0 else float(np.clip(second / dispersion, 0.0, 1.0))
    unbiased = np.cov(sample, rowvar=False, ddof=1)
    unbiased_scale = float(np.trace(unbiased) / cols)
    covariance = intensity * unbiased_scale * np.eye(cols) + (1.0 - intensity) * unbiased
    return covariance, intensity


def _allocation(paired: pd.DataFrame, weights: np.ndarray, covariance: np.ndarray) -> dict | None:
    variance = float(weights @ covariance @ weights)
    if not np.isfinite(variance) or variance <= 0:
        return None
    shares = weights * (covariance @ weights) / variance
    return {
        "variance": variance,
        "shares": [float(item) for item in shares],
        "names": list(paired.columns),
    }


def euler_allocation(
    connection,
    as_of: date,
    window: int = 252,
    weights: tuple[float, float] = (0.5, 0.5),
) -> dict:
    """Variance shares for SP500 and WTI. Weights must be non-negative and sum to one."""
    vector = np.asarray(weights, dtype=float)
    if vector.shape != (2,) or np.any(vector < 0) or not np.isclose(vector.sum(), 1.0):
        return {"eligible": False, "reason": "权重需要两个非负数，并且加总为 1", "weights": [float(item) for item in vector]}
    sp = simple_returns(_level(connection, "SP500", as_of)).dropna()
    wti = simple_returns(_level(connection, "DCOILWTICO", as_of)).dropna()
    paired = pd.concat([sp.rename("SP500"), wti.rename("DCOILWTICO")], axis=1, sort=True).dropna()
    if len(paired) > window:
        paired = paired.iloc[-window:]
    if len(paired) < 60:
        return {
            "eligible": False,
            "reason": "方差贡献至少需要 60 个同时有效的简单收益",
            "n": int(len(paired)),
            "weights": [float(item) for item in vector],
        }
    sample = paired.cov().to_numpy()
    shrunk, intensity = shrunk_covariance(paired.to_numpy())
    base = _allocation(paired, vector, sample)
    contracted = _allocation(paired, vector, shrunk)
    if base is None or contracted is None:
        return {"eligible": False, "reason": "组合方差不是正数", "n": int(len(paired)), "weights": [float(item) for item in vector]}
    return {
        "eligible": True,
        "reason": None,
        "n": int(len(paired)),
        "sample_start": _iso(paired.index[0]),
        "sample_end": _iso(paired.index[-1]),
        "weights": [float(item) for item in vector],
        "names": base["names"],
        "variance": base["variance"],
        "shares": base["shares"],
        "shrinkage": {
            "intensity": intensity,
            "target": "scaled_identity",
            "variance": contracted["variance"],
            "shares": contracted["shares"],
            "note": "Ledoit-Wolf 强度把样本协方差拉向平均方差乘单位阵。这不是最优组合。",
        },
        "note": "份额来自给定权重的方差分解，加总为 1。这不是交易建议。非正价格不进入简单收益。",
    }


def local_projection(connection, as_of: date) -> dict:
    """Jordà local projections with lagged controls. Reduced form only."""
    label = "约达局部投影，约化式。控制变量是滞后项。10年收益率的一阶差分不是已识别的货币政策冲击。"
    shock = _level(connection, NOMINAL, as_of).diff()
    response = simple_returns(_level(connection, "SP500", as_of))
    pieces = [shock.rename("shock"), response.rename("response"), response.shift(1).rename("own_lag")]
    vix = _level(connection, "VIXCLS", as_of)
    oas = _level(connection, OAS, as_of)
    if not vix.empty:
        pieces.append(vix.shift(1).rename("vix_lag"))
    if not oas.empty:
        pieces.append(oas.diff().shift(1).rename("oas_lag"))
    panel = pd.concat(pieces, axis=1)
    controls = [name for name in ("own_lag", "vix_lag", "oas_lag") if name in panel.columns and int(panel[name].notna().sum()) >= 80]
    usable = panel.dropna(subset=["shock", "response"])
    horizons = []
    if len(usable) < 80:
        return {
            "eligible": False,
            "label": label,
            "reason": "收益率变动与标普简单收益的重叠样本少于 80",
            "controls": controls,
            "horizons": horizons,
        }
    import statsmodels.api as sm

    for horizon in (1, 3, 5, 10, 21, 42, 63):
        future = sum(panel["response"].shift(-step) for step in range(1, horizon + 1))
        columns = ["shock", *controls]
        sample = pd.concat([future.rename("future"), panel[columns]], axis=1).dropna()
        if len(sample) < 80:
            horizons.append({"horizon": horizon, "eligible": False, "reason": "该期限的有效样本少于 80"})
            continue
        fitted = sm.OLS(sample["future"], sm.add_constant(sample[columns])).fit(
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
                "ci95": [beta - 1.96 * se, beta + 1.96 * se],
                "response": f"之后 {horizon} 个交易日的标普简单收益之和",
                "covariance": "Newey-West HAC",
                "controls": controls,
            }
        )
    return {
        "eligible": any(item.get("eligible") for item in horizons),
        "label": label,
        "reason": None,
        "controls": controls,
        "horizons": horizons,
    }


def delta_covar(left: pd.Series, right: pd.Series, tau: float = 0.05) -> dict:
    """Descriptive quantile-regression CoVaR difference. Not a causal estimate."""
    sample = pd.concat([left.rename("left"), right.rename("right")], axis=1, sort=True).dropna()
    if len(sample) < 80:
        return {"eligible": False, "reason": "条件分位数回归至少需要 80 个重叠观测", "n": int(len(sample))}
    import statsmodels.api as sm
    from statsmodels.regression.quantile_regression import QuantReg

    fitted = QuantReg(sample["left"], sm.add_constant(sample["right"])).fit(q=tau, max_iter=1000)
    stress = float(sample["right"].quantile(tau))
    middle = float(sample["right"].median())
    intercept = float(fitted.params["const"])
    slope = float(fitted.params["right"])
    covar_stress = intercept + slope * stress
    covar_median = intercept + slope * middle
    return {
        "eligible": True,
        "tau": tau,
        "n": int(len(sample)),
        "state_quantile": stress,
        "state_median": middle,
        "covar_stress": covar_stress,
        "covar_median": covar_median,
        "delta_covar": covar_stress - covar_median,
        "slope": slope,
        "label": "条件分位数回归的描述性差值，不是已识别的因果 CoVaR。",
    }


def covar_snapshot(connection, as_of: date) -> dict:
    equity = simple_returns(_level(connection, "SP500", as_of))
    oil = simple_returns(_level(connection, "DCOILWTICO", as_of))
    shock = _level(connection, NOMINAL, as_of).diff()
    return {
        "equity_on_oil": delta_covar(equity, oil),
        "equity_on_yield_change": delta_covar(equity, shock),
        "note": "左侧是标普简单收益。状态变量处于自身 5% 分位时的条件分位，减去状态变量处于中位数时的条件分位。",
    }


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
        first = connection.execute("SELECT MIN(release_date) FROM cftc_positions").fetchone()
        first_day = _iso(first[0]) if first and first[0] is not None else None
        reason = "这个 as_of 看不到 CFTC 持仓。"
        if first_day:
            reason = f"这个 as_of 看不到 CFTC 持仓。库内持仓自 {first_day} 起可见。"
        return {"status": "unavailable", "reason": reason, "markets": [], "positions_start": first_day}
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


def revision_wedge(connection, series_id: str, as_of: date) -> dict:
    """Compare the vintage visible on as_of with the latest stored vintage.

    The latest vintage is labeled ex post when its release date is after as_of.
    """
    visible = query_series(connection, series_id, as_of)
    if visible.height == 0:
        return {"series_id": series_id, "status": "unavailable", "reason": "这个 as_of 看不到该序列。"}
    final = connection.execute(
        """
        SELECT observation_date, value AS final_value, release_date AS final_release
        FROM (
            SELECT observation_date, value, release_date,
                   ROW_NUMBER() OVER (
                       PARTITION BY observation_date
                       ORDER BY release_date DESC
                   ) AS rn
            FROM observations
            WHERE series_id = ? AND value IS NOT NULL
        )
        WHERE rn = 1
        """,
        [series_id],
    ).fetchdf()
    if final.empty:
        return {"series_id": series_id, "status": "unavailable", "reason": "没有可用终版。"}
    left = visible.select(["observation_date", "release_date", "value"]).to_pandas()
    left["observation_date"] = pd.to_datetime(left["observation_date"])
    final["observation_date"] = pd.to_datetime(final["observation_date"])
    merged = left.merge(final, on="observation_date", how="inner")
    merged = merged.dropna(subset=["value", "final_value"])
    if merged.empty:
        return {"series_id": series_id, "status": "unavailable", "reason": "可见样本与终版没有重叠。"}
    changed = merged[merged["value"].round(6) != merged["final_value"].round(6)]
    if changed.empty:
        return {
            "series_id": series_id,
            "status": "unchanged",
            "revised_count": 0,
            "note": "在已入库的 vintage 里，该 as_of 可见值与库存最新值没有差异。",
        }
    last = changed.iloc[-1]
    final_release = pd.Timestamp(last["final_release"]).date()
    return {
        "series_id": series_id,
        "status": "revised",
        "revised_count": int(len(changed)),
        "observation_date": _iso(last["observation_date"]),
        "visible_value": float(last["value"]),
        "visible_release": _iso(last["release_date"]),
        "later_value": float(last["final_value"]),
        "later_release": final_release.isoformat(),
        "later_known_at_as_of": final_release <= as_of,
        "note": "later_value 的发布日若晚于 as_of，回放当日看不到这次修订。",
    }


def replay_cross_section(connection, as_of: date, window: int = 63) -> dict:
    from quantrisklab.metrics.structure import (
        LEVEL_IDS,
        PRICE_IDS,
        _feature_panel,
        _level_frame,
        _titles,
        correlation_network,
    )

    levels = {series_id: _level_frame(connection, series_id, as_of) for series_id in (*PRICE_IDS, *LEVEL_IDS)}
    panel = _feature_panel(levels, window)
    titles = _titles(connection)
    columns = [
        "sp500_return",
        "wti_return",
        "dgs10_change",
        "dgs2_change",
        "dff_change",
        "curve_change",
        "vix_change",
        "credit_change",
    ]
    network = correlation_network(
        panel[columns].dropna(how="all").tail(window),
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
    return {
        "as_of": as_of.isoformat(),
        "window": window,
        "network": network,
        "crowding": crowding_snapshot(connection, as_of),
        "revisions": [revision_wedge(connection, "CPIAUCSL", as_of), revision_wedge(connection, "UNRATE", as_of)],
        "note": "网络和持仓只使用 release_date 与 observation_date 都不晚于该日的记录。修订终值若晚于该日，会标明为事后信息。",
    }


def research_payload(
    connection,
    as_of: date,
    window: int = 252,
    weights: tuple[float, float] = (0.5, 0.5),
) -> dict:
    return {
        "as_of": as_of.isoformat(),
        "version": __version__,
        "decomposition": nominal_decomposition(connection, as_of),
        "euler": euler_allocation(connection, as_of, window, weights),
        "local_projection": local_projection(connection, as_of),
        "covar": covar_snapshot(connection, as_of),
        "crowding": crowding_snapshot(connection, as_of),
        "funding": funding_stress(connection, as_of),
        "revisions": [revision_wedge(connection, "CPIAUCSL", as_of), revision_wedge(connection, "UNRATE", as_of)],
        "note": "描述性计算。局部投影是约化式。持仓占比、信用利差和 CoVaR 差值都不是因果证据。",
    }
