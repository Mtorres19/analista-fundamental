"""Markets layer: equity indices and the US / Mexico yield curves, read against the macro report.

The point is the cross-feed. The curve feeds the macro reading (recession odds from the 3m10y slope, the policy
path the 2y / 1y CETES price in, Mexico's sovereign spread against our country-risk premium). The macro reading
feeds the indices (an expected-return path from our cost of equity, and reasons tying regime, real rates and
curve to the equity outlook). Market stress (drawdowns, inversions, high real yields) comes back as flags.
Rates are in percent here (4.2 = 4.2%), as the sources serve them; returns are decimals.
"""

from __future__ import annotations

import math

import pandas as pd
from pydantic import BaseModel

from macro import sources
from macro.report import MacroReport

# Estrella-Mishkin probit on the 10y minus 3m Treasury spread, in percentage points (NY Fed's published fit).
PROBIT_A, PROBIT_B = -0.5333, -0.6330
US_INDICES = ("S&P 500", "Nasdaq", "Dow Jones", "Russell 2000")
INDEX_CURRENCY = {"IPC México": "MXN", "Euro Stoxx 50": "EUR", "Nikkei 225": "JPY", "FTSE 100": "GBP"}


def tenor_years(tenor: str) -> float:
    return int(tenor[:-1]) / {"d": 365, "m": 12, "y": 1}[tenor[-1]]


def recession_probability(spread_3m10y_pp: float) -> float:
    """Probability of a US recession within 12 months, from the 10y-3m spread in pp."""
    z = PROBIT_A + PROBIT_B * spread_3m10y_pp
    return 0.5 * (1 + math.erf(z / math.sqrt(2)))


class Curve(BaseModel):
    country: str
    tenors: list[str]
    years: list[float]
    now: list[float | None]
    m3: list[float | None]      # three months before as_of
    y1: list[float | None]      # a year before as_of

    def at(self, tenor: str) -> float | None:
        return self.now[self.tenors.index(tenor)]


class IndexStats(BaseModel):
    name: str
    currency: str
    last: float
    r1m: float
    ytd: float
    r1y: float
    drawdown: float             # from the 52-week high, <= 0
    vs_200d: float              # last vs its 200-day average
    vol_3m: float               # annualised, daily log returns
    cost_of_equity: float       # the macro report's expected return for this market
    spark: list[list]           # one year of closes, [ms, value]


class Markets(BaseModel):
    as_of: str
    indices: list[IndexStats]
    ipc_usd: IndexStats
    us_curve: Curve
    mx_curve: Curve
    us_real: dict[str, float]
    us_real_curve: Curve
    mx_real_curve: Curve          # Udibonos
    us_2s10s: float
    us_3m10y: float
    mx_28d10y: float
    recession_prob: float
    us_policy_gap: float        # 2y minus fed funds: < 0 the market prices cuts
    mx_policy_gap: float        # 364d CETES minus the Banxico rate
    mx_us_spread: dict[str, float]
    mx_spread_10y: float
    slopes: dict[str, list[list]]   # history for the chart: 2s10s, 3m10y, recession probability

    @property
    def flags(self) -> dict[str, list[str]]:
        us, mx, world = [], [], []
        if self.us_2s10s < 0 or self.us_3m10y < 0:
            us.append("curva de Treasuries invertida (señal de recesión)")
        if self.recession_prob >= 0.3:
            us.append(f"probabilidad de recesión a 12m de {self.recession_prob:.0%} según la curva")
        if self.us_real.get("10y", 0) > 2:
            us.append("tasa real a 10 años arriba de 2%: presión sobre múltiplos")
        if self.mx_28d10y < 0:
            mx.append("curva de México invertida (CETES 28d arriba del bono 10a)")
        for ix in self.indices:
            if ix.drawdown <= -0.10:
                (mx if ix.name == "IPC México" else us if ix.name in US_INDICES else world).append(
                    f"{ix.name} {abs(ix.drawdown):.0%} abajo de su máximo de 52 semanas")
        return {"EE.UU.": us, "México": mx, "Mundo": world}


def build_markets(r: MacroReport, fetch: sources.Fetch = sources.fetch) -> Markets:
    as_of = r.as_of
    us_c = sources.load("US_CURVE", as_of, fetch)
    mx_c = sources.load("MX_CURVE", as_of, fetch)
    real = {t: float(v.iloc[-1]) for t, v in sources.load("US_REAL", as_of, fetch).items()}
    idx = sources.load("INDICES", as_of, fetch)
    fx = sources.load("MX", as_of, fetch)["fx_usd"]
    coe_us, coe_mx = (a.cost_of_equity() for a in r.assumptions)

    stats = [_index(n, s, INDEX_CURRENCY.get(n, "USD"), coe_mx if n == "IPC México" else coe_us)
             for n, s in idx.items()]
    ipc = idx["IPC México"]
    ipc_usd = _index("IPC México en dólares", (ipc / fx.reindex(ipc.index, method="ffill")).dropna(), "USD", coe_us)

    us_curve, mx_curve = _curve("US", us_c, as_of), _curve("MX", mx_c, as_of)
    for c, tenors in ((us_curve, ("2y", "10y")), (mx_curve, ("28d", "364d", "10y"))):
        for t in tenors:
            if c.at(t) is None:
                raise sources.DataError(f"{c.country} curve: no {t} yield in the 60 days before {as_of}")
    s3m10y = us_c["10y"] - us_c["3m"].reindex(us_c["10y"].index)
    s2s10 = us_c["10y"] - us_c["2y"].reindex(us_c["10y"].index)
    monthly = lambda s: s.dropna().resample("MS").mean().dropna()
    hist = lambda s: monthly(s)[monthly(s).index > pd.Timestamp(as_of) - pd.DateOffset(years=20)]
    prob = hist(s3m10y).apply(recession_probability) * 100

    spread = {}
    for t_mx, t_us in (("364d", "1y"), ("3y", "3y"), ("5y", "5y"), ("10y", "10y"), ("20y", "20y"), ("30y", "30y")):
        a, b = mx_curve.at(t_mx), us_curve.at(t_us)
        if a is not None and b is not None:
            spread[t_us] = round(a - b, 3)
    return Markets(
        as_of=as_of, indices=stats, ipc_usd=ipc_usd, us_curve=us_curve, mx_curve=mx_curve, us_real=real,
        us_real_curve=_curve("US", sources.load("US_REAL", as_of, fetch), as_of),
        mx_real_curve=_curve("MX", sources.load("MX_REAL", as_of, fetch), as_of),
        us_2s10s=float(s2s10.dropna().iloc[-1]), us_3m10y=float(s3m10y.dropna().iloc[-1]),
        mx_28d10y=mx_curve.at("10y") - mx_curve.at("28d"),
        recession_prob=recession_probability(float(s3m10y.dropna().iloc[-1])),
        us_policy_gap=us_curve.at("2y") - r.us.policy_rate * 100,
        mx_policy_gap=mx_curve.at("364d") - r.mx.policy_rate * 100,
        mx_us_spread=spread, mx_spread_10y=spread["10y"],
        slopes={"2s10s": _pts(hist(s2s10)), "3m10y": _pts(hist(s3m10y)), "prob": _pts(prob)},
    )


def reasons(m: Markets, r: MacroReport) -> dict[str, list[str]]:
    """Why curves and markets are where they are, read against the macro regime and real rates: {"Curvas", "Mercados"}."""
    by = {i.name: i for i in m.indices}
    sp, ipc = by["S&P 500"], by["IPC México"]
    real10 = m.us_real.get("10y")
    curves = [
        f"La curva de Treasuries tiene 2s10s de {m.us_2s10s:+.2f} pp y 3m10y de {m.us_3m10y:+.2f} pp: "
        + ("invertida, el mercado espera recortes fuertes porque ve la economía debilitarse." if m.us_3m10y < 0 else
           "positiva, el mercado no descuenta recesión.")
        + f" El modelo probit de la Fed de Nueva York traduce ese 3m10y en {m.recession_prob:.0%} de probabilidad de "
          "recesión en 12 meses.",
        f"El bono a 2 años paga {m.us_curve.at('2y'):.2f}% contra una tasa Fed de {r.us.policy_rate * 100:.2f}%: "
        + ("el mercado espera recortes." if m.us_policy_gap < -0.15 else "el mercado espera alzas." if m.us_policy_gap > 0.15
           else "el mercado no espera grandes cambios en la tasa.")
        + f" En México los CETES a un año ({m.mx_curve.at('364d'):.2f}%) contra Banxico ({r.mx.policy_rate * 100:.2f}%) "
        + ("descuentan recortes." if m.mx_policy_gap < -0.15 else "descuentan alzas." if m.mx_policy_gap > 0.15
           else "no descuentan cambios grandes."),
    ]
    be_mx = m.mx_curve.at("10y") - m.mx_real_curve.at("10y") if m.mx_real_curve.at("10y") is not None else None
    if be_mx is not None:
        curves.append(f"En México el Bono M a 10 años ({m.mx_curve.at('10y'):.2f}%) menos el Udibono a 10 años "
                      f"({m.mx_real_curve.at('10y'):.2f}% real) da una inflación implícita de {be_mx:.2f}%, "
                      + ("arriba de la meta de 3% de Banxico: el mercado duda de que la inflación converja."
                         if be_mx > 3.5 else "cerca de la meta de 3% de Banxico."))
    out = []
    if real10 is not None:
        curves.append(f"La tasa real a 10 años (TIPS) es {real10:.2f}%"
                   + (": alta, sube la tasa de descuento y presiona los múltiplos de las acciones, más en las de crecimiento."
                      if real10 > 2 else ": moderada, no castiga de más las valuaciones."))
    regime = {"stagflation": "estanflación, el régimen más difícil para acciones: márgenes apretados y tasas que no bajan",
              "goldilocks": "goldilocks, el mejor régimen para acciones",
              "reflation": "reflación, que favorece cíclicas y materias primas",
              "slowdown": "desaceleración, que favorece defensivas y bonos"}
    out.append(f"El S&P 500 lleva {sp.ytd:+.1%} en el año y {sp.r1y:+.1%} a 12 meses, {sp.vs_200d:+.1%} contra su promedio de "
               f"200 días. EE.UU. está en {regime[r.us.regime]}; con nuestro costo de capital de {sp.cost_of_equity:.1%} "
               "esa es la rentabilidad que exige el modelo, no un pronóstico de precio.")
    out.append(f"El IPC lleva {ipc.ytd:+.1%} en el año en pesos y {m.ipc_usd.ytd:+.1%} en dólares; "
               + ("el peso fuerte le suma al inversionista en dólares." if m.ipc_usd.ytd > ipc.ytd
                  else "el peso le resta al inversionista en dólares.")
               + f" México está en {regime[r.mx.regime]}.")
    crp = r.assumptions[1].country_risk_premium * 100
    out.append(f"El bono a 10 años de México paga {m.mx_spread_10y:.2f} pp sobre el Treasury; nuestro riesgo país en la "
               f"valuación es {crp:.2f} pp. " + ("El supuesto es más exigente que el mercado: conservador."
                                                   if crp >= m.mx_spread_10y else
                                                   "El mercado pide más que nuestro supuesto: la valuación podría ser optimista."))
    worst = min(m.indices, key=lambda i: i.drawdown)
    out.append(f"El índice más lejos de su máximo de 52 semanas es {worst.name} ({worst.drawdown:.1%}); "
               f"el más volátil a 3 meses es {max(m.indices, key=lambda i: i.vol_3m).name}.")
    return {"Curvas": curves, "Mercados": out}


def _index(name: str, s: pd.Series, currency: str, coe: float) -> IndexStats:
    s = s.dropna()
    last, t = float(s.iloc[-1]), s.index[-1]
    back = lambda off: float(s.asof(t - off))
    year_start = s[s.index < pd.Timestamp(t.year, 1, 1)]
    r3m = s[s.index > t - pd.DateOffset(months=3)]
    logret = (r3m / r3m.shift(1)).dropna().apply(math.log)
    year = s[s.index > t - pd.DateOffset(years=1)]
    return IndexStats(
        name=name, currency=currency, last=last, r1m=last / back(pd.DateOffset(months=1)) - 1,
        ytd=last / float(year_start.iloc[-1]) - 1 if not year_start.empty else 0.0,
        r1y=last / back(pd.DateOffset(years=1)) - 1, drawdown=last / float(year.max()) - 1,
        vs_200d=last / float(s.iloc[-200:].mean()) - 1, vol_3m=float(logret.std() * math.sqrt(252)),
        cost_of_equity=coe, spark=_pts(year.resample("W-FRI").last().dropna()),
    )


def _curve(country: str, s: dict[str, pd.Series], as_of: str) -> Curve:
    t = pd.Timestamp(as_of)
    # A tenor auctioned only now and then counts as "now" if printed in the last 60 days.
    at = lambda ser, when: (None if ser[ser.index <= when].empty or ser[ser.index <= when].index[-1] < when - pd.Timedelta(days=60)
                            else round(float(ser[ser.index <= when].iloc[-1]), 3))
    tenors = list(s)
    return Curve(country=country, tenors=tenors, years=[tenor_years(k) for k in tenors],
                 now=[at(s[k], t) for k in tenors], m3=[at(s[k], t - pd.DateOffset(months=3)) for k in tenors],
                 y1=[at(s[k], t - pd.DateOffset(years=1)) for k in tenors])


def _pts(series: pd.Series) -> list[list]:
    return [[int(i.timestamp() * 1000), round(float(v), 3)] for i, v in series.items()]
