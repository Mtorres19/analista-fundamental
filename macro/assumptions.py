"""Valuation inputs every DCF of a market shares, derived from the macro snapshots.

US (USD): CAPM on the 10y Treasury and a mature-market equity risk premium.

Mexico (MXN): Damodaran's approach. Build the cost of equity in dollars —
US risk-free + beta x (mature ERP + country risk premium) — then convert it
to pesos with the expected inflation gap, once. The country risk premium is a
default spread (no free sovereign CDS: the ICE BofA EM corporate OAS stands in)
times how much more volatile Mexican equities are than Mexican bonds. A real
bond-yield spread would also carry the peso's risk premium, which the inflation
conversion already prices, so it would count it twice.
"""

from __future__ import annotations

import numpy as np
import pandas as pd
from pydantic import BaseModel

from macro.snapshot import CountrySnapshot

# Fallback mature-market ERP when no implied one is given (Damodaran's implied US ERP has sat in 4-6% since 2010).
DEFAULT_ERP = 0.05
# Damodaran's global equity/bond volatility ratio, used when the local one cannot be measured.
EQUITY_BOND_VOL_RATIO = 1.5
BOND_DURATION_10Y = 6.5   # modified duration of a ~10y Bono M near par at 8-10%; turns yield changes into price returns


class MarketAssumptions(BaseModel):
    market: str
    currency: str
    risk_free_usd: float
    equity_risk_premium: float
    country_risk_premium: float
    expected_inflation: float       # local currency, long run
    expected_inflation_usd: float
    real_growth_long_run: float
    terminal_growth: float          # nominal, local currency, capped at the local 10y
    regime: str
    flags: list[str]
    real_growth_ours: float = 0.0   # our trend (10y, outside 2020-21), shown next to the consensus long run used
    default_spread: float = 0.0     # Mexico only: the credit spread the CRP starts from
    equity_bond_vol: float = 0.0    # Mexico only: equity / bond volatility multiplier

    def cost_of_equity(self, beta: float = 1.0) -> float:
        """Cost of equity in local currency for a company with this beta."""
        usd = self.risk_free_usd + beta * (self.equity_risk_premium + self.country_risk_premium)
        return (1 + usd) * (1 + self.expected_inflation) / (1 + self.expected_inflation_usd) - 1


def equity_bond_vol_ratio(equity: pd.Series, yield_10y: pd.Series, years: int = 5) -> float:
    """sigma(monthly equity log returns) / sigma(monthly bond price returns ~ -duration x yield change), both local
    currency, over the last *years*. Falls back to the global 1.5 with under 3 years of overlap."""
    m = lambda s: s.dropna().resample("MS").last().dropna()
    eq = np.log(m(equity)).diff().dropna()
    bd = (-BOND_DURATION_10Y * m(yield_10y).diff() / 100).dropna()
    start = min(eq.index[-1], bd.index[-1]) - pd.DateOffset(years=years)
    eq, bd = eq[eq.index > start], bd[bd.index > start]
    if min(len(eq), len(bd)) < 36 or bd.std() == 0:
        return EQUITY_BOND_VOL_RATIO
    return float(eq.std() / bd.std())


def us_assumptions(us: CountrySnapshot, erp: float = DEFAULT_ERP, long_run_growth: float | None = None) -> MarketAssumptions:
    """*long_run_growth*: consensus real growth for terminal value (Fed SEP longer run); our trend if not given."""
    inflation = us.breakeven_10y if us.breakeven_10y is not None else us.inflation_yoy
    growth = us.gdp_trend_ex_covid if long_run_growth is None else long_run_growth
    return MarketAssumptions(
        market="US", currency="USD",
        risk_free_usd=us.rate_10y,
        equity_risk_premium=erp,
        country_risk_premium=0.0,
        expected_inflation=inflation,
        expected_inflation_usd=inflation,
        real_growth_long_run=growth,
        terminal_growth=_terminal(inflation + growth, us.rate_10y),
        real_growth_ours=us.gdp_trend_ex_covid,
        regime=us.regime,
        flags=us.flags,
    )


def mx_assumptions(mx: CountrySnapshot, us: MarketAssumptions, mx_expected_inflation: float,
                   mx_long_run_inflation: float, default_spread: float, vol_ratio: float,
                   erp: float = DEFAULT_ERP, extra_flags: list[str] | None = None,
                   long_run_growth: float | None = None) -> MarketAssumptions:
    """*mx_expected_inflation*: peso inflation over the next years (Banxico survey, 1-4y), used to convert the cost
    of equity; *mx_long_run_inflation*: the survey's 5-8y view, used for terminal growth; *long_run_growth*: the
    survey's 10y real growth (our trend if not given). Decimals."""
    growth = mx.gdp_trend_ex_covid if long_run_growth is None else long_run_growth
    return MarketAssumptions(
        market="MX", currency="MXN",
        risk_free_usd=us.risk_free_usd,
        equity_risk_premium=erp,
        country_risk_premium=default_spread * vol_ratio,
        expected_inflation=mx_expected_inflation,
        expected_inflation_usd=us.expected_inflation,
        real_growth_long_run=growth,
        terminal_growth=_terminal(mx_long_run_inflation + growth, mx.rate_10y),
        real_growth_ours=mx.gdp_trend_ex_covid,
        regime=mx.regime,
        flags=mx.flags + (extra_flags or []),
        default_spread=default_spread, equity_bond_vol=vol_ratio,
    )


def _terminal(nominal_growth: float, risk_free_local: float) -> float:
    # A company can't outgrow the economy forever, and growth above the
    # risk-free rate makes a DCF explode (Damodaran's cap).
    return max(0.0, min(nominal_growth, risk_free_local))
