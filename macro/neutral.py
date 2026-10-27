"""Neutral real rate (r*): our own estimate per country, the external benchmarks, and the policy stance it implies.

Ours is deliberately simple and transparent: the average of (a) trend real growth, the 10y CAGR of real GDP the
snapshot already computes, and (b) the 10y average of the ex-ante real policy rate (policy minus expected
inflation: the Cleveland Fed 1y expectation for the US; realized inflation for Mexico, which has no free daily
expectations series). Nominal neutral = r* + the central bank's inflation target. Rates in percent.

shortcut: (b) is a plain rolling mean, not a filter; switch to an HP / Kalman estimate if r* drives decisions.
"""

from __future__ import annotations

import pandas as pd
from pydantic import BaseModel

from macro import sources
from macro.report import MacroReport
from macro.snapshot import _monthly

TARGET = {"US": 2.0, "MX": 3.0}
# Banxico's published range for the neutral real rate (Informe Trimestral abril-junio 2019, Recuadro 4).
BANXICO_RANGE = (1.8, 3.4)
HALF_LIFE_MONTHS = 12   # convergence-to-neutral path: the gap halves every year


class Neutral(BaseModel):
    country: str
    rstar: float                   # ours, real %
    trend_growth: float
    avg_real_rate: float           # 10y mean ex-ante real policy rate
    external: float | None         # NY Fed HLW (US) or the middle of Banxico's range (MX)
    external_label: str
    target: float
    policy: float
    real_policy: float             # today's ex-ante real policy rate
    history: list[list]            # ex-ante real policy rate, monthly, [ms, %]

    @property
    def nominal(self) -> float:
        return self.rstar + self.target

    @property
    def gap(self) -> float:
        """Policy minus nominal neutral: > 0 restrictive, < 0 loose."""
        return self.policy - self.nominal

    @property
    def stance(self) -> str:
        return "restrictiva" if self.gap > 0.75 else "laxa" if self.gap < -0.75 else "cerca de neutral"

    def path(self, index: pd.DatetimeIndex) -> pd.Series:
        """Policy rate converging to nominal neutral, one value per forecast date."""
        months = pd.Series(range(1, len(index) + 1), index=index)
        return self.nominal + self.gap * 0.5 ** (months / HALF_LIFE_MONTHS)


def build_neutral(r: MacroReport, fetch: sources.Fetch = sources.fetch) -> dict[str, Neutral]:
    as_of = r.as_of
    us, mx = sources.load("US", as_of, fetch), sources.load("MX", as_of, fetch)
    exp_us = _monthly(sources.load("US_ECON", as_of, fetch)["inflation_exp_1y"])
    hlw = sources.load("EXTERNAL", as_of, fetch)["hlw_rstar_us"]
    infl_mx = (_monthly(mx["cpi"]) / _monthly(mx["cpi"]).shift(freq=pd.DateOffset(years=1)) - 1).dropna() * 100
    out = {}
    for c, s, expected, snap, ext, label in (
            ("US", us, exp_us, r.us, float(hlw.iloc[-1]), f"NY Fed HLW {hlw.index[-1].year}T{(hlw.index[-1].month - 1) // 3 + 1}"),
            ("MX", mx, infl_mx, r.mx, sum(BANXICO_RANGE) / 2, f"Banxico {BANXICO_RANGE[0]:.1f}–{BANXICO_RANGE[1]:.1f}% (2019)")):
        out[c] = neutral_from(c, _monthly(s["policy_rate"]), expected, snap.gdp_trend * 100, ext, label)
    return out


def neutral_from(country: str, policy: pd.Series, expected_inflation: pd.Series, trend_growth: float,
                 external: float | None, external_label: str) -> Neutral:
    real = (policy - expected_inflation.reindex(policy.index)).dropna()
    window = real[real.index > real.index[-1] - pd.DateOffset(years=10)]
    if len(window) < 24:
        raise sources.DataError(f"{country} r*: fewer than 24 months of ex-ante real policy rate")
    avg = float(window.mean())
    return Neutral(country=country, rstar=(trend_growth + avg) / 2, trend_growth=trend_growth, avg_real_rate=avg,
                   external=external, external_label=external_label, target=TARGET[country],
                   policy=float(policy.iloc[-1]), real_policy=float(real.iloc[-1]),
                   history=[[int(t.timestamp() * 1000), round(float(v), 3)] for t, v in window.items()])
