"""Company data: annual financials, price history and peer multiples.

US companies: SEC EDGAR XBRL company facts (official, free; the SEC asks for a User-Agent with contact).
Mexican companies: Yahoo Finance statements (BMV's legal notice forbids extracting its filings).
Amounts in the company's reporting currency, units as reported (USD, not millions).
"""

from __future__ import annotations

import os
import warnings

import pandas as pd
import requests
from pydantic import BaseModel

from macro.sources import DataError

SEC_TICKERS = "https://www.sec.gov/files/company_tickers.json"
SEC_FACTS = "https://data.sec.gov/api/xbrl/companyfacts/CIK{cik:010d}.json"
# The SEC rejects requests without a contact; SEC_USER_AGENT overrides it.
USER_AGENT = os.environ.get("SEC_USER_AGENT", "analista-fundamental (github.com/Mtorres19/analista-fundamental)")

# Line item -> XBRL tags tried in order; the first with annual data wins. Flows sum a fiscal year, stocks are year-end.
FLOWS = {
    "revenue": ["Revenues", "RevenueFromContractWithCustomerExcludingAssessedTax", "SalesRevenueNet"],
    "ebit": ["OperatingIncomeLoss"],
    "pretax": ["IncomeLossFromContinuingOperationsBeforeIncomeTaxesExtraordinaryItemsNoncontrollingInterest",
               "IncomeLossFromContinuingOperationsBeforeIncomeTaxesMinorityInterestAndIncomeLossFromEquityMethodInvestments"],
    "tax": ["IncomeTaxExpenseBenefit"],
    "net_income": ["NetIncomeLoss"],
    "da": ["DepreciationDepletionAndAmortization", "DepreciationAmortizationAndAccretionNet", "DepreciationAndAmortization",
           "Depreciation"],
    "capex": ["PaymentsToAcquirePropertyPlantAndEquipment", "PaymentsToAcquireProductiveAssets"],
    "cfo": ["NetCashProvidedByUsedInOperatingActivities"],
    "interest": ["InterestExpense", "InterestExpenseNonoperating", "InterestExpenseDebt"],
    "sbc": ["ShareBasedCompensation", "AllocatedShareBasedCompensationExpense"],
    "shares": ["WeightedAverageNumberOfDilutedSharesOutstanding"],
}
STOCKS = {
    "cash": ["CashCashEquivalentsAndShortTermInvestments", "CashAndCashEquivalentsAtCarryingValue"],
    "debt": ["LongTermDebt", "LongTermDebtNoncurrent", "DebtInstrumentCarryingAmount"],
    "equity": ["StockholdersEquity", "StockholdersEquityIncludingPortionAttributableToNoncontrollingInterest"],
}


class Financials(BaseModel):
    ticker: str
    name: str
    currency: str
    fiscal_years: list[str]                 # fiscal year-end dates, oldest first
    items: dict[str, list[float | None]]    # line item -> one value per fiscal year
    source: str

    def last(self, item: str, n: int = 1) -> list[float]:
        return [v for v in self.items.get(item, [])[-n:] if v is not None]


# ---------------------------------------------------------------------------
# SEC EDGAR

def sec_financials(ticker: str, years: int = 6) -> Financials:
    facts = _sec_json(SEC_FACTS.format(cik=_cik(ticker)))
    gaap = facts.get("facts", {}).get("us-gaap", {})
    flows = {k: _annual(gaap, tags, flow=True) for k, tags in FLOWS.items()}
    stocks = {k: _annual(gaap, tags, flow=False) for k, tags in STOCKS.items()}
    ends = sorted(flows["revenue"].index)[-years:]
    if len(ends) < 3:
        raise DataError(f"SEC {ticker}: only {len(ends)} annual revenue figures")
    pick = lambda s: [None if pd.isna(v := s.get(e)) else float(v) for e in ends]
    return Financials(ticker=ticker.upper(), name=facts.get("entityName", ticker), currency="USD",
                      fiscal_years=[e.date().isoformat() for e in ends],
                      items={k: pick(s) for k, s in {**flows, **stocks}.items()}, source="SEC EDGAR")


def annual_facts(units: list[dict], flow: bool) -> pd.Series:
    """Fiscal-year values by period end from one tag's XBRL facts: 10-K only, a ~12-month span for flows, the latest
    filing for each end (restated figures win)."""
    rows = []
    for f in units:
        if f.get("form") not in ("10-K", "10-K/A", "20-F", "40-F") or "end" not in f:
            continue
        if flow:
            if "start" not in f or not 350 <= (pd.Timestamp(f["end"]) - pd.Timestamp(f["start"])).days <= 380:
                continue
        rows.append((pd.Timestamp(f["end"]), f.get("filed", ""), float(f["val"])))
    if not rows:
        return pd.Series(dtype=float)
    df = pd.DataFrame(rows, columns=["end", "filed", "val"]).sort_values(["end", "filed"])
    return df.groupby("end")["val"].last()


def _annual(gaap: dict, tags: list[str], flow: bool) -> pd.Series:
    # Companies switch tags over time (Revenues -> RevenueFromContract...): fill gaps from later tags.
    out = pd.Series(dtype=float)
    for tag in tags:
        units = gaap.get(tag, {}).get("units", {})
        vals = units.get("USD") or units.get("shares") or []
        s = annual_facts(vals, flow)
        out = s if out.empty else out.combine_first(s)
    return out


def _cik(ticker: str) -> int:
    for row in _sec_json(SEC_TICKERS).values():
        if row["ticker"].upper() == ticker.upper():
            return int(row["cik_str"])
    raise DataError(f"SEC: ticker {ticker} not found")


def _sec_json(url: str) -> dict:
    try:
        resp = requests.get(url, headers={"User-Agent": USER_AGENT}, timeout=60)
        resp.raise_for_status()
    except requests.RequestException as exc:
        raise DataError(f"{url}: {exc}") from exc
    return resp.json()


# ---------------------------------------------------------------------------
# Yahoo Finance: Mexican statements, prices, market data, peers

YAHOO_ROWS = {
    "revenue": ["Total Revenue"], "ebit": ["Operating Income", "EBIT"], "pretax": ["Pretax Income"],
    "tax": ["Tax Provision"], "net_income": ["Net Income"], "interest": ["Interest Expense"],
    "da": ["Depreciation And Amortization", "Depreciation Amortization Depletion"], "capex": ["Capital Expenditure"],
    "cfo": ["Operating Cash Flow"], "sbc": ["Stock Based Compensation"], "shares": ["Diluted Average Shares"],
    "cash": ["Cash Cash Equivalents And Short Term Investments", "Cash And Cash Equivalents"],
    "debt": ["Total Debt"], "equity": ["Stockholders Equity"],
}


def yahoo_financials(ticker: str) -> Financials:
    import yfinance as yf

    try:
        with warnings.catch_warnings():
            warnings.simplefilter("ignore")
            tk = yf.Ticker(ticker)
            frames = [tk.income_stmt, tk.cashflow, tk.balance_sheet]
            info = tk.info
    except Exception as exc:
        raise DataError(f"Yahoo {ticker}: {exc}") from exc
    df = pd.concat([f for f in frames if f is not None and not f.empty])
    if df.empty:
        raise DataError(f"Yahoo {ticker}: no statements")
    df = df[~df.index.duplicated()]
    ends = sorted(df.columns)
    items = {}
    for k, rows in YAHOO_ROWS.items():
        row = next((df.loc[r] for r in rows if r in df.index), None)
        vals = [None if row is None or pd.isna(row.get(e)) else float(row[e]) for e in ends]
        items[k] = [abs(v) if k == "capex" and v is not None else v for v in vals]   # Yahoo shows capex as negative
    return Financials(ticker=ticker.upper(), name=info.get("longName", ticker), currency=info.get("financialCurrency", "MXN"),
                      fiscal_years=[pd.Timestamp(e).date().isoformat() for e in ends], items=items, source="Yahoo Finance")


class Market(BaseModel):
    price: float
    shares_out: float           # all share classes
    beta: float                 # 5y monthly regression vs the benchmark, Blume-adjusted
    beta_raw: float
    benchmark: str
    multiples: dict[str, float | None]   # trailing P/E, forward P/E, EV/EBITDA, EV/revenue as Yahoo reports them


def market_data(ticker: str, benchmark: str) -> Market:
    import yfinance as yf

    try:
        with warnings.catch_warnings():
            warnings.simplefilter("ignore")
            tk = yf.Ticker(ticker)
            info = tk.info
            px = yf.download([ticker, benchmark], period="5y", interval="1mo", auto_adjust=True, progress=False)["Close"]
    except Exception as exc:
        raise DataError(f"Yahoo {ticker}: {exc}") from exc
    price = info.get("currentPrice") or info.get("regularMarketPrice")
    shares = info.get("impliedSharesOutstanding") or info.get("sharesOutstanding")
    if not price or not shares:
        raise DataError(f"Yahoo {ticker}: no price or share count")
    raw = regression_beta(px[ticker], px[benchmark])
    return Market(price=float(price), shares_out=float(shares), beta=0.67 * raw + 0.33, beta_raw=raw, benchmark=benchmark,
                  multiples=peer_multiples(info))


def peer_multiples(info: dict) -> dict[str, float | None]:
    keys = {"pe": "trailingPE", "pe_fwd": "forwardPE", "ev_ebitda": "enterpriseToEbitda", "ev_revenue": "enterpriseToRevenue"}
    return {k: (float(info[v]) if isinstance(info.get(v), (int, float)) and info[v] > 0 else None) for k, v in keys.items()}


def peers_multiples(tickers: list[str]) -> dict[str, dict[str, float | None]]:
    import yfinance as yf

    out = {}
    for t in tickers:
        try:
            with warnings.catch_warnings():
                warnings.simplefilter("ignore")
                out[t] = peer_multiples(yf.Ticker(t).info)
        except Exception:   # one missing peer should not sink the valuation
            continue
    return out


def regression_beta(stock: pd.Series, index: pd.Series) -> float:
    r = pd.concat([stock, index], axis=1).dropna().pct_change().dropna()
    if len(r) < 24:
        raise DataError("beta: under 24 months of overlapping prices")
    return float(r.cov().iloc[0, 1] / r.iloc[:, 1].var())
