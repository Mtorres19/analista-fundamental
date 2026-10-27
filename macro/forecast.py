"""Simple, transparent forecasts: several methods side by side, none of them trusted alone.

- drift: the last value plus the average change of the past year, damped (phi 0.8 per period) so a price
  shock is not projected forever: at most ~4 periods of the recent pace get added.
- ar1: x_t = a + b x_{t-1} fitted on the last 10 years: the series drifts back to its own long-run mean.
  Its residuals set a 90% band, placed around both models, robust to one shock (2020) without collapsing on
  series that move in steps.
- ensemble: the average of drift and ar1.
External views (IMF WEO, market breakevens) are added next to these by the dashboard, not mixed in.
"""

from __future__ import annotations

import numpy as np
import pandas as pd

DAMPING = 0.8


def forecast(series: pd.Series, horizon: int, freq: str = "MS", fit_years: int = 10) -> pd.DataFrame:
    """Forecast *horizon* periods past the series' last date; columns drift, ar1, lo, hi, ensemble."""
    s = series.dropna()
    s = s[s.index > s.index[-1] - pd.DateOffset(years=fit_years)]
    if len(s) < 8:
        raise ValueError("not enough history to forecast")
    steps = np.arange(1, horizon + 1)
    per_year = {"MS": 12, "QS": 4}[freq]
    recent = s.iloc[-(per_year + 1):]
    drift = s.iloc[-1] + np.cumsum(DAMPING ** steps) * recent.diff().mean()

    x0, x1 = s.values[:-1], s.values[1:]
    var = np.var(x0)
    # OLS slope; a flat series has none. shortcut: a unit-root fit would never revert, so cap it instead of testing.
    b = 0.0 if var < 1e-12 else min(float(np.cov(x0, x1, bias=True)[0, 1] / var), 0.99)
    a = float(np.mean(x1 - b * x0))
    resid = x1 - (a + b * x0)
    # Robust to one shock (2020), but series that move in steps (policy rates) have a near-zero MAD: floor it
    # with the std of the residuals minus their largest 10%, which drops the COVID months/quarters.
    trimmed = resid[np.abs(resid) <= np.quantile(np.abs(resid), 0.9)]
    sigma = max(1.4826 * float(np.median(np.abs(resid - np.median(resid)))), float(np.std(trimmed)))
    ar, x = [], float(s.iloc[-1])
    for _ in steps:
        x = a + b * x
        ar.append(x)
    ar = np.array(ar)
    spread = 1.645 * sigma * np.sqrt(np.cumsum(b ** (2 * (steps - 1))))

    idx = pd.date_range(s.index[-1], periods=horizon + 1, freq=freq)[1:]
    # The band spans both models, so their average always falls inside it.
    return pd.DataFrame({"drift": drift, "ar1": ar, "lo": np.minimum(ar, drift) - spread,
                         "hi": np.maximum(ar, drift) + spread,
                         "ensemble": (drift + ar) / 2}, index=idx)
