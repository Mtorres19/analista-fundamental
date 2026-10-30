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
    # shortcut: debt + debt_current double-counts the current part when a company only tags LongTermDebt (which already
    # includes it); small for most issuers, upgrade by reading LongTermDebt alone when Noncurrent is missing.
    "debt": ["LongTermDebtNoncurrent", "LongTermDebt", "DebtInstrumentCarryingAmount"],
    "debt_current": ["LongTermDebtCurrent", "DebtCurrent"],
    "equity": ["StockholdersEquity", "StockholdersEquityIncludingPortionAttributableToNoncontrollingInterest"],
}


class Financials(BaseModel):
    ticker: str
    name: str
    currency: str
    fiscal_years: list[str]                 # fiscal year-end dates, oldest first
    items: dict[str, list[float | None]]    # line item -> one value per fiscal year
    source: str
    ttm: dict[str, float] = {}              # trailing twelve months (flows) and latest balance (stocks) after the last 10-K
    ttm_end: str | None = None

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
    ttm, ttm_end = {}, None
    for k, tags in {**FLOWS, **STOCKS}.items():
        for tag in tags:
            got = latest_facts(_units(gaap, tag), ends[-1], flow=k in FLOWS)
            if got:
                ttm[k], end = got
                ttm_end = max(ttm_end or end, end)
                if k == "revenue" and (pair := ytd_pair(_units(gaap, tag), ends[-1])):
                    ttm["revenue_ytd_growth"] = float(pair[0]["val"]) / float(pair[1]["val"]) - 1
                break
    return Financials(ticker=ticker.upper(), name=facts.get("entityName", ticker), currency="USD",
                      fiscal_years=[e.date().isoformat() for e in ends],
                      items={k: pick(s) for k, s in {**flows, **stocks}.items()}, source="SEC EDGAR",
                      ttm=ttm, ttm_end=ttm_end)


def latest_facts(units: list[dict], fy_end: pd.Timestamp, flow: bool) -> tuple[float, str] | None:
    """Value after the last fiscal year from 10-Qs: for a flow, trailing twelve months = last fiscal year + this
    year-to-date - the same span a year earlier; for a stock, the latest quarter-end balance. None if no 10-Q since."""
    if not flow:
        q = [f for f in units if f.get("form") in ("10-Q", "10-Q/A") and "end" in f and pd.Timestamp(f["end"]) > fy_end]
        if not q:
            return None
        f = max(q, key=lambda f: (f["end"], f.get("filed", "")))
        return float(f["val"]), f["end"]
    pair, fy = ytd_pair(units, fy_end), annual_facts(units, flow=True)
    if pair is None or fy_end not in fy.index:
        return None
    now, before = pair
    return float(fy[fy_end]) + float(now["val"]) - float(before["val"]), now["end"]


def ytd_pair(units: list[dict], fy_end: pd.Timestamp) -> tuple[dict, dict] | None:
    """This fiscal year's latest year-to-date 10-Q fact and the same span a year earlier."""
    days = lambda f: (pd.Timestamp(f["end"]) - pd.Timestamp(f["start"])).days
    ytd = [f for f in units if f.get("form") in ("10-Q", "10-Q/A") and "start" in f and "end" in f
           and pd.Timestamp(f["end"]) > fy_end and abs((pd.Timestamp(f["start"]) - fy_end).days - 1) <= 3]
    if not ytd:
        return None
    now = max(ytd, key=lambda f: (f["end"], f.get("filed", "")))
    year_ago = pd.Timestamp(now["end"]) - pd.DateOffset(years=1)
    prior = [f for f in units if "start" in f and abs((pd.Timestamp(f["end"]) - year_ago).days) <= 7
             and abs(days(f) - days(now)) <= 7]
    return (now, max(prior, key=lambda f: f.get("filed", ""))) if prior else None


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
        s = annual_facts(_units(gaap, tag), flow)
        out = s if out.empty else out.combine_first(s)
    return out


def _units(gaap: dict, tag: str) -> list[dict]:
    units = gaap.get(tag, {}).get("units", {})
    return units.get("USD") or units.get("shares") or []


def _cik(ticker: str) -> int:
    for row in _sec_json(SEC_TICKERS).values():
        if row["ticker"].upper() == ticker.upper():
            return int(row["cik_str"])
    raise DataError(f"SEC: ticker {ticker} not found")


def _sec_json(url: str) -> dict:
    # The SEC blocks requests whose User-Agent carries no contact (name and e-mail): it must come from the environment.
    agent = os.environ.get("SEC_USER_AGENT")
    if not agent:
        raise DataError("SEC_USER_AGENT is not set: the SEC requires 'name email', e.g. 'analista-fundamental you@mail.com'")
    try:
        resp = requests.get(url, headers={"User-Agent": agent}, timeout=60)
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


class Consensus(BaseModel):
    """What the analysts say, shown next to our value for comparison only; never an input to the DCF."""
    target_mean: float | None
    target_median: float | None
    target_low: float | None
    target_high: float | None
    ratings: dict[str, int]                 # strongBuy, buy, hold, sell, strongSell (latest month)
    revenue: dict[str, dict[str, float]]    # '0y' / '+1y' -> {avg, growth, analysts}


def consensus(ticker: str) -> Consensus | None:
    import yfinance as yf

    try:
        with warnings.catch_warnings():
            warnings.simplefilter("ignore")
            tk = yf.Ticker(ticker)
            t = tk.analyst_price_targets or {}
            rec, rev = tk.recommendations_summary, tk.revenue_estimate
    except Exception:   # a missing consensus must not stop the valuation
        return None
    num = lambda v: float(v) if isinstance(v, (int, float)) and v == v else None
    ratings = ({k: int(rec.iloc[0][k]) for k in ("strongBuy", "buy", "hold", "sell", "strongSell") if k in rec.columns}
               if rec is not None and not rec.empty else {})
    revenue = {}
    if rev is not None and not rev.empty:
        for period in ("0y", "+1y"):
            if period in rev.index and num(rev.loc[period].get("avg")):
                row = rev.loc[period]
                revenue[period] = {"avg": float(row["avg"]), "growth": num(row.get("growth")) or 0.0,
                                   "analysts": num(row.get("numberOfAnalysts")) or 0.0}
    out = Consensus(target_mean=num(t.get("mean")), target_median=num(t.get("median")), target_low=num(t.get("low")),
                    target_high=num(t.get("high")), ratings=ratings, revenue=revenue)
    return out if out.target_mean or out.revenue else None


def regression_beta(stock: pd.Series, index: pd.Series) -> float:
    r = pd.concat([stock, index], axis=1).dropna().pct_change().dropna()
    if len(r) < 24:
        raise DataError("beta: under 24 months of overlapping prices")
    return float(r.cov().iloc[0, 1] / r.iloc[:, 1].var())
