"""Where the macro data comes from: FRED, Banxico SIE, the IMF, the NY Fed (r*) and Yahoo Finance (indices).

Every series the analysis reads is declared once in SERIES, with its source,
its id there, and its publication lag. `load` cuts each series at as_of minus
that lag, so a past date only sees prints that were plausibly public then.

Infrastructure failures RAISE (DataError): missing data must never pass for
"no signal".

shortcut: FRED, Banxico and the IMF serve their latest vintage, so revised
data (GDP, IMF estimates) leaks into backtests; switch to ALFRED / WEO
vintages when backtesting on macro.
"""

from __future__ import annotations

import io
import os
from collections.abc import Callable
from datetime import date, timedelta

import pandas as pd
import requests

FRED_CSV = "https://fred.stlouisfed.org/graph/fredgraph.csv"
BANXICO_API = "https://www.banxico.org.mx/SieAPIRest/service/v1/series/{id}/datos"
IMF_API = "https://www.imf.org/external/datamapper/api/v1/{indicator}"
DAMODARAN_ERP = "https://pages.stern.nyu.edu/~adamodar/pc/implprem/ERPbymonth.xlsx"
HLW_XLSX = "https://www.newyorkfed.org/medialibrary/media/research/economists/williams/data/Holston_Laubach_Williams_current_estimates.xlsx"

# region -> name -> (source, series id, publication lag in days).
# FRED dates a quarter by its first day, so quarterly lags count from there.
SERIES: dict[str, dict[str, tuple[str, str, int]]] = {
    "US": {
        "rate_10y": ("fred", "DGS10", 1),              # 10y Treasury, %
        "policy_rate": ("fred", "DFF", 1),             # effective fed funds, %
        "breakeven_10y": ("fred", "T10YIE", 1),        # 10y breakeven inflation, %
        "credit_spread": ("fred", "BAA10Y", 1),        # Baa corporate minus 10y, pp
        "cpi": ("fred", "CPIAUCSL", 45),               # CPI index, monthly
        "unemployment": ("fred", "UNRATE", 35),        # %, monthly
        "gdp": ("fred", "GDPC1", 120),                 # real GDP, quarterly
    },
    "MX": {
        "rate_10y": ("fred", "IRLTLT01MXM156N", 45),   # 10y government bond, %, monthly (OECD)
        "policy_rate": ("banxico", "SF61745", 1),      # Banxico target rate, %
        "cpi": ("banxico", "SP1", 25),                 # INPC index, biweekly/monthly
        "unemployment": ("fred", "LRHUTTTTMXM156S", 60),  # %, monthly (OECD)
        "gdp": ("fred", "NGDPRSAXDCMXQ", 150),         # real GDP, quarterly
        "fx_usd": ("fred", "DEXMXUS", 1),              # pesos per dollar, daily
        "reer": ("fred", "RBMXBIS", 75),               # BIS real broad effective exchange rate, monthly; up = stronger
    },
    "GLOBAL": {
        "vix": ("fred", "VIXCLS", 1),                  # S&P 500 implied vol
        "dollar": ("fred", "DTWEXBGS", 1),             # broad trade-weighted dollar
        "brent": ("fred", "DCOILBRENTEU", 1),          # Brent, USD/bbl
        "copper": ("fred", "PCOPPUSDM", 45),           # copper, USD/t, monthly
    },
    # Curves: tenor -> yield in %. Tenor keys end in d/m/y so markets.py can place them in years.
    "US_CURVE": {t: ("fred", sid, 1) for t, sid in (
        ("1m", "DGS1MO"), ("3m", "DGS3MO"), ("6m", "DGS6MO"), ("1y", "DGS1"), ("2y", "DGS2"), ("3y", "DGS3"),
        ("5y", "DGS5"), ("7y", "DGS7"), ("10y", "DGS10"), ("20y", "DGS20"), ("30y", "DGS30"))},
    "US_REAL": {t: ("fred", sid, 1) for t, sid in (
        ("5y", "DFII5"), ("7y", "DFII7"), ("10y", "DFII10"), ("20y", "DFII20"), ("30y", "DFII30"))},
    # Short end, daily market yields: TIIE de fondeo (overnight) and CETES from Banxico's price vector (CF300).
    "MX_CURVE": {t: ("banxico", sid, 1) for t, sid in (
        ("1d", "SF331451"), ("28d", "SF45470"), ("91d", "SF45471"), ("182d", "SF45472"), ("364d", "SF45473"),
        ("2y", "SF349889"))},
    # Banxico price vector (CF300, daily market valuation) for each Bonos M / Udibonos benchmark bucket:
    # days to maturity, dirty price (Udibonos in pesos per 100 UDIs) and coupon; markets.py turns them into yields.
    "MX_VECTOR": {f"{b}_{f}": ("banxico", sid, 1) for b, ids in (
        ("M3", ("SF45427", "SF45449", "SF45475")), ("M5", ("SF45428", "SF45451", "SF45476")),
        ("M7", ("SF45429", "SF45453", "SF45477")), ("M10", ("SF45430", "SF45455", "SF45478")),
        ("M20", ("SF45431", "SF45457", "SF45479")), ("M30", ("SF60720", "SF60722", "SF60723")),
        ("U3", ("SF61784", "SF61786", "SF61787")), ("U10", ("SF45432", "SF45459", "SF45480")),
        ("U20", ("SF50761", "SF50766", "SF50763")), ("U30", ("SF50762", "SF50768", "SF50764")))
        for f, sid in zip(("plazo", "sucio", "cupon"), ids)} | {
        "cetes2y_plazo": ("banxico", "SF349886", 1), "udi": ("banxico", "SP68257", 1)},
    # Weekly auction yields: fallback for a vector bucket with no recent price, and a sanity check.
    "MX_AUCTION": {t: ("banxico", sid, 1) for t, sid in (
        ("3y", "SF43883"), ("5y", "SF43886"), ("10y", "SF44071"), ("20y", "SF45384"), ("30y", "SF60696"),
        ("udi_3y", "SF61592"), ("udi_10y", "SF43924"), ("udi_20y", "SF46958"), ("udi_30y", "SF46961"))},
    # name -> Yahoo Finance ticker, daily closes in local currency.
    "INDICES": {n: ("yahoo", t, 1) for n, t in (
        ("S&P 500", "^GSPC"), ("Nasdaq", "^IXIC"), ("Dow Jones", "^DJI"), ("Russell 2000", "^RUT"),
        ("IPC México", "^MXX"), ("Euro Stoxx 50", "^STOXX50E"), ("Nikkei 225", "^N225"), ("FTSE 100", "^FTSE"),
        ("Emergentes (EEM)", "EEM"))},
    "US_ECON": {
        "trade_balance": ("fred", "BOPGSTB", 40),       # goods & services, USD mn, monthly
        "current_account": ("fred", "IEABC", 90),       # USD mn, quarterly
        "industrial_production": ("fred", "INDPRO", 20),
        "retail_sales": ("fred", "RSAFS", 20),           # USD mn, monthly
        "payrolls": ("fred", "PAYEMS", 10),              # thousands
        "sentiment": ("fred", "UMCSENT", 10),            # U. Michigan
        "inflation_exp_1y": ("fred", "EXPINF1YR", 20),   # Cleveland Fed, %
    },
    "MX_ECON": {
        "current_account": ("banxico", "SE44352", 60),   # USD mn, quarterly (BoP, MBP6)
        "exports": ("banxico", "SE44355", 60),           # goods exports, USD mn, quarterly
        "imports": ("banxico", "SE44374", 60),           # goods imports, USD mn, quarterly
        "remittances": ("banxico", "SE27803", 35),       # USD mn, monthly
        "reserves": ("banxico", "SF43707", 7),           # USD mn, weekly
        "igae": ("banxico", "SR17692", 60),              # activity index, base 2018
    },
    # Daily prices for the market charts where the macro series is monthly.
    "DAILY": {"copper": ("yahoo", "HG=F", 1)},     # COMEX copper future, USD per pound
    "RISK": {
        "em_corp_oas": ("fred", "BAMLEMCBPIOAS", 1),     # ICE BofA EM corporate OAS, pp; Mexico's default spread proxy
        "us_hy_oas": ("fred", "BAMLH0A0HYM2", 1),        # ICE BofA US high yield OAS, pp
    },
    # NY Fed Holston-Laubach-Williams one-sided estimates, quarterly dated at the quarter's start;
    # Damodaran's implied ERP of the S&P 500 (trailing 12m cash yield), monthly.
    "EXTERNAL": {"hlw_rstar_us": ("nyfed", "rstar", 120), "implied_erp": ("damodaran", "ERP (T12 m with sustainable payout)", 5)},
    # Outside views the forecasts are anchored to. Banxico survey of private-sector economists (medians, monthly),
    # Fed SEP longer-run medians, US 5y breakeven.
    "CONSENSUS": {
        "mx_infl_12m": ("banxico", "SR14195", 35), "mx_infl_1_4y": ("banxico", "SR14209", 35),
        "mx_infl_5_8y": ("banxico", "SR14216", 35), "mx_gdp_10y": ("banxico", "SR14469", 35),
        "mx_cete28_t": ("banxico", "SR14749", 35), "mx_cete28_t1": ("banxico", "SR14756", 35),
        "us_gdp_lr": ("fred", "GDPC1MDLR", 1), "us_unemp_lr": ("fred", "UNRATEMDLR", 1),
        "us_breakeven_5y": ("fred", "T5YIE", 1),
    },
    # Futures curves: price by contract month (index = delivery month, not a quote date), so they are fetched
    # directly, never through load(). Fed funds: rate = 100 - price.
    "FUTURES": {"fed_funds": ("yahoo_curve", "ZQ.CBT", 0), "brent": ("yahoo_curve", "BZ.NYM", 0),
                "copper": ("yahoo_curve", "HG.CMX", 0), "sofr_3m": ("yahoo_curve", "SR3.CME", 0)},
    # Implied volatility indices, daily: Treasury options (ICE BofA MOVE) and the VIX term structure.
    "VOL": {"move": ("yahoo", "^MOVE", 1), "vix9d": ("yahoo", "^VIX9D", 1), "vix": ("yahoo", "^VIX", 1),
            "vix3m": ("yahoo", "^VIX3M", 1), "vix6m": ("yahoo", "^VIX6M", 1)},
}

# IMF World Economic Outlook: real GDP growth and average CPI inflation, % per year.
IMF_INDICATORS = ("NGDP_RPCH", "PCPIPCH", "BCA_NGDPD", "GGXWDG_NGDP", "GGXCNL_NGDP")  # + current account, gross debt, fiscal balance, % of GDP
# The G20 economies (EU aside) the global breadth is measured on.
G20 = ("USA", "MEX", "CHN", "JPN", "DEU", "IND", "GBR", "FRA", "ITA", "BRA",
       "CAN", "RUS", "KOR", "AUS", "ESP", "IDN", "TUR", "SAU", "ARG", "ZAF")

Fetch = Callable[[str, str], pd.Series]


class DataError(RuntimeError):
    """A series could not be fetched, or has no data before as_of."""


def fetch(source: str, series_id: str) -> pd.Series:
    """Full history of one series, indexed by observation date."""
    if source == "fred":
        return _fred(series_id)
    if source == "banxico":
        return _banxico(series_id)
    if source == "yahoo":
        return _yahoo(series_id)
    if source == "nyfed":
        return parse_hlw(_get(HLW_XLSX).content)
    if source == "damodaran":
        return parse_damodaran_erp(_get(DAMODARAN_ERP).content, series_id)
    if source == "yahoo_curve":
        return _yahoo_curve(series_id)
    raise ValueError(f"unknown source {source!r}")


def load(region: str, as_of: str, fetch: Fetch = fetch) -> dict[str, pd.Series]:
    """Every series of *region*, cut at as_of minus its publication lag."""
    cutoff = date.fromisoformat(as_of[:10])
    out = {}
    for name, (source, sid, lag) in SERIES[region].items():
        series = fetch(source, sid)
        series = series[series.index <= pd.Timestamp(cutoff - timedelta(days=lag))]
        if series.empty:
            raise DataError(f"{source} {sid} ({region} {name}): no observations before {as_of}")
        out[name] = series
    return out


def imf_weo(indicator: str) -> pd.DataFrame:
    """One WEO indicator for every country: index = year, columns = ISO3, values in %."""
    resp = _get(IMF_API.format(indicator=indicator))
    return parse_imf(resp.json(), indicator)


def parse_imf(payload: dict, indicator: str) -> pd.DataFrame:
    try:
        values = payload["values"][indicator]
    except (KeyError, TypeError) as exc:
        raise DataError(f"IMF {indicator}: unexpected payload") from exc
    df = pd.DataFrame({c: {int(y): v for y, v in years.items()} for c, years in values.items()})
    return df.sort_index()


def parse_hlw(xlsx: bytes) -> pd.Series:
    """US natural rate (r*, %) from the NY Fed HLW workbook: the 'Natural Rate (r*)' block's US column."""
    try:
        df = pd.read_excel(io.BytesIO(xlsx), sheet_name="HLW Estimates", header=None)
        col = next(c for c in df.columns if str(df.iat[4, c]).startswith("Natural Rate"))
        assert str(df.iat[5, col]).strip() == "US"
        body = df.iloc[6:, [0, col]].dropna()
    except Exception as exc:
        raise DataError(f"NY Fed HLW: unexpected workbook layout ({exc})") from exc
    return pd.Series(body.iloc[:, 1].astype(float).values, index=pd.to_datetime(body.iloc[:, 0]))


def parse_damodaran_erp(xlsx: bytes, column: str) -> pd.Series:
    """One column of Damodaran's ERPbymonth workbook, in %, indexed by start of month."""
    try:
        df = pd.read_excel(io.BytesIO(xlsx), header=0)
        out = pd.to_numeric(df[column], errors="coerce") * 100
        out.index = pd.to_datetime(df["Start of month"], errors="coerce")
        out = out[out.index.notna()].dropna()
    except Exception as exc:
        raise DataError(f"Damodaran ERP: unexpected workbook layout ({exc})") from exc
    if out.empty:
        raise DataError(f"Damodaran ERP: no {column} values")
    return out


def parse_banxico(payload: dict, series_id: str | None = None) -> pd.Series:
    """One series from a SIE answer: the first, or the one named series_id when the call asked for several."""
    try:
        series = payload["bmx"]["series"]
        datos = next(x for x in series if series_id in (None, x["idSerie"])).get("datos", [])
    except (KeyError, IndexError, TypeError, StopIteration) as exc:
        raise DataError(f"Banxico {series_id or ''}: unexpected payload") from exc
    # Dates are dd/mm/yyyy, numbers carry thousands commas, "N/E" means no data.
    idx = pd.to_datetime([d["fecha"] for d in datos], format="%d/%m/%Y")
    vals = pd.to_numeric(pd.Series([d["dato"].replace(",", "") for d in datos], index=idx), errors="coerce")
    return vals.dropna()


def _fred(series_id: str) -> pd.Series:
    resp = _get(FRED_CSV, params={"id": series_id})
    df = pd.read_csv(io.StringIO(resp.text), index_col=0, parse_dates=True)
    # FRED writes "." for missing days (holidays).
    return pd.to_numeric(df.iloc[:, 0], errors="coerce").dropna()


_banxico_cache: dict[str, dict] = {}


def _banxico(series_id: str) -> pd.Series:
    """SIE caps queries per token, so the first call fetches every declared Banxico series, 20 per request."""
    token = os.environ.get("BANXICO_TOKEN")
    if not token:
        raise DataError("BANXICO_TOKEN is not set (free at https://www.banxico.org.mx/SieAPIRest/service/v1/token)")
    if series_id not in _banxico_cache:
        wanted = [series_id] + sorted({sid for reg in SERIES.values() for src, sid, _ in reg.values()
                                       if src == "banxico" and sid != series_id and sid not in _banxico_cache})
        for i in range(0, len(wanted), 20):
            resp = _get(BANXICO_API.format(id=",".join(wanted[i:i + 20])), headers={"Bmx-Token": token})
            for x in resp.json().get("bmx", {}).get("series", []):
                _banxico_cache[x["idSerie"]] = {"bmx": {"series": [x]}}
    if series_id not in _banxico_cache:
        raise DataError(f"Banxico {series_id}: not in the SIE answer")
    return parse_banxico(_banxico_cache[series_id])


def _yahoo(ticker: str) -> pd.Series:
    import warnings

    import yfinance as yf  # only the markets layer needs it

    try:
        with warnings.catch_warnings():
            warnings.simplefilter("ignore")  # yfinance is noisy about pandas deprecations
            df = yf.download(ticker, period="15y", interval="1d", auto_adjust=True, progress=False)
    except Exception as exc:
        raise DataError(f"Yahoo {ticker}: {exc}") from exc
    if df is None or df.empty:
        raise DataError(f"Yahoo {ticker}: no data")
    close = df["Close"]
    close = close.iloc[:, 0] if isinstance(close, pd.DataFrame) else close
    close.index = pd.DatetimeIndex(close.index).tz_localize(None)
    return close.dropna()


def _yahoo_curve(root: str) -> pd.Series:
    """Last close of each futures contract for the next 15 delivery months, e.g. 'BZ.NYM' -> BZZ26.NYM, BZF27.NYM..."""
    import warnings

    import yfinance as yf

    code, exch = root.split(".")
    start = pd.Timestamp.today().normalize().replace(day=1)
    months = [start + pd.DateOffset(months=k) for k in range(15)]
    tickers = {f"{code}{'FGHJKMNQUVXZ'[m.month - 1]}{m.year % 100:02d}.{exch}": m for m in months}
    try:
        with warnings.catch_warnings():
            warnings.simplefilter("ignore")
            df = yf.download(list(tickers), period="10d", interval="1d", progress=False, auto_adjust=False)["Close"]
    except Exception as exc:
        raise DataError(f"Yahoo futures {root}: {exc}") from exc
    last = df.ffill().iloc[-1].dropna() if df is not None and not df.empty else pd.Series(dtype=float)
    out = pd.Series({tickers[t]: float(v) for t, v in last.items() if t in tickers}).sort_index()
    if len(out) < 4:   # SOFR futures list only quarterly months this far out
        raise DataError(f"Yahoo futures {root}: only {len(out)} contracts quoted")
    return out


def option_chain(ticker: str, target_days: int = 30) -> tuple[dict, float, int]:
    """Calls and puts (DataFrames) of the expiry closest to *target_days*, the spot price and the days to expiry."""
    import warnings

    import yfinance as yf

    try:
        with warnings.catch_warnings():
            warnings.simplefilter("ignore")
            tk = yf.Ticker(ticker)
            today = pd.Timestamp.today().normalize()
            expiry = min(tk.options, key=lambda e: abs((pd.Timestamp(e) - today).days - target_days))
            chain = tk.option_chain(expiry)
            spot = float(tk.history(period="5d")["Close"].dropna().iloc[-1])
    except Exception as exc:
        raise DataError(f"Yahoo options {ticker}: {exc}") from exc
    return {"calls": chain.calls, "puts": chain.puts}, spot, max(1, (pd.Timestamp(expiry) - today).days)


def _get(url: str, **kwargs) -> requests.Response:
    try:
        resp = requests.get(url, timeout=60, **kwargs)
        resp.raise_for_status()
    except requests.RequestException as exc:
        detail = getattr(exc.response, "text", "")[:200] if getattr(exc, "response", None) is not None else ""
        raise DataError(f"{url}: {exc} {detail}".strip()) from exc
    return resp
