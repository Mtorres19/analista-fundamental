import math
import re

import pandas as pd
import pytest

from equity.data import Financials, Market, annual_facts, latest_facts, regression_beta
from equity.dcf import Inputs, default_spread, implied_growth, project, value
from equity.report import render
from macro.assumptions import MarketAssumptions

A = MarketAssumptions(market="US", currency="USD", risk_free_usd=0.042, equity_risk_premium=0.045,
                      country_risk_premium=0.0, expected_inflation=0.024, expected_inflation_usd=0.024,
                      real_growth_long_run=0.018, terminal_growth=0.042, regime="goldilocks", flags=[])
FIN = Financials(ticker="TEST", name="Test Inc", currency="USD", source="test",
                 fiscal_years=["2021-12-31", "2022-12-31", "2023-12-31", "2024-12-31"],
                 items={"revenue": [100e9, 110e9, 121e9, 133.1e9], "ebit": [25e9, 28e9, 31e9, 35e9],
                        "pretax": [26e9, 29e9, 32e9, 36e9], "tax": [4e9, 5e9, 5e9, 6e9], "net_income": [22e9, 24e9, 27e9, 30e9],
                        "da": [5e9, 6e9, 6e9, 7e9], "capex": [10e9, 12e9, 14e9, 18e9], "cfo": [30e9, 33e9, 36e9, 40e9],
                        "interest": [None, None, None, 0.3e9], "sbc": [5e9, 6e9, 6e9, 7e9], "shares": [10e9] * 4,
                        "cash": [100e9] * 4, "debt": [10e9] * 4, "equity": [200e9, 220e9, 240e9, 260e9]})
MKT = Market(price=150.0, shares_out=10e9, beta=1.05, beta_raw=1.07, benchmark="^GSPC", multiples={})


def test_annual_facts_keeps_full_years_from_the_latest_10k():
    units = [
        {"form": "10-K", "start": "2023-01-01", "end": "2023-12-31", "filed": "2024-02-01", "val": 100},
        {"form": "10-K", "start": "2023-01-01", "end": "2023-12-31", "filed": "2025-02-01", "val": 101},  # restated
        {"form": "10-Q", "start": "2024-01-01", "end": "2024-03-31", "filed": "2024-04-25", "val": 30},
        {"form": "10-K", "start": "2024-10-01", "end": "2024-12-31", "filed": "2025-02-01", "val": 40},  # a quarter in a 10-K
        {"form": "10-K", "start": "2024-01-01", "end": "2024-12-31", "filed": "2025-02-01", "val": 120},
    ]
    s = annual_facts(units, flow=True)
    assert list(s.values) == [101, 120]
    assert list(annual_facts([{"form": "10-K", "end": "2024-12-31", "filed": "2025-02-01", "val": 7}], flow=False)) == [7]


def test_trailing_twelve_months_from_10qs():
    units = [
        {"form": "10-K", "start": "2025-01-01", "end": "2025-12-31", "filed": "2026-02-01", "val": 400},
        {"form": "10-Q", "start": "2025-01-01", "end": "2025-09-30", "filed": "2025-10-28", "val": 290},
        {"form": "10-Q", "start": "2026-01-01", "end": "2026-09-30", "filed": "2026-10-28", "val": 330},
        {"form": "10-Q", "start": "2026-07-01", "end": "2026-09-30", "filed": "2026-10-28", "val": 115},  # quarter alone
    ]
    assert latest_facts(units, pd.Timestamp("2025-12-31"), flow=True) == (440.0, "2026-09-30")
    assert latest_facts(units[:1], pd.Timestamp("2025-12-31"), flow=True) is None
    bal = [{"form": "10-K", "end": "2025-12-31", "val": 9}, {"form": "10-Q", "end": "2026-09-30", "filed": "2026-10-28", "val": 7}]
    assert latest_facts(bal, pd.Timestamp("2025-12-31"), flow=False) == (7.0, "2026-09-30")


def test_no_growth_dcf_is_a_perpetuity():
    x = Inputs(revenue=100.0, growth=0.0, terminal_growth=0.0, margin=0.2, tax_effective=0.25, tax_marginal=0.25,
               sales_to_capital=2.0, terminal_roic=0.1, cost_of_equity=0.1, cost_of_debt=0.05, wacc=0.1, beta=1.0,
               cash=0.0, debt=0.0, shares=1.0, price=100.0)
    assert project(x)[3] == pytest.approx(100 * 0.2 * 0.75 / 0.1)


def test_value_verdict_sensitivity_and_implied_growth():
    v = value(FIN, MKT, A, "2026-10-30", peers={"P1": {"pe": 20.0, "ev_ebitda": 15.0}, "P2": {"pe": 30.0, "ev_ebitda": 25.0}})
    x = v.inputs
    assert x.growth == pytest.approx(0.10)
    assert x.cost_of_equity == pytest.approx(0.042 + 1.05 * 0.045)
    assert x.wacc < x.cost_of_equity              # cheap debt pulls the WACC down
    assert v.verdict == ("comprar" if v.upside >= 0.2 else "vender" if v.upside <= -0.15 else "mantener")
    s = v.sensitivity
    assert s["+1 pp"]["+0 pp"] < s["+0 pp"]["+0 pp"] < s["-1 pp"]["+0 pp"]       # higher rates, lower value
    assert s["+0 pp"]["-5 pp"] < s["+0 pp"]["+0 pp"] < s["+0 pp"]["+5 pp"]
    assert s["+0 pp"]["+0 pp"] == pytest.approx(v.value_per_share, abs=0.01)
    assert v.comparables["P/U"] == pytest.approx(25 * 30e9 / 10e9)
    g = implied_growth(x)
    assert g is not None and value(FIN, MKT, A, "2026-10-30", growth=g).value_per_share == pytest.approx(150.0, rel=1e-4)
    assert v.health["roic"] == pytest.approx(35e9 * (1 - 6 / 36) / (260e9 + 10e9 - 100e9))


def test_terminal_growth_above_wacc_is_refused():
    with pytest.raises(ValueError):
        value(FIN, MKT, A, "2026-10-30", wacc=0.03)


def test_default_spread_and_beta():
    assert default_spread(float("inf")) == default_spread(20) < default_spread(2) < default_spread(0.1)
    idx = pd.Series([100 * 1.01 ** i for i in range(40)]) * (1 + 0.02 * pd.Series([math.sin(i) for i in range(40)]))
    assert regression_beta(idx * 2, idx) == pytest.approx(1.0)


def test_ttm_base_and_report_is_spanish_markdown():
    f = FIN.model_copy(update={"ttm": {"revenue": 133.1e9 * 1.1 ** 0.75, "ebit": 40e9, "revenue_ytd_growth": 0.20,
                                       "debt_current": 2e9}, "ttm_end": "2025-09-30"})
    v = value(f, MKT, A, "2026-10-30")
    assert v.ttm_end == "2025-09-30" and v.inputs.growth == pytest.approx((0.10 + 0.20) / 2, abs=1e-3)  # 3.75y at 10%, YTD 20%
    assert v.inputs.debt == 12e9
    assert v.inputs.margin == pytest.approx((31 / 121 + 35 / 133.1 + 40e9 / f.ttm["revenue"]) / 3)
    text = render(value(FIN, MKT, A, "2026-10-30"), A)
    for h in ("# Test Inc (TEST):", "## Tesis", "## Valuación", "## Salud financiera", "## Sensibilidad", "## Riesgos"):
        assert h in text
    assert not re.search(r"\bnan\b", text.lower())
