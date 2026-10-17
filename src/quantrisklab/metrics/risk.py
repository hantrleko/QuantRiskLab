"""Risk summaries for price series. Yields are not converted into asset returns."""

from __future__ import annotations

import logging

import numpy as np
import pandas as pd
import polars as pl

logger = logging.getLogger("quantrisklab.metrics")

MIN_RETURNS = 30


def simple_returns(prices: pd.Series) -> pd.Series:
    """Simple returns. A non-positive price has no percentage return.

    WTI printed a negative Cushing price on 2020-04-20. That observation stays
    in the level series. Returns that would divide by it, or start from it, are
    left missing instead of being turned into a fake percentage.
    """
    values = prices.astype(float)
    returns = values.pct_change()
    invalid = (values <= 0) | (values.shift(1) <= 0)
    return returns.mask(invalid)


def historical_var_es(returns: np.ndarray, alpha: float) -> tuple[float, float]:
    """Empirical return quantile and the mean of returns at or below that quantile.

    Both numbers are in simple-return units. A more negative number is a larger loss.
    Expected shortfall is less than or equal to VaR under this definition.
    """
    if not 0 < alpha < 1:
        raise ValueError("alpha 必须在 (0, 1) 内")
    clean = np.asarray(returns, dtype=float)
    clean = clean[np.isfinite(clean)]
    if clean.size < MIN_RETURNS:
        raise ValueError(f"有效收益不足 {MIN_RETURNS} 个")
    var = float(np.quantile(clean, alpha, method="linear"))
    tail = clean[clean <= var]
    if tail.size == 0:
        raise ValueError("VaR 分位没有对应的尾部样本")
    expected_shortfall = float(tail.mean())
    return var, expected_shortfall


def max_drawdown(prices: np.ndarray) -> float:
    clean = np.asarray(prices, dtype=float)
    clean = clean[np.isfinite(clean)]
    if clean.size < 2:
        raise ValueError("价格样本不足")
    peak = np.maximum.accumulate(clean)
    if np.any(peak <= 0):
        raise ValueError("没有正的历史高点，不能用价格比定义回撤")
    drawdown = clean / peak - 1.0
    return float(drawdown.min())


def realized_volatility(returns: np.ndarray, window: int, periods_per_year: int = 252) -> float:
    clean = np.asarray(returns, dtype=float)
    clean = clean[np.isfinite(clean)]
    if window < 2 or clean.size < window:
        raise ValueError("实现波动率窗口长于有效样本")
    sample = clean[-window:]
    return float(np.std(sample, ddof=1) * np.sqrt(periods_per_year))


def ljung_box_pvalue(returns: np.ndarray, lags: int = 10) -> float | None:
    clean = np.asarray(returns, dtype=float)
    clean = clean[np.isfinite(clean)]
    if clean.size <= lags + 5:
        return None
    try:
        from statsmodels.stats.diagnostic import acorr_ljungbox

        table = acorr_ljungbox(clean, lags=[lags], return_df=True)
    except Exception:
        logger.exception("Ljung-Box 计算失败")
        return None
    return float(table["lb_pvalue"].iloc[0])


def _price_frame(frame: pl.DataFrame) -> pd.DataFrame:
    pdf = frame.select(["observation_date", "value"]).to_pandas()
    pdf["observation_date"] = pd.to_datetime(pdf["observation_date"])
    pdf = pdf.dropna(subset=["value"]).sort_values("observation_date")
    pdf = pdf.drop_duplicates("observation_date", keep="last")
    return pdf


def summarize_price(frame: pl.DataFrame, window: int, alpha: float) -> dict:
    pdf = _price_frame(frame)
    if pdf.empty:
        raise ValueError("没有可用价格")
    returns = simple_returns(pdf["value"]).dropna()
    var, expected_shortfall = historical_var_es(returns.to_numpy(), alpha)
    var_01, es_01 = historical_var_es(returns.to_numpy(), min(alpha, 0.01) if alpha > 0.01 else 0.01)
    if alpha == 0.01:
        var_01, es_01 = var, expected_shortfall
    elif abs(alpha - 0.05) > 1e-9:
        var_01, es_01 = historical_var_es(returns.to_numpy(), 0.01)
    vol = None
    vol_error = None
    try:
        vol = realized_volatility(returns.to_numpy(), window)
    except ValueError as exc:
        vol_error = str(exc)
    return {
        "eligible": True,
        "reason": None,
        "sample_start": pdf["observation_date"].iloc[0].date().isoformat(),
        "sample_end": pdf["observation_date"].iloc[-1].date().isoformat(),
        "n_prices": int(len(pdf)),
        "n_returns": int(returns.shape[0]),
        "return_definition": (
            "相邻可得价格的简单收益。缺失日不填成零收益。不含费用、滑点或股息再投资。"
            + (
                " 样本含非正价格。非正价格及其下一期不计算简单收益，因此不进入 VaR。价格比回撤仍使用该价格，可以低于 -100%。"
                if bool((pdf["value"] <= 0).any())
                else ""
            )
        ),
        "realized_vol_window": window,
        "realized_vol": vol,
        "realized_vol_error": vol_error,
        "vol_annualization": 252,
        "max_drawdown": max_drawdown(pdf["value"].to_numpy()),
        "var_alpha": alpha,
        "var": var,
        "expected_shortfall": expected_shortfall,
        "var_01": var_01,
        "expected_shortfall_01": es_01,
        "sign_convention": "return_quantile",
        "loss_var": -var,
        "loss_expected_shortfall": -expected_shortfall,
        "ljung_box_lags": 10,
        "ljung_box_pvalue": ljung_box_pvalue(returns.to_numpy(), 10),
        "ljung_box_note": "Ljung-Box 检验收益自相关，只是描述统计，不是交易信号。",
    }


def summarize_level(frame: pl.DataFrame) -> dict:
    pdf = _price_frame(frame)
    change_21 = None
    change_252 = None
    if len(pdf) > 21:
        change_21 = float(pdf["value"].iloc[-1] - pdf["value"].iloc[-22])
    if len(pdf) > 252:
        change_252 = float(pdf["value"].iloc[-1] - pdf["value"].iloc[-253])
    return {
        "eligible": False,
        "reason": "该序列不是资产价格。不计算收益、实现波动率、最大回撤、VaR 或 Expected Shortfall。",
        "sample_start": None if pdf.empty else pdf["observation_date"].iloc[0].date().isoformat(),
        "sample_end": None if pdf.empty else pdf["observation_date"].iloc[-1].date().isoformat(),
        "n_observations": int(len(pdf)),
        "latest_level": None if pdf.empty else float(pdf["value"].iloc[-1]),
        "level_change_21": change_21,
        "level_change_252": change_252,
        "level_change_note": "这是原序列水平的差分，单位与原序列相同（通常是百分点），不是资产收益，也不是久期调整后的债券收益。",
    }


def quarterly_realized_vol(frame: pl.DataFrame) -> list[dict]:
    pdf = _price_frame(frame)
    if pdf.empty:
        return []
    pdf = pdf.copy()
    pdf["ret"] = simple_returns(pdf["value"])
    pdf = pdf.dropna(subset=["ret"])
    pdf["quarter"] = pdf["observation_date"].dt.to_period("Q").astype(str)
    rows = []
    for quarter, part in pdf.groupby("quarter", sort=True):
        vol = None
        if len(part) >= 40:
            vol = float(part["ret"].std(ddof=1) * np.sqrt(252))
        rows.append({"quarter": str(quarter), "realized_vol": vol, "n_returns": int(len(part))})
    return rows


def correlation_matrix(series: dict[str, pl.DataFrame], window: int) -> dict:
    frames = []
    for series_id, frame in series.items():
        pdf = _price_frame(frame)
        if pdf.empty:
            continue
        pdf = pdf.copy()
        pdf["ret"] = simple_returns(pdf["value"])
        pdf = pdf.dropna(subset=["ret"])
        frames.append(pdf[["observation_date", "ret"]].rename(columns={"ret": series_id}))
    if len(frames) < 2:
        return {
            "eligible": False,
            "reason": "至少需要两条价格序列才能计算相关矩阵。",
            "labels": [],
            "matrix": [],
            "n_overlaps": 0,
        }
    merged = frames[0]
    for other in frames[1:]:
        merged = merged.merge(other, on="observation_date", how="inner")
    labels = [column for column in merged.columns if column != "observation_date"]
    if merged.shape[0] > window:
        merged = merged.iloc[-window:]
    if merged.shape[0] < max(20, min(window, 40)):
        return {
            "eligible": False,
            "reason": "重叠的收益样本少于窗口要求，不计算相关矩阵。",
            "labels": labels,
            "matrix": [],
            "n_overlaps": int(merged.shape[0]),
            "sample_start": None if merged.empty else merged["observation_date"].iloc[0].date().isoformat(),
            "sample_end": None if merged.empty else merged["observation_date"].iloc[-1].date().isoformat(),
        }
    corr = merged[labels].corr(method="pearson")
    return {
        "eligible": True,
        "reason": None,
        "labels": labels,
        "matrix": corr.to_numpy().tolist(),
        "n_overlaps": int(merged.shape[0]),
        "window": window,
        "method": "pearson_simple_returns",
        "sample_start": merged["observation_date"].iloc[0].date().isoformat(),
        "sample_end": merged["observation_date"].iloc[-1].date().isoformat(),
        "note": "相关由价格简单收益计算。利率序列不进入这个矩阵。",
    }


def change_correlation_matrix(series: dict[str, pl.DataFrame], window: int) -> dict:
    """Pearson correlation of first differences. This is not an asset-return correlation."""
    frames = []
    for series_id, frame in series.items():
        pdf = _price_frame(frame)
        if pdf.empty:
            continue
        pdf = pdf.copy()
        pdf["delta"] = pdf["value"].diff()
        pdf = pdf.dropna(subset=["delta"])
        frames.append(pdf[["observation_date", "delta"]].rename(columns={"delta": series_id}))
    if len(frames) < 2:
        return {
            "eligible": False,
            "reason": "至少需要两条水平序列才能计算差分相关。",
            "labels": [],
            "matrix": [],
            "n_overlaps": 0,
        }
    merged = frames[0]
    for other in frames[1:]:
        merged = merged.merge(other, on="observation_date", how="inner")
    labels = [column for column in merged.columns if column != "observation_date"]
    if merged.shape[0] > window:
        merged = merged.iloc[-window:]
    if merged.shape[0] < max(20, min(window, 40)):
        return {
            "eligible": False,
            "reason": "重叠的差分样本少于窗口要求，不计算相关矩阵。",
            "labels": labels,
            "matrix": [],
            "n_overlaps": int(merged.shape[0]),
        }
    corr = merged[labels].corr(method="pearson")
    return {
        "eligible": True,
        "reason": None,
        "labels": labels,
        "matrix": json_matrix(corr),
        "n_overlaps": int(merged.shape[0]),
        "window": window,
        "method": "pearson_first_difference",
        "sample_start": merged["observation_date"].iloc[0].date().isoformat(),
        "sample_end": merged["observation_date"].iloc[-1].date().isoformat(),
        "note": "这是水平值一阶差分的相关系数。利率差分的单位是百分点，不是资产收益，也不能解释成久期调整后的债券收益。",
    }


def json_matrix(corr: pd.DataFrame) -> list[list[float | None]]:
    rows = []
    for row in corr.to_numpy().tolist():
        cleaned = []
        for value in row:
            number = float(value)
            cleaned.append(None if not np.isfinite(number) else number)
        rows.append(cleaned)
    return rows
