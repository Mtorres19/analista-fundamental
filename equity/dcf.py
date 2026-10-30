"""Two-stage FCFF DCF (Damodaran), priced off the macro layer's assumptions, plus comparables and a verdict.

Stage 1 (high_years, default 5): revenue grows at the recent growth (capped), operating margin at its 3-year
average, effective tax rate. Then fade_years (default 5): growth fades linearly to the terminal rate and tax to the
marginal rate. Both are per-company settings in watchlist.toml for firms whose investment buys a longer runway.
Reinvestment = revenue change / sales-to-capital (the company's own last 3 years). Terminal: growth = the macro
layer's terminal growth (capped at the local 10y), reinvestment = g / terminal ROIC.
Discount rate: WACC with the cost of equity from MarketAssumptions.cost_of_equity(beta) and a synthetic-rating cost
of debt. Rates are decimals; amounts in the company's reporting currency.
"""

from __future__ import annotations

import statistics

import pandas as pd

from pydantic import BaseModel

from equity.data import Financials, Market
from macro.assumptions import MarketAssumptions

MARGINAL_TAX = {"USD": 0.25, "MXN": 0.30}     # federal + state in the US (Damodaran's 25%); ISR in Mexico
GROWTH_CAP = (-0.05, 0.25)
SALES_TO_CAPITAL_CAP = (0.5, 5.0)
# shortcut: fixed thresholds on DCF upside; upgrade to a band that widens with the valuation's uncertainty.
BUY, SELL = 0.20, -0.15
# Interest coverage -> default spread, large non-financial firms (Damodaran ratings table, Jan 2026, approximate).
SPREADS = [(8.5, 0.0059), (6.5, 0.0070), (5.5, 0.0092), (4.25, 0.0103), (3.0, 0.0114), (2.5, 0.0130),
           (2.25, 0.0169), (2.0, 0.0193), (1.75, 0.0262), (1.5, 0.0318), (1.25, 0.0519), (0.8, 0.0861),
           (0.65, 0.1176), (0.2, 0.1500), (float("-inf"), 0.2000)]


class Inputs(BaseModel):
    revenue: float
    growth: float               # years 1-5
    terminal_growth: float
    margin: float
    tax_effective: float
    tax_marginal: float
    sales_to_capital: float
    terminal_roic: float
    cost_of_equity: float
    cost_of_debt: float         # pre-tax
    wacc: float
    beta: float
    cash: float
    debt: float
    shares: float
    price: float
    high_years: int = 5         # years at full growth, then...
    fade_years: int = 5         # ...years fading linearly to terminal growth


class Year(BaseModel):
    year: int
    growth: float
    revenue: float
    ebit: float
    tax: float
    reinvestment: float
    fcff: float
    discount: float


class Valuation(BaseModel):
    ticker: str
    name: str
    currency: str
    as_of: str
    inputs: Inputs
    years: list[Year]
    terminal_value: float
    pv_terminal: float
    enterprise_value: float
    equity_value: float
    value_per_share: float
    upside: float
    verdict: str                # comprar / mantener / vender
    comparables: dict[str, float]       # method -> value per share
    peers: dict[str, dict[str, float | None]]
    health: dict[str, float | None]
    implied_growth: float | None   # years 1-5 growth the market price implies
    sensitivity: dict[str, dict[str, float]]   # WACC shift -> growth shift -> value per share
    history: dict[str, list]    # fiscal years, revenue, margin for the report
    ttm_end: str | None = None  # quarter end of the trailing-twelve-month base, when there is one


def value(f: Financials, m: Market, a: MarketAssumptions, as_of: str, peers: dict | None = None,
          **overrides: float) -> Valuation:
    """*overrides*: any Inputs field (growth, margin, sales_to_capital, terminal_roic, ...) to replace the default."""
    x = inputs(f, m, a, **overrides)
    years, tv, pv_tv, ev = project(x)
    equity = ev + x.cash - x.debt
    per_share = equity / x.shares
    upside = per_share / x.price - 1
    peers = peers or {}
    return Valuation(
        ticker=f.ticker, name=f.name, currency=f.currency, as_of=as_of, inputs=x, years=years,
        terminal_value=tv, pv_terminal=pv_tv, enterprise_value=ev, equity_value=equity, value_per_share=per_share,
        upside=upside, verdict="comprar" if upside >= BUY else "vender" if upside <= SELL else "mantener",
        comparables=comparables(f, x, peers), implied_growth=implied_growth(x), peers=peers, health=health(f),
        sensitivity={f"{dw * 100:+.0f} pp": {f"{dg * 100:+.0f} pp": round(_rerun(x, wacc=x.wacc + dw, growth=x.growth + dg), 2)
                                   for dg in (-0.05, 0.0, 0.05)} for dw in (-0.01, 0.0, 0.01)},
        ttm_end=f.ttm_end if "revenue" in f.ttm else None,
        history={"years": f.fiscal_years, "revenue": f.items["revenue"],
                 "margin": [e / r if e is not None and r else None for e, r in zip(f.items["ebit"], f.items["revenue"])]},
    )


def inputs(f: Financials, m: Market, a: MarketAssumptions, **overrides: float) -> Inputs:
    rev = f.items["revenue"]
    n = min(3, len(rev) - 1)
    # Recent momentum counts as much as the 3-year trend: half each when 10-Qs give this year's growth.
    yoy = f.ttm.get("revenue_ytd_growth")
    growth = _clip(revenue_cagr(f) if yoy is None else (revenue_cagr(f) + yoy) / 2, *GROWTH_CAP)
    margins = [e / r for e, r in zip(f.items["ebit"][-3:], rev[-3:]) if e is not None and r]
    if "revenue" in f.ttm and "ebit" in f.ttm:   # the latest twelve months replace the oldest of the three years
        margins = margins[1:] + [f.ttm["ebit"] / f.ttm["revenue"]]
    taxes = [t / p for t, p in zip(f.items["tax"][-3:], f.items["pretax"][-3:]) if t is not None and p and p > 0]
    marginal = MARGINAL_TAX.get(f.currency, 0.25)

    d_rev = rev[-1] - rev[-1 - n]
    net_capex = sum(c - d for c, d in zip(f.items["capex"][-n:], f.items["da"][-n:]) if c is not None and d is not None)
    stc = _clip(d_rev / net_capex, *SALES_TO_CAPITAL_CAP) if net_capex > 0 and d_rev > 0 else 2.0

    debt = sum(f.ttm.get(k, (f.last(k) or [0.0])[0]) for k in ("debt", "debt_current"))
    cash = f.ttm.get("cash", (f.last("cash") or [0.0])[0])
    ebit, interest = (f.last("ebit") or [0.0])[0], (f.last("interest") or [0.0])[0]
    spread = default_spread(ebit / interest if interest else float("inf"))
    # Same conversion as the cost of equity: price it in dollars, then carry it into local currency.
    kd = (1 + a.risk_free_usd + spread + a.country_risk_premium) * (1 + a.expected_inflation) / (1 + a.expected_inflation_usd) - 1
    ke = a.cost_of_equity(m.beta)
    e_mkt = m.price * m.shares_out
    wacc = (e_mkt * ke + debt * kd * (1 - marginal)) / (e_mkt + debt)

    # Terminal ROIC: today's, but no more than 5 pp over the WACC and never under it (competition erodes excess returns).
    roic = health(f)["roic"]
    # Start from the latest twelve months (10-Qs), not a fiscal year that may be ten months old.
    x = dict(revenue=f.ttm.get("revenue", rev[-1]), growth=growth, terminal_growth=a.terminal_growth,
             margin=statistics.mean(margins), tax_effective=_clip(statistics.mean(taxes) if taxes else marginal, 0.0, 0.4),
             tax_marginal=marginal, sales_to_capital=stc, terminal_roic=max(wacc, min(roic or wacc, wacc + 0.05)),
             cost_of_equity=ke, cost_of_debt=kd, wacc=wacc, beta=m.beta, cash=cash, debt=debt, shares=m.shares_out,
             price=m.price)
    x.update(overrides)
    return Inputs(**x)


def project(x: Inputs) -> tuple[list[Year], float, float, float]:
    """Yearly FCFF, terminal value, its present value and the enterprise value."""
    if x.wacc <= x.terminal_growth:
        raise ValueError(f"WACC {x.wacc:.2%} must exceed terminal growth {x.terminal_growth:.2%}")
    years, rev, pv = [], x.revenue, 0.0
    for t in range(1, x.high_years + x.fade_years + 1):
        k = max(0, t - x.high_years) / x.fade_years     # 0 through the high-growth years, 1 at the last year
        g = x.growth + (x.terminal_growth - x.growth) * k
        tax = x.tax_effective + (x.tax_marginal - x.tax_effective) * k
        new = rev * (1 + g)
        ebit = new * x.margin
        reinv = (new - rev) / x.sales_to_capital
        fcff = ebit * (1 - tax) - reinv
        disc = (1 + x.wacc) ** -t
        years.append(Year(year=t, growth=g, revenue=new, ebit=ebit, tax=tax, reinvestment=reinv, fcff=fcff, discount=disc))
        pv += fcff * disc
        rev = new
    nopat = rev * (1 + x.terminal_growth) * x.margin * (1 - x.tax_marginal)
    tv = nopat * (1 - x.terminal_growth / x.terminal_roic) / (x.wacc - x.terminal_growth)
    pv_tv = tv * years[-1].discount
    return years, tv, pv_tv, pv + pv_tv


def comparables(f: Financials, x: Inputs, peers: dict[str, dict[str, float | None]]) -> dict[str, float]:
    """Value per share at the peers' median EV/EBITDA and trailing P/E."""
    med = lambda k: statistics.median(v for p in peers.values() if (v := p.get(k)) is not None) \
        if any(p.get(k) is not None for p in peers.values()) else None
    out = {}
    ebitda = sum(f.last("ebit") + f.last("da"))
    if (m := med("ev_ebitda")) and ebitda > 0:
        out["EV/EBITDA"] = (m * ebitda + x.cash - x.debt) / x.shares
    if (m := med("pe")) and f.last("net_income"):
        out["P/U"] = m * f.last("net_income")[0] / x.shares
    return out


def revenue_cagr(f: Financials) -> float:
    """Revenue growth over about three years, ending at the trailing twelve months when there are any."""
    rev = f.items["revenue"]
    n = min(3, len(rev) - 1)
    if "revenue" in f.ttm and f.ttm_end:
        extra = (pd.Timestamp(f.ttm_end) - pd.Timestamp(f.fiscal_years[-1])).days / 365.25
        return (f.ttm["revenue"] / rev[-1 - n]) ** (1 / (n + extra)) - 1
    return (rev[-1] / rev[-1 - n]) ** (1 / n) - 1


def health(f: Financials) -> dict[str, float | None]:
    """Latest twelve months (fiscal year if no 10-Q since)."""
    last = lambda k: f.ttm[k] if k in f.ttm else (f.last(k) or [None])[0]
    rev, ebit, tax, pretax = last("revenue"), last("ebit"), last("tax"), last("pretax")
    cash, debt, eq, cfo, capex, interest = last("cash") or 0.0, (last("debt") or 0.0) + (last("debt_current") or 0.0), last("equity"), last("cfo"), last("capex"), last("interest")
    t = tax / pretax if tax is not None and pretax else 0.25
    invested = (eq or 0.0) + debt - cash
    return {
        "revenue_cagr_3y": revenue_cagr(f),
        "operating_margin": ebit / rev if ebit is not None and rev else None,
        "fcf_margin": (cfo - capex) / rev if cfo is not None and capex is not None and rev else None,
        "roic": ebit * (1 - t) / invested if ebit is not None and invested > 0 else None,
        "net_cash": cash - debt,
        "interest_coverage": ebit / interest if ebit is not None and interest else None,
        "sbc_to_revenue": last("sbc") / rev if last("sbc") is not None and rev else None,
        "capex_to_revenue": capex / rev if capex is not None and rev else None,
    }


def implied_growth(x: Inputs) -> float | None:
    """Years 1-5 revenue growth at which the DCF equals today's price (bisection), None if outside -20%..60%."""
    lo, hi = -0.20, 0.60
    f = lambda g: _rerun(x, growth=g) - x.price
    if f(lo) > 0 or f(hi) < 0:
        return None
    for _ in range(60):
        mid = (lo + hi) / 2
        lo, hi = (mid, hi) if f(mid) < 0 else (lo, mid)
    return (lo + hi) / 2


def default_spread(coverage: float) -> float:
    return next(s for floor, s in SPREADS if coverage > floor)


def _rerun(x: Inputs, **changes: float) -> float:
    y = x.model_copy(update=changes)
    if y.wacc <= y.terminal_growth:
        return float("nan")
    return (project(y)[3] + y.cash - y.debt) / y.shares


def _clip(v: float, lo: float, hi: float) -> float:
    return max(lo, min(hi, v))
