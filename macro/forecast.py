"""Simple, transparent forecasts: several methods side by side, none of them trusted alone.

- drift: the last value plus the average monthly change of the past year ("if the recent trend continues").
- ar1: x_t = a + b x_{t-1} fitted on the last 10 years: the series drifts back to its own long-run mean.
  Comes with a 90% band from the fit's residuals.
- ensemble: the average of drift and ar1.
External views (IMF WEO, market breakevens) are added next to these by the dashboard, not mixed in.
"""

from __future__ import annotations

import numpy as np
import pandas as pd


def forecast(series: pd.Series, horizon: int, freq: str = "MS", fit_years: int = 10) -> pd.DataFrame:
    """Forecast *horizon* periods past the series' last date; columns drift, ar1, lo, hi, ensemble."""
    s = series.dropna()
    s = s[s.index > s.index[-1] - pd.DateOffset(years=fit_years)]
    if len(s) < 8:
        raise ValueError("not enough history to forecast")
    steps = np.arange(1, horizon + 1)
    per_year = {"MS": 12, "QS": 4}[freq]
    recent = s.iloc[-(per_year + 1):]
    drift = s.iloc[-1] + steps * recent.diff().mean()

    x0, x1 = s.values[:-1], s.values[1:]
    var = np.var(x0)
    # OLS slope; a flat series has none. shortcut: a unit-root fit would never revert, so cap it instead of testing.
    b = 0.0 if var < 1e-12 else min(float(np.cov(x0, x1, bias=True)[0, 1] / var), 0.99)
    a = float(np.mean(x1 - b * x0))
    sigma = float(np.std(x1 - (a + b * x0), ddof=2))
    ar, x = [], float(s.iloc[-1])
    for _ in steps:
        x = a + b * x
        ar.append(x)
    ar = np.array(ar)
    spread = 1.645 * sigma * np.sqrt(np.cumsum(b ** (2 * (steps - 1))))

    idx = pd.date_range(s.index[-1], periods=horizon + 1, freq=freq)[1:]
    return pd.DataFrame({"drift": drift, "ar1": ar, "lo": ar - spread, "hi": ar + spread,
                         "ensemble": (drift + ar) / 2}, index=idx)
