"""Two-state Markov switching, estimated offline and read back by the API.

The request path never fits the model. A historical as_of uses the latest
stored estimate whose cutoff is on or before that date.
"""

from __future__ import annotations

from datetime import date, datetime
from pathlib import Path

import numpy as np
import pandas as pd

from quantrisklab.paths import DATA_DIR, DB_PATH
from quantrisklab.store.pit import query_series

MODEL_RATE = "dgs10_weekly_diff"
MODEL_VIX = "vix_weekly_level"
MIN_WEEKS = 80
ALIGN_GAP_DAYS = 14

RATE_CAVEAT = (
    "两状态 Markov 只按 10 年期国债收益率周度变动的均值和方差区分状态。"
    "高方差状态是方差较大的那个，不是危机标签，也不是政策体制。"
    "参数只用估计截止日及以前的观测。滤波概率在参数固定后只使用截至该周的观测。"
    "平滑概率还使用同一次估计里更晚的周，所以它不是截面日当时的概率。"
    "估计截止日之后的周没有状态。缺失的交易日不补。"
)
VIX_CAVEAT = (
    "两状态 Markov 按周度 VIX 水平的均值和方差区分状态。"
    "高状态是平均水平较高的那个，不是危机标签。"
    "参数只用估计截止日及以前的观测。滤波概率在参数固定后只使用截至该周的观测。"
    "平滑概率还使用同一次估计里更晚的周。估计截止日之后的周没有状态。"
)


def candidate_ends(last: date) -> list[date]:
    seeds = [date(2008, 9, 12), date(2008, 12, 31), date(2009, 3, 31)]
    year = 2010
    while True:
        end = date(year, 12, 31)
        if end >= last:
            break
        seeds.append(end)
        year += 1
    seeds.append(last)
    unique: list[date] = []
    for item in seeds:
        if item <= last and item not in unique:
            unique.append(item)
    return unique


def _as_date(value) -> date:
    if isinstance(value, datetime):
        return value.date()
    if isinstance(value, date):
        return value
    return pd.Timestamp(value).date()


def _weekly(series: pd.Series, how: str) -> pd.Series:
    clean = series.replace([np.inf, -np.inf], np.nan).dropna().sort_index()
    if clean.empty:
        return clean
    rows: list[tuple[pd.Timestamp, float]] = []
    for _, group in clean.groupby(clean.index.to_period("W-FRI")):
        if how == "sum":
            value = float(group.sum())
        else:
            value = float(group.iloc[-1])
        if np.isfinite(value):
            rows.append((pd.Timestamp(group.index.max()), value))
    if not rows:
        return pd.Series(dtype=float)
    out = pd.Series({stamp: value for stamp, value in rows}).sort_index()
    out.index = pd.DatetimeIndex(out.index)
    return out


def weekly_rate_changes(connection, as_of: date) -> pd.Series:
    frame = query_series(connection, "DGS10", as_of)
    if frame.height == 0:
        return pd.Series(dtype=float)
    values = frame.select(["observation_date", "value"]).to_pandas()
    values["observation_date"] = pd.to_datetime(values["observation_date"])
    level = values.set_index("observation_date")["value"].sort_index()
    return _weekly(level.diff(), "sum")


def weekly_vix(connection, as_of: date) -> pd.Series:
    frame = query_series(connection, "VIXCLS", as_of)
    if frame.height == 0:
        return pd.Series(dtype=float)
    values = frame.select(["observation_date", "value"]).to_pandas()
    values["observation_date"] = pd.to_datetime(values["observation_date"])
    level = values.set_index("observation_date")["value"].sort_index()
    return _weekly(level, "last")


def fit_two_state(values: np.ndarray, search_reps: int = 0) -> dict:
    """Fit a two-state mean-and-variance Markov model. Labels follow the data."""
    from statsmodels.tsa.regime_switching.markov_regression import MarkovRegression

    endog = np.asarray(values, dtype=float)
    if len(endog) < MIN_WEEKS or not np.isfinite(endog).all():
        raise ValueError("周度样本不足，或含有非有限值")
    result = MarkovRegression(endog, k_regimes=2, trend="c", switching_variance=True).fit(
        disp=False,
        maxiter=80,
        em_iter=8,
        search_reps=search_reps,
    )
    params = result.params
    if hasattr(params, "index"):
        lookup = {str(name): float(params[name]) for name in params.index}
    else:
        lookup = {name: float(params[index]) for index, name in enumerate(result.model.param_names)}
    filtered = np.asarray(result.filtered_marginal_probabilities, dtype=float)
    smoothed = np.asarray(result.smoothed_marginal_probabilities, dtype=float)
    if filtered.shape != (len(endog), 2):
        filtered = filtered.T
        smoothed = smoothed.T
    if filtered.shape != (len(endog), 2) or smoothed.shape != filtered.shape:
        raise ValueError("状态概率长度与样本不一致")
    converged = bool(result.mle_retvals.get("converged"))
    return {
        "converged": converged,
        "loglike": float(result.llf),
        "lookup": lookup,
        "filtered": filtered,
        "smoothed": smoothed,
    }


def _label_high(fitted: dict, high_rule: str) -> dict:
    lookup = fitted["lookup"]
    means = [lookup["const[0]"], lookup["const[1]"]]
    variances = [lookup["sigma2[0]"], lookup["sigma2[1]"]]
    if high_rule == "mean" and abs(means[0] - means[1]) > 1e-8:
        high = int(np.argmax(means))
        used = "mean"
    else:
        high = int(np.argmax(variances))
        used = "variance"
    low = 1 - high
    stay = {
        0: lookup["p[0->0]"],
        1: 1.0 - lookup["p[1->0]"],
    }
    finite = all(np.isfinite(means + variances + [stay[0], stay[1]]))
    ordered = variances[high] > variances[low] if used == "variance" else True
    inside = all(0.0 < item < 1.0 for item in stay.values())
    if not fitted["converged"] or not finite or not ordered or not inside:
        fitted["converged"] = False
    fitted.update(
        {
            "high": high,
            "high_rule": used,
            "mean_low": means[low],
            "mean_high": means[high],
            "variance_low": variances[low],
            "variance_high": variances[high],
            "p_stay_low": stay[low],
            "p_stay_high": stay[high],
        }
    )
    return fitted


def ensure_regime_tables(connection) -> None:
    connection.execute(
        """
        CREATE TABLE IF NOT EXISTS regime_fit (
            model_id VARCHAR,
            estimation_end DATE,
            series_id VARCHAR,
            transform VARCHAR,
            high_rule VARCHAR,
            n_obs INTEGER,
            converged BOOLEAN,
            loglike DOUBLE,
            variance_low DOUBLE,
            variance_high DOUBLE,
            mean_low DOUBLE,
            mean_high DOUBLE,
            p_stay_low DOUBLE,
            p_stay_high DOUBLE,
            note VARCHAR
        )
        """
    )
    connection.execute(
        """
        CREATE TABLE IF NOT EXISTS regime_probability (
            model_id VARCHAR,
            estimation_end DATE,
            observation_date DATE,
            filtered_high DOUBLE,
            smoothed_high DOUBLE
        )
        """
    )


def _replace_fit(connection, fit_row: dict, probabilities: pd.DataFrame | None) -> None:
    connection.execute("BEGIN")
    try:
        connection.execute(
            "DELETE FROM regime_probability WHERE model_id = ? AND estimation_end = ?",
            [fit_row["model_id"], fit_row["estimation_end"]],
        )
        connection.execute(
            "DELETE FROM regime_fit WHERE model_id = ? AND estimation_end = ?",
            [fit_row["model_id"], fit_row["estimation_end"]],
        )
        connection.execute(
            """
            INSERT INTO regime_fit VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
            """,
            [
                fit_row["model_id"],
                fit_row["estimation_end"],
                fit_row["series_id"],
                fit_row["transform"],
                fit_row["high_rule"],
                fit_row["n_obs"],
                fit_row["converged"],
                fit_row["loglike"],
                fit_row["variance_low"],
                fit_row["variance_high"],
                fit_row["mean_low"],
                fit_row["mean_high"],
                fit_row["p_stay_low"],
                fit_row["p_stay_high"],
                fit_row["note"],
            ],
        )
        if probabilities is not None and not probabilities.empty:
            connection.register("regime_prob_in", probabilities)
            connection.execute(
                """
                INSERT INTO regime_probability
                SELECT model_id, estimation_end, observation_date, filtered_high, smoothed_high
                FROM regime_prob_in
                """
            )
            connection.unregister("regime_prob_in")
        connection.execute("COMMIT")
    except Exception:
        connection.execute("ROLLBACK")
        raise


def store_regimes(path: Path | None = None, today: date | None = None) -> int:
    """Fit the stored grid and replace those rows. Observations are not deleted."""
    import duckdb

    target = path or DB_PATH
    today = today or date.today()
    connection = duckdb.connect(str(target))
    saved = {MODEL_RATE: 0, MODEL_VIX: 0}
    try:
        ensure_regime_tables(connection)
        specs = (
            (MODEL_RATE, "DGS10", "weekly_sum_of_daily_difference", "variance", weekly_rate_changes, RATE_CAVEAT),
            (MODEL_VIX, "VIXCLS", "weekly_last_level", "mean", weekly_vix, VIX_CAVEAT),
        )
        for model_id, series_id, transform, high_rule, builder, caveat in specs:
            series = builder(connection, today)
            if series.empty:
                print(f"{model_id} 没有周度样本", flush=True)
                continue
            last = _as_date(series.index.max())
            for end in candidate_ends(last):
                sample = series[series.index <= pd.Timestamp(end)]
                if len(sample) < MIN_WEEKS:
                    continue
                try:
                    fitted = _label_high(fit_two_state(sample.to_numpy(dtype=float)), high_rule)
                    if not fitted["converged"]:
                        fitted = _label_high(fit_two_state(sample.to_numpy(dtype=float), search_reps=2), high_rule)
                except Exception as exc:
                    print(f"{model_id} {end.isoformat()} 未完成 {type(exc).__name__}", flush=True)
                    _replace_fit(
                        connection,
                        _fit_row(model_id, series_id, transform, high_rule, end, len(sample), False, None, caveat),
                        None,
                    )
                    continue
                probabilities = None
                if fitted["converged"]:
                    high = fitted["high"]
                    probabilities = pd.DataFrame(
                        {
                            "model_id": model_id,
                            "estimation_end": end,
                            "observation_date": [_as_date(stamp) for stamp in sample.index],
                            "filtered_high": np.clip(np.round(fitted["filtered"][:, high], 6), 0.0, 1.0),
                            "smoothed_high": np.clip(np.round(fitted["smoothed"][:, high], 6), 0.0, 1.0),
                        }
                    )
                    saved[model_id] += 1
                _replace_fit(
                    connection,
                    _fit_row(
                        model_id,
                        series_id,
                        transform,
                        fitted["high_rule"],
                        end,
                        len(sample),
                        fitted["converged"],
                        fitted,
                        caveat,
                    ),
                    probabilities,
                )
                print(
                    f"{model_id} {end.isoformat()} n={len(sample)} converged={fitted['converged']}",
                    flush=True,
                )
        export_regime_csv(connection)
    finally:
        connection.close()
    if saved[MODEL_RATE] == 0 or saved[MODEL_VIX] == 0:
        return 1
    return 0


def _fit_row(model_id, series_id, transform, high_rule, end, n_obs, converged, fitted, caveat) -> dict:
    def pick(name):
        if not fitted or not converged:
            return None
        value = fitted.get(name)
        return None if value is None else float(value)

    return {
        "model_id": model_id,
        "estimation_end": end,
        "series_id": series_id,
        "transform": transform,
        "high_rule": high_rule,
        "n_obs": int(n_obs),
        "converged": bool(converged),
        "loglike": pick("loglike"),
        "variance_low": pick("variance_low"),
        "variance_high": pick("variance_high"),
        "mean_low": pick("mean_low"),
        "mean_high": pick("mean_high"),
        "p_stay_low": pick("p_stay_low"),
        "p_stay_high": pick("p_stay_high"),
        "note": caveat,
    }


def export_regime_csv(connection, destination: Path | None = None) -> Path:
    destination = destination or (DATA_DIR / "regime_states.csv")
    frame = connection.execute(
        """
        SELECT model_id, estimation_end, observation_date, filtered_high, smoothed_high,
               CASE WHEN filtered_high >= 0.5 THEN 1 ELSE 0 END AS high_state
        FROM regime_probability
        ORDER BY model_id, estimation_end, observation_date
        """
    ).fetchdf()
    destination.parent.mkdir(parents=True, exist_ok=True)
    frame.to_csv(destination, index=False)
    return destination


def _tables_ready(connection) -> bool:
    try:
        connection.execute("SELECT 1 FROM regime_fit LIMIT 1").fetchone()
    except Exception:
        return False
    return True


def regime_model(connection, model_id: str, as_of: date, with_points: bool = False) -> dict:
    title = "10年期国债收益率" if model_id == MODEL_RATE else "VIX"
    caveat = RATE_CAVEAT if model_id == MODEL_RATE else VIX_CAVEAT
    base = {
        "eligible": False,
        "method": "markov_switching_two_state",
        "model_id": model_id,
        "title": title,
        "reason": "还没有离线两状态估计。",
        "caveat": caveat,
        "points": [] if with_points else None,
    }
    if not _tables_ready(connection):
        return base
    row = connection.execute(
        """
        SELECT estimation_end, series_id, high_rule, n_obs, mean_low, mean_high,
               variance_low, variance_high, p_stay_low, p_stay_high, note
        FROM regime_fit
        WHERE model_id = ? AND converged AND estimation_end <= ?
        ORDER BY estimation_end DESC
        LIMIT 1
        """,
        [model_id, as_of],
    ).fetchone()
    if row is None:
        first = connection.execute(
            "SELECT MIN(estimation_end) FROM regime_fit WHERE model_id = ? AND converged",
            [model_id],
        ).fetchone()
        if first and first[0] is not None:
            base["reason"] = f"离线两状态估计从 {_as_date(first[0]).isoformat()} 起才有，这个截面日更早。"
        return base
    estimation_end = _as_date(row[0])
    points = []
    latest_filtered = None
    latest_date = None
    loaded = connection.execute(
        """
        SELECT observation_date, filtered_high, smoothed_high
        FROM regime_probability
        WHERE model_id = ? AND estimation_end = ? AND observation_date <= ?
        ORDER BY observation_date
        """,
        [model_id, estimation_end, as_of],
    ).fetchall()
    for obs, filtered_high, smoothed_high in loaded:
        obs_date = _as_date(obs)
        if obs_date > estimation_end or obs_date > as_of:
            continue
        latest_date = obs_date.isoformat()
        latest_filtered = float(filtered_high)
        if with_points:
            points.append(
                {
                    "observation_date": latest_date,
                    "filtered_high": float(filtered_high),
                    "smoothed_high": float(smoothed_high),
                }
            )
    return {
        "eligible": True,
        "reason": None,
        "method": "markov_switching_two_state",
        "model_id": model_id,
        "title": title,
        "series_id": row[1],
        "high_rule": row[2],
        "estimation_end": estimation_end.isoformat(),
        "n_weeks": int(row[3]),
        "mean_low": None if row[4] is None else float(row[4]),
        "mean_high": None if row[5] is None else float(row[5]),
        "variance_low": None if row[6] is None else float(row[6]),
        "variance_high": None if row[7] is None else float(row[7]),
        "p_stay_low": None if row[8] is None else float(row[8]),
        "p_stay_high": None if row[9] is None else float(row[9]),
        "latest_date": latest_date,
        "latest_filtered_high": latest_filtered,
        "latest_in_high_variance": bool(latest_filtered is not None and latest_filtered >= 0.5),
        "caveat": row[10] or caveat,
        "points": points if with_points else None,
    }


def regime_summary(connection, as_of: date) -> dict:
    summary = regime_model(connection, MODEL_RATE, as_of, with_points=False)
    summary.pop("points", None)
    return summary


def regime_payload(connection, as_of: date) -> dict:
    return {
        "as_of": as_of.isoformat(),
        "models": [
            regime_model(connection, MODEL_RATE, as_of, with_points=True),
            regime_model(connection, MODEL_VIX, as_of, with_points=True),
        ],
        "note": (
            "分段检验使用 filtered_high，并选择 estimation_end 不晚于检验日期的那一次估计。"
            "smoothed_high 用到了该次估计内部更晚的周。high_state 为 1 表示该模型的高状态。"
            "状态编号不是危机或政策体制。"
        ),
    }


def align_states(panel: pd.DataFrame, dates: pd.Series, model_id: str, as_of: date) -> pd.DataFrame:
    """Attach the filtered state known on as_of. Gaps longer than 14 days stay empty."""
    dates_frame = pd.DataFrame({"date": pd.to_datetime(dates)}).sort_values("date")
    empty = dates_frame.copy()
    empty["filtered_high"] = np.nan
    empty["high_state"] = np.nan
    empty["estimation_end"] = pd.NaT
    if panel.empty:
        return empty
    chosen = panel[(panel["model_id"] == model_id) & (pd.to_datetime(panel["estimation_end"]) <= pd.Timestamp(as_of))]
    if chosen.empty:
        return empty
    end = pd.to_datetime(chosen["estimation_end"]).max()
    sample = chosen[pd.to_datetime(chosen["estimation_end"]) == end].copy()
    sample["observation_date"] = pd.to_datetime(sample["observation_date"])
    sample = sample[sample["observation_date"] <= pd.Timestamp(as_of)].sort_values("observation_date")
    if sample.empty:
        return empty
    merged = pd.merge_asof(
        dates_frame,
        sample[["observation_date", "filtered_high"]],
        left_on="date",
        right_on="observation_date",
        direction="backward",
        tolerance=pd.Timedelta(days=ALIGN_GAP_DAYS),
    )
    merged["estimation_end"] = end
    merged.loc[merged["filtered_high"].isna(), "estimation_end"] = pd.NaT
    merged["high_state"] = np.where(merged["filtered_high"].isna(), np.nan, (merged["filtered_high"] >= 0.5).astype(float))
    return merged
