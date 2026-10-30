"""Markets layer: equity indices and the US / Mexico yield curves, read against the macro report.

The point is the cross-feed. The curve feeds the macro reading (recession odds from the 3m10y slope, the policy
path the 2y / 1y CETES price in, Mexico's sovereign spread against our country-risk premium). The macro reading
feeds the indices (an expected-return path from our cost of equity, and reasons tying regime, real rates and
curve to the equity outlook). Market stress (drawdowns, inversions, high real yields) comes back as flags.
Rates are in percent here (4.2 = 4.2%), as the sources serve them; returns are decimals.
"""

from __future__ import annotations

import math

import numpy as np
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


STD_TENORS = (1, 2, 3, 5, 7, 10, 20, 30)   # years, where curves are compared on their fitted values


class NSS(BaseModel):
    """Nelson-Siegel(-Svensson) curve: yield in % at maturity t in years. tau2 None = plain Nelson-Siegel."""
    betas: list[float]
    tau1: float
    tau2: float | None = None

    def __call__(self, t):
        y = _ns_basis(np.atleast_1d(np.asarray(t, float)), self.tau1, self.tau2) @ np.asarray(self.betas)
        return float(y[0]) if np.ndim(t) == 0 else y


def _ns_basis(t: np.ndarray, tau1: float, tau2: float | None) -> np.ndarray:
    hump = lambda tau: ((1 - np.exp(-t / tau)) / (t / tau), (1 - np.exp(-t / tau)) / (t / tau) - np.exp(-t / tau))
    f1, f2 = hump(tau1)
    cols = [np.ones_like(t), f1, f2] + ([hump(tau2)[1]] if tau2 is not None else [])
    return np.column_stack(cols)


def fit_nss(years: list[float], yields: list[float]) -> NSS:
    """Least squares on the betas over a grid of decay parameters. Svensson only with 7+ nodes, else Nelson-Siegel,
    so a short curve (the real ones have 4-5 nodes) is not over-fitted."""
    t, y = np.asarray(years, float), np.asarray(yields, float)
    if len(t) < 4:
        raise sources.DataError(f"curve fit needs at least 4 nodes, got {len(t)}")
    best = None
    for tau1 in np.geomspace(0.1, 10, 40):
        for tau2 in (np.geomspace(tau1 * 1.5, 30, 16) if len(t) >= 7 else [None]):
            X = _ns_basis(t, tau1, tau2)
            b = np.linalg.lstsq(X, y, rcond=None)[0]
            err = float(((X @ b - y) ** 2).sum())
            if best is None or err < best[0] - 1e-12:
                best = (err, b, tau1, tau2)
    _, b, tau1, tau2 = best
    return NSS(betas=[float(x) for x in b], tau1=float(tau1), tau2=None if tau2 is None else float(tau2))


def ytm(dirty, coupon, days):
    """Yield to maturity, % a year, of Mexican fixed-coupon bonds (Bonos M, Udibonos): 182-day coupon periods,
    coupon per period = coupon% * 182/360 per 100, discounting at (1 + y * 182/360) per period, the first one
    fractional (days to next coupon / 182). Works elementwise on arrays (one bond per date); NaN in, NaN out."""
    p, c, d = (np.asarray(x, float) for x in (dirty, coupon, days))
    n = np.ceil(d / 182)
    first = np.where(d % 182 == 0, 182, d % 182) / 182
    cpn = c * 182 / 360
    k = np.arange(int(np.nanmax(n)) if np.isfinite(n).any() else 0)[:, None]   # coupon index, rows
    def price(y):
        disc = (1 + y * 182 / 36000) ** -(first + k)
        flows = np.where(k < n, cpn, 0) + np.where(k == n - 1, 100, 0)
        return (flows * disc).sum(axis=0)
    lo, hi = np.full(p.shape, -5.0), np.full(p.shape, 40.0)
    for _ in range(70):                    # bisection: price falls as the yield rises
        mid = (lo + hi) / 2
        cheap = price(mid) < p
        hi, lo = np.where(cheap, mid, hi), np.where(cheap, lo, mid)
    out = (lo + hi) / 2
    return np.where(np.isfinite(p) & np.isfinite(c) & np.isfinite(d) & (d > 0), out, np.nan)


def vector_nodes(v: dict[str, pd.Series], prefix: str, real: bool) -> dict[str, tuple[pd.Series, pd.Series]]:
    """Daily yield and years to maturity for each price-vector bucket (M3..M30 or U3..U30), keyed '3y', '10y'..."""
    out = {}
    for name in sorted({k.split("_")[0] for k in v if k.startswith(prefix)}, key=lambda b: int(b[1:])):
        df = pd.concat({f: v[f"{name}_{f}"] for f in ("plazo", "sucio", "cupon")}, axis=1).dropna()
        if real:  # Udibonos are priced in pesos: per 100 UDIs with that day's UDI value
            df["sucio"] = df["sucio"] / v["udi"].reindex(df.index, method="ffill")
            df = df.dropna()
        df = df[df.index > df.index[-1] - pd.DateOffset(years=6)] if len(df) else df
        out[f"{name[1:]}y"] = (pd.Series(ytm(df["sucio"], df["cupon"], df["plazo"]), index=df.index).dropna(),
                               df["plazo"] / 365)
    return out


class Curve(BaseModel):
    country: str
    tenors: list[str]
    years: list[float]
    years_by: dict[str, list[float]] = {}   # per date when maturities move (price-vector buckets roll down)
    now: list[float | None]
    m3: list[float | None]      # three months before as_of
    y1: list[float | None]      # a year before as_of
    fits: dict[str, NSS | None]  # "now" / "m3" / "y1" -> fitted curve, None with too few nodes that day

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
    mx_real_curve: Curve          # Udibonos, from the price vector
    mx_10y_daily: list[list]      # Bono M 7-10y bucket yield, daily, [ms, %]
    us10_daily: list[list]
    us_2s10s: float
    us_3m10y: float
    mx_28d10y: float
    recession_prob: float
    us_policy_gap: float        # 2y minus fed funds: < 0 the market prices cuts
    mx_policy_gap: float        # 364d CETES minus the Banxico rate
    mx_us_spread: dict[str, float]
    mx_spread_10y: float
    mx_real_spread_10y: float | None   # Udibono 10y minus TIPS 10y: the spread net of inflation and peso premia
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

    v = sources.load("MX_VECTOR", as_of, fetch)
    auction = sources.load("MX_AUCTION", as_of, fetch)
    nominal, realv = vector_nodes(v, "M", real=False), vector_nodes(v, "U", real=True)
    # A bucket with no price in 60 days (Bonos 5-7 often reads N/E) falls back to that tenor's auction yield.
    stale = lambda ser: ser.empty or ser.index[-1] < pd.Timestamp(as_of) - pd.Timedelta(days=60)
    for nodes, pre in ((nominal, ""), (realv, "udi_")):
        for t, (y, yrs) in list(nodes.items()):
            if stale(y) and pre + t in auction:
                nodes[t] = (auction[pre + t], pd.Series(tenor_years(t), index=auction[pre + t].index))
    mx_series = {**{k: x for k, x in mx_c.items() if k != "2y"}, "2y": mx_c["2y"], **{t: y for t, (y, _) in nominal.items()}}
    mx_years = {"2y": v["cetes2y_plazo"] / 365, **{t: yrs for t, (_, yrs) in nominal.items()}}
    us_curve, mx_curve = _curve("US", us_c, as_of), _curve("MX", mx_series, as_of, mx_years)
    self_real = _curve("MX", {t: y for t, (y, _) in realv.items()}, as_of, {t: yrs for t, (_, yrs) in realv.items()})
    for c, tenors in ((us_curve, ("2y", "10y")), (mx_curve, ("28d", "364d", "10y"))):
        for t in tenors:
            if c.at(t) is None:
                raise sources.DataError(f"{c.country} curve: no {t} yield in the 60 days before {as_of}")
    s3m10y = us_c["10y"] - us_c["3m"].reindex(us_c["10y"].index)
    s2s10 = us_c["10y"] - us_c["2y"].reindex(us_c["10y"].index)
    hist = lambda s: s.dropna()[s.dropna().index > pd.Timestamp(as_of) - pd.DateOffset(years=10)]   # daily
    prob = hist(s3m10y).apply(recession_probability) * 100

    # On the fitted curves, so tenors one country does not issue still compare.
    fm, fu = mx_curve.fits["now"], us_curve.fits["now"]
    if fm is None or fu is None:
        raise sources.DataError("curve fit: fewer than 4 nodes today on the US or Mexico curve")
    spread = {f"{t}y": round(float(fm(t) - fu(t)), 3) for t in STD_TENORS}
    return Markets(
        as_of=as_of, indices=stats, ipc_usd=ipc_usd, us_curve=us_curve, mx_curve=mx_curve, us_real=real,
        us_real_curve=_curve("US", sources.load("US_REAL", as_of, fetch), as_of),
        mx_real_curve=self_real, mx_10y_daily=_pts(mx_series["10y"][mx_series["10y"].index > pd.Timestamp(as_of) - pd.DateOffset(years=5)]),
        us10_daily=_pts(us_c["10y"].dropna()[us_c["10y"].dropna().index > pd.Timestamp(as_of) - pd.DateOffset(years=5)]),
        us_2s10s=float(s2s10.dropna().iloc[-1]), us_3m10y=float(s3m10y.dropna().iloc[-1]),
        mx_28d10y=mx_curve.at("10y") - mx_curve.at("28d"),
        recession_prob=recession_probability(float(s3m10y.dropna().iloc[-1])),
        us_policy_gap=us_curve.at("2y") - r.us.policy_rate * 100,
        mx_policy_gap=mx_curve.at("364d") - r.mx.policy_rate * 100,
        mx_us_spread=spread, mx_spread_10y=mx_curve.at("10y") - us_curve.at("10y"),
        mx_real_spread_10y=(self_real.at("10y") - real["10y"]) if self_real.at("10y") is not None and "10y" in real else None,
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
    out.append(country_risk_text(m, crp))
    worst = min(m.indices, key=lambda i: i.drawdown)
    out.append(f"El índice más lejos de su máximo de 52 semanas es {worst.name} ({worst.drawdown:.1%}); "
               f"el más volátil a 3 meses es {max(m.indices, key=lambda i: i.vol_3m).name}.")
    return {"Curvas": curves, "Mercados": out}


def country_risk_text(m: Markets, crp: float) -> str:
    """Our country-risk premium against the market's real spread. The nominal 10y spread also pays Mexico's higher
    inflation and the peso's risk, which the valuation prices separately, so it is not the comparison."""
    head = (f"El bono a 10 años de México paga {m.mx_spread_10y:.2f} pp sobre el Treasury en términos nominales, pero buena parte es "
            "inflación y prima cambiaria. ")
    if m.mx_real_spread_10y is None:
        return head + f"Sin Udibono a 10 años reciente no hay spread real que comparar con nuestro riesgo país ({crp:.2f} pp)."
    return head + (f"En términos reales (Udibono − TIPS) el diferencial es {m.mx_real_spread_10y:.2f} pp, y nuestro riesgo país en la "
                   f"valuación es {crp:.2f} pp: " + ("más exigente que el mercado, conservador." if crp >= m.mx_real_spread_10y
                                                      else "menos de lo que pide el mercado, la valuación podría ser optimista."))


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


def _curve(country: str, s: dict[str, pd.Series], as_of: str, maturity: dict[str, pd.Series] | None = None) -> Curve:
    """maturity: years to maturity by date for nodes whose maturity moves; other nodes sit at their nominal tenor."""
    t = pd.Timestamp(as_of)
    maturity = maturity or {}
    # A tenor auctioned only now and then counts as "now" if printed in the last 60 days.
    at = lambda ser, when: (None if ser[ser.index <= when].empty or ser[ser.index <= when].index[-1] < when - pd.Timedelta(days=60)
                            else round(float(ser[ser.index <= when].iloc[-1]), 3))
    tenors = list(s)
    dates = {"now": t, "m3": t - pd.DateOffset(months=3), "y1": t - pd.DateOffset(years=1)}
    yrs = lambda k, d: round(float(maturity[k][maturity[k].index <= d].iloc[-1]), 4) \
        if k in maturity and not maturity[k][maturity[k].index <= d].empty else tenor_years(k)
    years_by = {key: [yrs(k, d) for k in tenors] for key, d in dates.items()}
    vals = {key: [at(s[x], d) for x in tenors] for key, d in dates.items()}
    fit = lambda key: (fit_nss([y for y, x in zip(years_by[key], vals[key]) if x is not None], [x for x in vals[key] if x is not None])
                       if sum(x is not None for x in vals[key]) >= 4 else None)
    return Curve(country=country, tenors=tenors, years=years_by["now"], years_by=years_by, **vals,
                 fits={key: fit(key) for key in dates})


def _pts(series: pd.Series) -> list[list]:
    return [[int(i.timestamp() * 1000), round(float(v), 3)] for i, v in series.items()]
