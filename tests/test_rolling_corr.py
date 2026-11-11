"""A missing return drops out of the pair count. It does not erase the window."""

import numpy as np
import pandas as pd

from quantrisklab.metrics.risk import rolling_corr, simple_returns


def test_negative_price_does_not_blank_the_rest_of_the_window():
    index = pd.bdate_range("2020-01-02", periods=120)
    equity = pd.Series(100 + np.arange(len(index)) * 0.2, index=index)
    oil = pd.Series(40 + np.sin(np.arange(len(index)) / 3.0), index=index)
    oil.iloc[40] = -36.98
    oil_returns = simple_returns(oil)
    assert pd.isna(oil_returns.iloc[40])
    assert pd.isna(oil_returns.iloc[41])

    correlated = rolling_corr(simple_returns(equity), oil_returns, 63)
    paired = pd.concat(
        [simple_returns(equity).rename("left"), oil_returns.rename("right")],
        axis=1,
        sort=True,
    )
    blanked = paired["left"].rolling(63).corr(paired["right"])
    # Index 80 still sits inside the 63-row window that touches the negative print.
    assert pd.isna(blanked.iloc[80])
    assert np.isfinite(correlated.iloc[80])
    both = np.isfinite(correlated.to_numpy()) & np.isfinite(blanked.to_numpy())
    assert both.any()
    assert np.allclose(correlated.to_numpy()[both], blanked.to_numpy()[both])

    clean_oil = pd.Series(40 + np.arange(len(index)) * 0.05, index=index)
    clean = rolling_corr(simple_returns(equity), simple_returns(clean_oil), 63)
    assert np.isfinite(clean.iloc[-1])
