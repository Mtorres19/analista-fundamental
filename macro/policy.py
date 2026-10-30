"""Policy-rate probabilities from futures and options: what the market prices for the Fed and Banxico.

Fed: CME FedWatch method on 30-day Fed funds futures (monthly average EFFR = 100 - price). In a month with a
FOMC decision on day d of N, avg = (d x before + (N - d) x after) / N, so the post-meeting rate falls out; a
month with no meeting reads the rate directly. Each meeting's expected move, in 25 bp steps, is split between
the two adjacent outcomes and the steps compound across meetings.
Banxico: no free TIIE futures or options (MexDer is paid), so the path comes from the daily Cetes curve:
forward rates between Cetes tenors minus a term premium (5-year average of forward minus the Banxico rate
that followed), and is shown next to the Banxico survey.
Options: MOVE (Treasury implied vol) sets the width of the policy-rate distribution; Mexico's is scaled by
the ratio of realized 1y-yield volatility, since no MXN rate option is free. VIX term structure and the SPY
25-delta skew read equity risk. All market numbers come from Yahoo Finance and Banxico; none are official
FedWatch figures. Rates in percent.
"""

from __future__ import annotations

import math

import numpy as np
import pandas as pd
from pydantic import BaseModel

from macro import sources

STEP = 0.25
# FOMC decision days (second day of each meeting), federalreserve.gov/monetarypolicy/fomccalendars.htm.
# shortcut: hard-coded; add the next year's dates when the Fed publishes them (usually in August).
FOMC = [pd.Timestamp(d) for d in (
    "2026-01-28", "2026-03-18", "2026-04-29", "2026-06-17", "2026-07-29", "2026-09-16", "2026-10-28", "2026-12-09",
    "2027-01-27", "2027-03-17", "2027-04-28", "2027-06-09", "2027-07-28", "2027-09-15", "2027-10-27", "2027-12-08")]
# Banxico announcements. shortcut: 2026 only (17-dic per secondary calendars); Banxico had not published 2027's
# in a free source on 29-oct-2026, so beyond December probabilities are read at 3/6/12-month horizons instead.
BANXICO = [pd.Timestamp(d) for d in ("2026-11-05", "2026-12-17")]
CETES_DAYS = {"28d": 28, "91d": 91, "182d": 182, "364d": 364}


def fedwatch(avg: pd.Series, meetings: list[pd.Timestamp], current: float) -> list[dict]:
    """Expected rate after each meeting covered by the futures. *avg*: monthly average rate by month start."""
    months = {m.replace(day=1) for m in meetings}
    out, before = [], None
    for m in sorted(x for x in meetings if x.replace(day=1) in avg.index):
        ms = m.replace(day=1)
        prev, nxt = ms - pd.DateOffset(months=1), ms + pd.DateOffset(months=1)
        if before is None:
            before = float(avg[prev]) if prev in avg.index and prev not in months else current
        n, d = ms.days_in_month, m.day
        after = (float(avg[nxt]) if nxt in avg.index and nxt not in months
                 else (float(avg[ms]) * n - before * d) / (n - d))
        out.append({"date": m, "before": before, "after": after})
        before = after
    return out


def step_distribution(path: list[dict], current: float) -> list[dict]:
    """Per meeting: probabilities of cut/hold/hike at that meeting and of each cumulative 25 bp bucket vs today."""
    dist, rows = {0: 1.0}, []
    for p in path:
        k = (p["after"] - p["before"]) / STEP
        lo = math.floor(k)
        move = {lo: 1 - (k - lo), lo + 1: k - lo}
        new = {}
        for a, pa in dist.items():
            for b, pb in move.items():
                new[a + b] = new.get(a + b, 0.0) + pa * pb
        dist = {k2: v for k2, v in new.items() if v > 1e-9}
        rows.append({**p, "expected": p["after"], "change": p["after"] - current,
                     "p_cut": sum(v for s, v in move.items() if s < 0), "p_hike": sum(v for s, v in move.items() if s > 0),
                     "p_hold": move.get(0, 0.0),
                     "cum": {b: sum(v for s, v in dist.items() if (s <= -2 if b == -2 else s >= 2 if b == 2 else s == b))
                             for b in (-2, -1, 0, 1, 2)}})
    return rows


def cetes_forwards(yields: dict[int, float]) -> list[tuple[int, int, float]]:
    """(from day, to day, forward %) between consecutive Cetes tenors; yields are simple act/360 rates."""
    days = sorted(yields)
    out = [(0, days[0], yields[days[0]])]
    for d1, d2 in zip(days, days[1:]):
        g1, g2 = 1 + yields[d1] / 100 * d1 / 360, 1 + yields[d2] / 100 * d2 / 360
        out.append((d1, d2, (g2 / g1 - 1) * 360 / (d2 - d1) * 100))
    return out


def cetes_term_premium(cetes: dict[str, pd.Series], target: pd.Series, as_of: pd.Timestamp, years: int = 5) -> list[float]:
    """Average over the last *years* of each Cetes forward minus the Banxico rate actually set over that window."""
    df = pd.concat({CETES_DAYS[k]: v for k, v in cetes.items()}, axis=1).dropna()
    df = df[df.index > as_of - pd.DateOffset(years=years + 1)]
    daily = target.resample("D").ffill()
    premia = []
    windows = cetes_forwards({d: 0.0 for d in df.columns})
    for i, (d1, d2, _) in enumerate(windows):
        vals = []
        for t, row in df[df.index <= as_of - pd.Timedelta(days=d2)].iloc[::5].iterrows():   # weekly sample
            fwd = cetes_forwards(row.to_dict())[i][2]
            realized = daily[t + pd.Timedelta(days=d1): t + pd.Timedelta(days=d2)].mean()
            if pd.notna(realized):
                vals.append(fwd - realized)
        premia.append(float(np.mean(vals)) if vals else 0.0)
    return premia


def normal_buckets(mean: float, sigma: float, current: float) -> dict[int, float]:
    """Probability of ending in each 25 bp bucket around today's rate (-2 = 50 bp or more lower ... +2 = 50+ higher)."""
    cdf = lambda x: 0.5 * (1 + math.erf((x - mean) / (sigma * math.sqrt(2)))) if sigma > 0 else float(x >= mean)
    edges = [current + (k + 0.5) * STEP for k in (-2, -1, 0, 1)]
    c = [cdf(e) for e in edges]
    return {-2: c[0], -1: c[1] - c[0], 0: c[2] - c[1], 1: c[3] - c[2], 2: 1 - c[3]}


class RatesOutlook(BaseModel):
    fed_current: float
    fed: list[dict]                 # per FOMC meeting (step_distribution rows)
    fed_path: list[list]            # [ms, expected rate] at each meeting
    sofr_check: dict | None         # SR3 front quarter vs Fed funds futures over the same months
    mx_current: float
    mx_meetings: list[dict]         # per Banxico meeting with a known date
    mx_path: list[list]             # Cetes-implied path, [ms, %], after term premium
    mx_premium: list[float]
    horizons: dict[str, dict]       # "US"/"MX" -> {"3m"/"6m"/"12m": {"mean", "sigma", "buckets"}}
    move: float
    vix: dict[str, float]           # 9d, 1m, 3m, 6m
    spy_skew: dict | None           # 25-delta put minus call implied vol, ~1 month
    p_spx_down10: float             # risk-neutral P(S&P 500 >10% lower in a month), from the VIX
    usdmxn_vol: float               # realized 3m, annualized %
    mx_vol_scale: float             # realized vol of Mexico's 1y yield / the US 2y
    front_vol_scale: float          # realized vol of the US 2y / MOVE's 2-5-10-30y blend


def build_rates(as_of: str, fetch: sources.Fetch = sources.fetch, options=sources.option_chain) -> RatesOutlook:
    t = pd.Timestamp(as_of)
    us, mx = sources.load("US", as_of, fetch), sources.load("MX", as_of, fetch)
    fed_now = float(us["policy_rate"].iloc[-1])
    zq = 100 - fetch("yahoo_curve", "ZQ.CBT")
    fed = step_distribution(fedwatch(zq, [m for m in FOMC if m > t], fed_now), fed_now)
    if not fed:
        raise sources.DataError("Fed funds futures cover no upcoming FOMC meeting")

    sofr_check = None
    try:  # cross-check only: a missing SOFR contract does not stop the dashboard
        sr3 = 100 - fetch("yahoo_curve", "SR3.CME")
        q = sr3.index[sr3.index >= t.replace(day=1)][0]
        window = zq[(zq.index >= q) & (zq.index < q + pd.DateOffset(months=3))]
        sofr_check = {"month": q.strftime("%Y-%m"), "sofr": float(sr3[q]), "fed_funds": float(window.mean())}
    except (sources.DataError, IndexError):
        pass

    # Banxico: Cetes forwards net of the term premium; then probabilities at known meetings and horizons.
    curve = sources.load("MX_CURVE", as_of, fetch)
    cetes = {k: curve[k] for k in CETES_DAYS}
    mx_now = float(mx["policy_rate"].iloc[-1])
    premium = cetes_term_premium(cetes, mx["policy_rate"], t)
    fwd = cetes_forwards({CETES_DAYS[k]: float(v.iloc[-1]) for k, v in cetes.items()})
    days = [(a + b) / 2 for a, b, _ in fwd]
    rates = [f - p for (_, _, f), p in zip(fwd, premium)]
    at = lambda when: float(np.interp((when - t).days, [0] + days, [mx_now] + rates))
    mx_rows, prev = [], mx_now
    for m in BANXICO:
        if m > t:
            mx_rows.append({"date": m, "before": prev, "after": at(m)})
            prev = at(m)
    mx_meetings = step_distribution(mx_rows, mx_now)

    # Options: MOVE is ~1m implied normal vol of Treasury yields (bp a year); Mexico scaled by realized vol.
    vol = sources.load("VOL", as_of, fetch)
    move = float(vol["move"].iloc[-1])
    # MOVE blends 2/5/10/30y options (weights 20/20/40/20); the policy rate moves like the front end, so scale it by
    # how volatile the US 2y is relative to that blend (realized, 1y), and Mexico further by its 1y vs the US 2y.
    realized = lambda s: float(s.dropna().diff().iloc[-250:].std())
    usc = sources.load("US_CURVE", as_of, fetch)
    blend = sum(w * realized(usc[k]) for k, w in (("2y", .2), ("5y", .2), ("10y", .4), ("30y", .2)))
    ratio = lambda a, b: a / b if b > 0 else 1.0   # a flat series has no volatility to compare
    front = ratio(realized(usc["2y"]), blend)
    scale = ratio(realized(curve["364d"]), realized(usc["2y"]))
    fed_path = pd.Series([r["expected"] for r in fed], index=[r["date"] for r in fed])
    horizons = {}
    for c, now, path, k in (("US", fed_now, lambda d: float(np.interp((d - t).days, [0] + [(x - t).days for x in fed_path.index],
                                                                         [fed_now] + list(fed_path.values))), front),
                            ("MX", mx_now, at, front * scale)):
        horizons[c] = {}
        for h in (3, 6, 12):
            mean = path(t + pd.DateOffset(months=h))
            sigma = move / 100 * k * math.sqrt(h / 12)
            horizons[c][f"{h}m"] = {"mean": mean, "sigma": sigma, "buckets": normal_buckets(mean, sigma, now)}

    vix = {k: float(vol[k].iloc[-1]) for k in ("vix9d", "vix", "vix3m", "vix6m")}
    s1 = vix["vix"] / 100 * math.sqrt(1 / 12)
    p_down = 0.5 * (1 + math.erf((math.log(0.9) + 0.5 * s1 ** 2) / (s1 * math.sqrt(2))))
    fx = mx["fx_usd"].dropna()
    fx_vol = float(np.log(fx).diff().iloc[-63:].std() * math.sqrt(252) * 100)
    return RatesOutlook(
        fed_current=fed_now, fed=fed, fed_path=[[int(d.timestamp() * 1000), round(v, 3)] for d, v in fed_path.items()],
        sofr_check=sofr_check, mx_current=mx_now, mx_meetings=mx_meetings,
        mx_path=[[int((t + pd.Timedelta(days=d)).timestamp() * 1000), round(r, 3)] for d, r in zip(days, rates)],
        mx_premium=premium, horizons=horizons, move=move, vix=vix, spy_skew=spy_skew(options=options),
        p_spx_down10=p_down, usdmxn_vol=fx_vol, mx_vol_scale=scale, front_vol_scale=front)


def spy_skew(ticker: str = "SPY", options=sources.option_chain) -> dict | None:
    """25-delta put minus 25-delta call implied vol on the expiry nearest 30 days. None if the chain is unavailable."""
    try:
        chain, spot, days = options(ticker, target_days=30)
    except sources.DataError:
        return None
    t = days / 365
    def delta(row, call):
        s = row["impliedVolatility"]
        if not s or s <= 0:
            return np.nan
        d1 = (math.log(spot / row["strike"]) + 0.5 * s * s * t) / (s * math.sqrt(t))
        n = 0.5 * (1 + math.erf(d1 / math.sqrt(2)))
        return n if call else n - 1
    pick = {}
    for side, call, target in (("calls", True, 0.25), ("puts", False, -0.25)):
        df = chain[side].copy()
        df["delta"] = df.apply(lambda r: delta(r, call), axis=1)
        df = df.dropna(subset=["delta"])
        if df.empty:
            return None
        pick[side] = df.iloc[(df["delta"] - target).abs().argsort()[:1]].iloc[0]
    return {"days": days, "put_iv": float(pick["puts"]["impliedVolatility"] * 100),
            "call_iv": float(pick["calls"]["impliedVolatility"] * 100),
            "skew": float((pick["puts"]["impliedVolatility"] - pick["calls"]["impliedVolatility"]) * 100)}
