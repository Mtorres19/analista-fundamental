"""Valuation inputs every DCF of a market shares, derived from the macro snapshots.

US (USD): CAPM on the 10y Treasury and a mature-market equity risk premium.

Mexico (MXN): Damodaran's approach. Build the cost of equity in dollars —
US risk-free + beta x (mature ERP + country risk premium) — then convert it
to pesos with the expected inflation gap. The country risk premium is the
sovereign spread Mexico pays in real terms, scaled up because equities are
more volatile than bonds.
"""

from __future__ import annotations

from pydantic import BaseModel

from macro.snapshot import CountrySnapshot

# Long-run mature-market ERP. Damodaran's implied US ERP has mostly sat in
# 4-6% since 2010; override per run rather than editing here.
DEFAULT_ERP = 0.05
# Equity vol / sovereign bond vol for emerging markets (Damodaran uses ~1.5).
EQUITY_BOND_VOL_RATIO = 1.5


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

    def cost_of_equity(self, beta: float = 1.0) -> float:
        """Cost of equity in local currency for a company with this beta."""
        usd = self.risk_free_usd + beta * (self.equity_risk_premium + self.country_risk_premium)
        return (1 + usd) * (1 + self.expected_inflation) / (1 + self.expected_inflation_usd) - 1


def us_assumptions(us: CountrySnapshot, erp: float = DEFAULT_ERP) -> MarketAssumptions:
    inflation = us.breakeven_10y if us.breakeven_10y is not None else us.inflation_yoy
    return MarketAssumptions(
        market="US", currency="USD",
        risk_free_usd=us.rate_10y,
        equity_risk_premium=erp,
        country_risk_premium=0.0,
        expected_inflation=inflation,
        expected_inflation_usd=inflation,
        real_growth_long_run=us.gdp_trend,
        terminal_growth=_terminal(inflation + us.gdp_trend, us.rate_10y),
        regime=us.regime,
        flags=us.flags,
    )


def mx_assumptions(mx: CountrySnapshot, us: MarketAssumptions, mx_expected_inflation: float,
                   erp: float = DEFAULT_ERP, extra_flags: list[str] | None = None) -> MarketAssumptions:
    """*mx_expected_inflation*: long-run peso inflation (e.g. IMF 5y projection, Banxico survey)."""
    # What Mexico's 10y pays in dollars over Treasuries once the inflation gap is removed.
    mx_10y_in_usd = (1 + mx.rate_10y) * (1 + us.expected_inflation) / (1 + mx_expected_inflation) - 1
    sovereign_spread = max(0.0, mx_10y_in_usd - us.risk_free_usd)
    return MarketAssumptions(
        market="MX", currency="MXN",
        risk_free_usd=us.risk_free_usd,
        equity_risk_premium=erp,
        country_risk_premium=sovereign_spread * EQUITY_BOND_VOL_RATIO,
        expected_inflation=mx_expected_inflation,
        expected_inflation_usd=us.expected_inflation,
        real_growth_long_run=mx.gdp_trend,
        terminal_growth=_terminal(mx_expected_inflation + mx.gdp_trend, mx.rate_10y),
        regime=mx.regime,
        flags=mx.flags + (extra_flags or []),
    )


def _terminal(nominal_growth: float, risk_free_local: float) -> float:
    # A company can't outgrow the economy forever, and growth above the
    # risk-free rate makes a DCF explode (Damodaran's cap).
    return max(0.0, min(nominal_growth, risk_free_local))
