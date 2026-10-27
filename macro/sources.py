"""Where the macro data comes from: FRED, Banxico SIE, the IMF and Yahoo Finance (indices).

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
    "US_REAL": {t: ("fred", sid, 1) for t, sid in (("5y", "DFII5"), ("10y", "DFII10"), ("30y", "DFII30"))},
    # Banxico weekly auction yields (CETES and fixed-rate Bonos M); a tenor is only auctioned every few weeks.
    "MX_CURVE": {t: ("banxico", sid, 1) for t, sid in (
        ("28d", "SF43936"), ("91d", "SF43939"), ("182d", "SF43942"), ("364d", "SF43945"), ("3y", "SF43883"),
        ("5y", "SF43886"), ("10y", "SF44071"), ("20y", "SF45384"), ("30y", "SF60696"))},
    # name -> Yahoo Finance ticker, daily closes in local currency.
    "INDICES": {n: ("yahoo", t, 1) for n, t in (
        ("S&P 500", "^GSPC"), ("Nasdaq", "^IXIC"), ("Dow Jones", "^DJI"), ("Russell 2000", "^RUT"),
        ("IPC México", "^MXX"), ("Euro Stoxx 50", "^STOXX50E"), ("Nikkei 225", "^N225"), ("FTSE 100", "^FTSE"),
        ("Emergentes (EEM)", "EEM"))},
}

# IMF World Economic Outlook: real GDP growth and average CPI inflation, % per year.
IMF_INDICATORS = ("NGDP_RPCH", "PCPIPCH")
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


def parse_banxico(payload: dict) -> pd.Series:
    try:
        datos = payload["bmx"]["series"][0]["datos"]
    except (KeyError, IndexError, TypeError) as exc:
        raise DataError("Banxico: unexpected payload") from exc
    # Dates are dd/mm/yyyy, numbers carry thousands commas, "N/E" means no data.
    idx = pd.to_datetime([d["fecha"] for d in datos], format="%d/%m/%Y")
    vals = pd.to_numeric(pd.Series([d["dato"].replace(",", "") for d in datos], index=idx), errors="coerce")
    return vals.dropna()


def _fred(series_id: str) -> pd.Series:
    resp = _get(FRED_CSV, params={"id": series_id})
    df = pd.read_csv(io.StringIO(resp.text), index_col=0, parse_dates=True)
    # FRED writes "." for missing days (holidays).
    return pd.to_numeric(df.iloc[:, 0], errors="coerce").dropna()


def _banxico(series_id: str) -> pd.Series:
    token = os.environ.get("BANXICO_TOKEN")
    if not token:
        raise DataError("BANXICO_TOKEN is not set (free at https://www.banxico.org.mx/SieAPIRest/service/v1/token)")
    resp = _get(BANXICO_API.format(id=series_id), headers={"Bmx-Token": token})
    return parse_banxico(resp.json())


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


def _get(url: str, **kwargs) -> requests.Response:
    try:
        resp = requests.get(url, timeout=30, **kwargs)
        resp.raise_for_status()
    except requests.RequestException as exc:
        raise DataError(f"{url}: {exc}") from exc
    return resp
