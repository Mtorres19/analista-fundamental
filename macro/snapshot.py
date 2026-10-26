"""In-house reading of the economy: one snapshot per country plus a global one.

Everything here is computed from the raw series in sources.py: growth versus
its own trend, inflation and its direction, real rates, the curve, labour
slack, the peso's real level. External forecasts (IMF) are only used to
compare against, never as the reading itself. Rates and growth are decimals
(0.042 = 4.2%).
"""

from __future__ import annotations

import pandas as pd
from pydantic import BaseModel

from macro.sources import G20, DataError


class CountrySnapshot(BaseModel):
    country: str
    as_of: str
    rate_10y: float
    policy_rate: float
    inflation_yoy: float
    inflation_yoy_6m_ago: float
    gdp_yoy: float
    gdp_trend: float            # 10y CAGR of real GDP
    unemployment: float
    sahm_gap: float             # 3m avg unemployment minus its prior 12m low
    breakeven_10y: float | None = None
    credit_spread: float | None = None

    @property
    def curve(self) -> float:
        """10y minus the policy rate: negative means the market expects cuts / a slowdown."""
        return self.rate_10y - self.policy_rate

    @property
    def real_policy_rate(self) -> float:
        """Policy rate minus current inflation: above ~1-2% the central bank is restrictive."""
        return self.policy_rate - self.inflation_yoy

    @property
    def regime(self) -> str:
        """Growth vs trend x inflation direction — the four classic quadrants."""
        # Rounded to a basis point so float noise on flat series doesn't flip the quadrant.
        growth_up = round(self.gdp_yoy, 4) >= round(self.gdp_trend, 4)
        inflation_up = round(self.inflation_yoy, 4) >= round(self.inflation_yoy_6m_ago, 4)
        return {
            (True, False): "goldilocks",
            (True, True): "reflation",
            (False, True): "stagflation",
            (False, False): "slowdown",
        }[(growth_up, inflation_up)]

    @property
    def flags(self) -> list[str]:
        flags = []
        if self.curve < 0:
            flags.append("curva invertida (10a < tasa de política)")
        if self.sahm_gap >= 0.005:
            flags.append("regla de Sahm activada (desempleo subiendo)")
        if self.real_policy_rate > 0.02:
            flags.append("política monetaria restrictiva (tasa real > 2%)")
        if self.gdp_yoy < 0:
            flags.append("PIB real cayendo a tasa anual")
        if self.credit_spread is not None and self.credit_spread >= 0.03:
            flags.append("estrés de crédito (spread Baa >= 3pp)")
        return flags


class MexicoExtras(BaseModel):
    """What only matters for Mexico: carry against the US and the peso's real level."""

    fx_usd: float
    fx_yoy: float
    carry_vs_us: float          # Banxico rate minus fed funds
    real_carry_vs_us: float     # same, net of each inflation
    real_fx_gap: float          # real peso vs its 10y average; > 0 = peso weaker than usual (cheap)

    @property
    def flags(self) -> list[str]:
        flags = []
        if self.real_fx_gap < -0.10:
            flags.append("peso real >10% más fuerte que su promedio de 10 años (caro)")
        if self.real_fx_gap > 0.10:
            flags.append("peso real >10% más débil que su promedio de 10 años (barato)")
        if self.real_carry_vs_us < 0.01:
            flags.append("carry real vs EE.UU. menor a 1pp (riesgo de salida de capital)")
        return flags


class GlobalSnapshot(BaseModel):
    as_of: str
    year: int
    vix: float
    dollar_yoy: float
    brent_yoy: float
    copper_yoy: float
    g20_growth_median: float    # IMF, current year
    g20_breadth: float          # share of G20 growing faster this year than last
    growth: dict[str, float]    # IMF current-year growth by country
    inflation: dict[str, float]  # IMF current-year inflation by country

    @property
    def cycle(self) -> str:
        if self.g20_breadth >= 0.6:
            return "aceleración global"
        if self.g20_breadth <= 0.4:
            return "desaceleración global"
        return "ciclo global mixto"

    @property
    def flags(self) -> list[str]:
        flags = []
        if self.vix >= 25:
            flags.append(f"aversión al riesgo (VIX {self.vix:.0f})")
        if self.dollar_yoy > 0.05:
            flags.append("dólar fuerte (+5% anual): presión para emergentes")
        if self.copper_yoy < -0.10:
            flags.append("cobre cayendo >10% anual: señal de demanda industrial débil")
        if self.brent_yoy > 0.25:
            flags.append("petróleo +25% anual: presión inflacionaria")
        return flags


class Comparison(BaseModel):
    """Our latest reading against the IMF's estimate for the same year."""

    country: str
    year: int
    gdp_ours: float
    gdp_imf: float
    inflation_ours: float
    inflation_imf: float

    @property
    def flags(self) -> list[str]:
        flags = []
        if self.gdp_ours - self.gdp_imf < -0.01:
            flags.append("crecimiento observado >1pp debajo del FMI: riesgo de recorte")
        if self.gdp_ours - self.gdp_imf > 0.01:
            flags.append("crecimiento observado >1pp arriba del FMI: posible sorpresa positiva")
        if self.inflation_ours - self.inflation_imf > 0.01:
            flags.append("inflación >1pp arriba de lo que espera el FMI")
        return flags


# ---------------------------------------------------------------------------
# Builders
# ---------------------------------------------------------------------------

def build_country(country: str, as_of: str, s: dict[str, pd.Series]) -> CountrySnapshot:
    unrate = _monthly(s["unemployment"]).rolling(3).mean().dropna()
    if len(unrate) < 13:
        raise DataError(f"{country} unemployment: not enough history as of {as_of}")
    return CountrySnapshot(
        country=country,
        as_of=as_of[:10],
        rate_10y=_last(s["rate_10y"]) / 100,
        policy_rate=_last(s["policy_rate"]) / 100,
        inflation_yoy=_yoy(s["cpi"]),
        inflation_yoy_6m_ago=_yoy(s["cpi"], months_back=6),
        gdp_yoy=_yoy(s["gdp"]),
        gdp_trend=_cagr(s["gdp"], years=10),
        unemployment=_last(s["unemployment"]) / 100,
        sahm_gap=float(unrate.iloc[-1] - unrate.iloc[-13:-1].min()) / 100,
        breakeven_10y=_last(s["breakeven_10y"]) / 100 if "breakeven_10y" in s else None,
        credit_spread=_last(s["credit_spread"]) / 100 if "credit_spread" in s else None,
    )


def build_mexico_extras(mx: dict[str, pd.Series], us: dict[str, pd.Series],
                        mx_snap: CountrySnapshot, us_snap: CountrySnapshot) -> MexicoExtras:
    fx = _monthly(mx["fx_usd"])
    # Real exchange rate: pesos per dollar adjusted by relative prices.
    real = (fx * _monthly(us["cpi"]) / _monthly(mx["cpi"])).dropna()
    window = real[real.index > real.index[-1] - pd.DateOffset(years=10)]
    return MexicoExtras(
        fx_usd=_last(mx["fx_usd"]),
        fx_yoy=_yoy(mx["fx_usd"]),
        carry_vs_us=mx_snap.policy_rate - us_snap.policy_rate,
        real_carry_vs_us=mx_snap.real_policy_rate - us_snap.real_policy_rate,
        real_fx_gap=float(real.iloc[-1] / window.mean() - 1),
    )


def build_global(as_of: str, s: dict[str, pd.Series], weo: dict[str, pd.DataFrame]) -> GlobalSnapshot:
    year = int(as_of[:4])
    growth, inflation = weo["NGDP_RPCH"], weo["PCPIPCH"]
    if year not in growth.index or year - 1 not in growth.index:
        raise DataError(f"IMF WEO has no growth for {year - 1}-{year}")
    sample = [c for c in G20 if c in growth.columns and growth[c][[year, year - 1]].notna().all()]
    if not sample:
        raise DataError("IMF WEO: no G20 country has growth data")
    now = growth.loc[year, sample] / 100
    accelerating = (growth.loc[year, sample] > growth.loc[year - 1, sample]).mean()
    return GlobalSnapshot(
        as_of=as_of[:10],
        year=year,
        vix=_last(s["vix"]),
        dollar_yoy=_yoy(s["dollar"]),
        brent_yoy=_yoy(s["brent"]),
        copper_yoy=_yoy(s["copper"]),
        g20_growth_median=float(now.median()),
        g20_breadth=float(accelerating),
        growth={c: float(v) for c, v in now.items()},
        inflation={c: float(inflation.loc[year, c]) / 100 for c in sample
                   if c in inflation.columns and pd.notna(inflation.loc[year, c])},
    )


def compare_with_imf(snap: CountrySnapshot, iso3: str, weo: dict[str, pd.DataFrame]) -> Comparison:
    year = int(snap.as_of[:4])
    try:
        gdp, infl = weo["NGDP_RPCH"].loc[year, iso3], weo["PCPIPCH"].loc[year, iso3]
    except KeyError as exc:
        raise DataError(f"IMF WEO has no {iso3} data for {year}") from exc
    return Comparison(country=snap.country, year=year, gdp_ours=snap.gdp_yoy, gdp_imf=float(gdp) / 100,
                      inflation_ours=snap.inflation_yoy, inflation_imf=float(infl) / 100)


# ---------------------------------------------------------------------------
# Series helpers
# ---------------------------------------------------------------------------

def _last(series: pd.Series) -> float:
    return float(series.iloc[-1])


def _monthly(series: pd.Series) -> pd.Series:
    return series.resample("MS").last().dropna()


def _yoy(series: pd.Series, months_back: int = 0) -> float:
    """% change over 12 months ending at the latest observation (or months_back before it)."""
    ser = _monthly(series)
    end = ser.index[-1] - pd.DateOffset(months=months_back)
    now, prior = ser.asof(end), ser.asof(end - pd.DateOffset(years=1))
    if pd.isna(now) or pd.isna(prior):
        raise DataError(f"not enough history for a yoy change at {end.date()}")
    return float(now / prior - 1)


def _cagr(series: pd.Series, years: int) -> float:
    start = series.asof(series.index[-1] - pd.DateOffset(years=years))
    if pd.isna(start):
        raise DataError(f"under {years}y of history for a trend")
    return float((series.iloc[-1] / start) ** (1 / years) - 1)
