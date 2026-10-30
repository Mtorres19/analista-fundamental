"""The numbers behind the page: KPIs, chart payloads, tables and summaries, all JSON-ready."""

from __future__ import annotations

import math

import numpy as np
import pandas as pd

from macro.economy import Economy
from macro.markets import Markets
from macro.neutral import Neutral
from macro.policy import RatesOutlook
from macro.report import MacroReport
from macro.snapshot import CountrySnapshot

HISTORY_YEARS = 10
REGIME_ES = {"goldilocks": "goldilocks", "reflation": "reflación", "stagflation": "estanflación", "slowdown": "desaceleración"}
REGIME_TEXT = {
    "goldilocks": "crece arriba de su tendencia con inflación bajando: el mejor cuadrante para acciones",
    "reflation": "crece arriba de su tendencia con inflación subiendo: favorece cíclicas y materias primas, presiona tasas",
    "stagflation": "crece debajo de su tendencia con inflación subiendo: el cuadrante más difícil para acciones y bonos",
    "slowdown": "crece debajo de su tendencia con inflación bajando: abre espacio a recortes de tasa, favorece defensivas y bonos",
}


def _kpis(r: MacroReport, m: Markets, n: dict[str, Neutral]) -> dict[str, list[dict]]:
    def k(label, value, sub="", tone="neutral"):
        return {"label": label, "value": value, "sub": sub, "tone": tone}

    def country(s: CountrySnapshot, cmp):
        return [k("Régimen", REGIME_ES[s.regime], "crecimiento vs tendencia × inflación",
                  {"goldilocks": "good", "stagflation": "bad"}.get(s.regime, "neutral")),
                k("PIB real anual", _p(s.gdp_yoy), f"tendencia {_p(s.gdp_trend)} · FMI {_p(cmp.gdp_imf)}",
                  "good" if s.gdp_yoy >= s.gdp_trend else "bad"),
                k("Inflación", _p(s.inflation_yoy), f"hace 6m {_p(s.inflation_yoy_6m_ago)} · FMI {_p(cmp.inflation_imf)}",
                  "good" if s.inflation_yoy < s.inflation_yoy_6m_ago else "bad"),
                k("Tasa de política", _p(s.policy_rate), f"real {_p(s.real_policy_rate)}"),
                k("Tasa neutral", f"{n[s.country].nominal:.2f}%", f"r* {n[s.country].rstar:.2f}% · brecha {n[s.country].gap:+.2f} pp",
                  "warn" if n[s.country].stance != "cerca de neutral" else "good"),
                k("Bono 10 años", _p(s.rate_10y), f"curva {_p(s.curve)}", "bad" if s.curve < 0 else "neutral"),
                k("Desempleo", _p(s.unemployment), f"brecha Sahm {_p(s.sahm_gap)}",
                  "bad" if s.sahm_gap >= 0.005 else "good")]

    w, e = r.world, r.mx_extras
    mx = country(r.mx, r.vs_imf[1]) + [
        k("Peso por dólar", f"{e.fx_usd:.2f}", f"FIX · {_p(e.fx_yoy)} anual · real vs 10a {_p(e.real_fx_gap)} "
          f"(BIS {e.reer_date}, llevado a hoy con el FIX)"),
        k("Carry vs EE.UU.", _p(e.carry_vs_us), f"real {_p(e.real_carry_vs_us)}",
          "good" if e.real_carry_vs_us >= 0.01 else "bad")]
    return {
        "Mundo": [k("Ciclo global", w.cycle, f"{_p(w.g20_breadth, 0)} del G20 acelera",
                    "good" if w.g20_breadth >= 0.6 else "bad" if w.g20_breadth <= 0.4 else "neutral"),
                  k("Crecimiento G20", _p(w.g20_growth_median), f"mediana FMI {w.year}"),
                  k("VIX", f"{w.vix:.1f}", "volatilidad implícita", "bad" if w.vix >= 25 else "neutral"),
                  k("Dólar amplio", _p(w.dollar_yoy), "cambio anual"),
                  k("Brent", _p(w.brent_yoy), "cambio anual", "bad" if w.brent_yoy > 0.25 else "neutral"),
                  k("Cobre", _p(w.copper_yoy), "cambio anual", "good" if w.copper_yoy > 0 else "bad")],
        "EE.UU.": country(r.us, r.vs_imf[0]) + [
            k("Inflación esperada 10a", _p(r.us.breakeven_10y), "breakeven de mercado"),
            k("Spread Baa", _p(r.us.credit_spread), "riesgo de crédito",
              "bad" if r.us.credit_spread >= 0.03 else "good"),
            k("Prob. recesión 12m", f"{m.recession_prob * 100:.0f}%", f"curva 3m10y {m.us_3m10y:+.2f} pp",
              "bad" if m.recession_prob >= 0.3 else "good")],
        "México": mx,
    }


def _at_horizon(value: float, start: pd.Timestamp, months: int) -> pd.Series:
    """A single outside number reached *months* after the last print."""
    return pd.Series([value], index=[start + pd.DateOffset(months=months)])


def _along(points: pd.Series, now: float, now_date: pd.Timestamp, index: pd.DatetimeIndex) -> pd.Series:
    """An outside path on the forecast dates: linear in time from today's value through its points, flat after the last."""
    p = pd.concat([pd.Series([now], index=[now_date]), points[points.index > now_date]]).sort_index()
    x = lambda ix: (pd.DatetimeIndex(ix) - now_date).days.to_numpy(float)
    return pd.Series(np.interp(x(index), x(p.index), p.to_numpy(float)), index=index)


def _chart(title, unit, hist, fc, imf, extra, anchor_label=None, outside_label=None) -> dict:
    """Lines carry a role, not a color: the page maps roles to its palette so every chart reads the same way."""
    lines = [{"label": "Histórico", "role": "hist", "points": _pts(hist)}]
    for i, (label, ser) in enumerate(extra):
        lines.append({"label": label, "role": f"extra{i + 1}", "points": _pts(ser)})
    start = _pts(hist.iloc[-1:])  # every forecast line starts at the last print, so there is no gap
    lines += [
        {"label": "_lo", "role": "band", "points": start + _pts(fc["lo"])},
        {"label": "Banda 90%", "role": "band", "points": start + _pts(fc["hi"]), "fill": True},
        {"label": "Reversión a la media (AR)", "role": "ar", "points": start + _pts(fc["ar1"])},
        {"label": "Tendencia (amortiguada)", "role": "drift", "points": start + _pts(fc["drift"])},
        {"label": "Promedio de modelos", "role": "ens", "points": start + _pts(fc["ensemble"])},
    ]
    if "anchor" in fc:
        lines.append({"label": anchor_label, "role": "anchor", "points": start + _pts(fc["anchor"])})
    if "outside" in fc:
        lines.append({"label": outside_label, "role": "outside", "points": start + _pts(fc["outside"])})
    if imf is not None and not imf.empty:
        lines.append({"label": "FMI (promedio anual)", "role": "imf", "points": _pts(imf), "scatter": True})
    return {"title": title, "unit": unit, "lines": lines}


def _markets_payload(m: Markets) -> dict:
    return {"indices": [i.model_dump() for i in m.indices], "ipc_usd": m.ipc_usd.model_dump(),
            "curves": [m.us_curve.model_dump(), m.mx_curve.model_dump()], "spread": m.mx_us_spread,
            "slopes": m.slopes, "real": m.us_real,
            "kpis": [{"label": "Prob. recesión 12m", "value": f"{m.recession_prob * 100:.0f}%", "sub": "probit Fed NY sobre 3m10y",
                      "tone": "bad" if m.recession_prob >= 0.3 else "good"},
                     {"label": "Curva 2s10s EE.UU.", "value": f"{m.us_2s10s:+.2f} pp", "sub": f"3m10y {m.us_3m10y:+.2f} pp",
                      "tone": "bad" if m.us_2s10s < 0 else "neutral"},
                     {"label": "Tasa real 10a", "value": f"{m.us_real['10y']:.2f}%", "sub": "TIPS, EE.UU.",
                      "tone": "bad" if m.us_real["10y"] > 2 else "neutral"},
                     {"label": "Mercado vs Fed", "value": f"{m.us_policy_gap:+.2f} pp", "sub": "bono 2a menos tasa Fed"},
                     {"label": "Spread MX–EE.UU. 10a", "value": f"{m.mx_spread_10y:.2f} pp",
                      "sub": f"nominal · real (Udibono − TIPS) {m.mx_real_spread_10y:.2f} pp" if m.mx_real_spread_10y is not None else "nominal"},
                     {"label": "Curva México", "value": f"{m.mx_28d10y:+.2f} pp", "sub": "bono 10a menos CETES 28d",
                      "tone": "bad" if m.mx_28d10y < 0 else "neutral"}]}


def _dia(d: pd.Timestamp) -> str:
    return f"{d.day} {'ene feb mar abr may jun jul ago sep oct nov dic'.split()[d.month - 1]}"


def _rate_flags(x: RatesOutlook) -> list[str]:
    nxt = x.fed[0]
    for p, word in ((nxt["p_hike"], "alza"), (nxt["p_cut"], "recorte")):
        if p >= 0.6:
            return [f"el mercado da {p:.0%} de probabilidad de {word} en la reunión de la Fed del {nxt['date']:%d-%m-%Y}"]
    return []


def _scenarios(h: dict, now: float, base: float) -> list[dict]:
    """Cut / hold / hike at 12 months from the option-implied normal distribution; cost of equity moves with half
    the surprise in the policy rate. shortcut: 0.5 pass-through from policy rate to the 10y, fit it from data later."""
    mu, sd = h["mean"], max(h["sigma"], 1e-6)
    cdf = lambda x: 0.5 * (1 + math.erf((x - mu) / (sd * math.sqrt(2))))
    pdf = lambda x: math.exp(-((x - mu) / sd) ** 2 / 2) / (sd * math.sqrt(2 * math.pi))
    lo, hi = now - 0.125, now + 0.125
    p = {"cut": cdf(lo), "hold": cdf(hi) - cdf(lo), "hike": 1 - cdf(hi)}
    mean = {"cut": mu - sd * sd * pdf(lo) / p["cut"] if p["cut"] > 1e-9 else lo,
            "hold": now, "hike": mu + sd * sd * pdf(hi) / p["hike"] if p["hike"] > 1e-9 else hi}
    return [{"scenario": k, "prob": p[k], "rate": mean[k], "coe": base + 0.5 * (mean[k] - mu) / 100} for k in ("cut", "hold", "hike")]


def _rates_payload(x: RatesOutlook, r: MacroReport) -> dict:
    a_us, a_mx = r.assumptions
    row = lambda m: {"date": m["date"].strftime("%Y-%m-%d"), "expected": m["expected"], "change": m["change"],
                     "p_cut": m["p_cut"], "p_hold": m["p_hold"], "p_hike": m["p_hike"], "cum": {str(k): v for k, v in m["cum"].items()}}
    def horizon(c, h, now):
        v = x.horizons[c][h]
        b = v["buckets"]
        return {"date": {"3m": "3 meses", "6m": "6 meses", "12m": "12 meses"}[h], "expected": v["mean"], "change": v["mean"] - now,
                "p_cut": b[-2] + b[-1], "p_hold": b[0], "p_hike": b[1] + b[2], "cum": {str(k): p for k, p in b.items()}, "horizon": True}
    hz = lambda c, now: [horizon(c, h, now) for h in ("3m", "6m", "12m")]
    return {
        "fed_current": x.fed_current, "fed": [row(m) for m in x.fed[:2]] + hz("US", x.fed_current), "mx_current": x.mx_current,
        "mx": [row(m) for m in x.mx_meetings] + hz("MX", x.mx_current), "mx_premium": x.mx_premium, "sofr": x.sofr_check,
        "horizons": {c: {h: {"mean": v["mean"], "sigma": v["sigma"], "buckets": {str(k): b for k, b in v["buckets"].items()}}
                         for h, v in hs.items()} for c, hs in x.horizons.items()},
        "move": x.move, "vix": x.vix, "skew": x.spy_skew, "p_down10": x.p_spx_down10, "usdmxn_vol": x.usdmxn_vol,
        "scales": {"front": x.front_vol_scale, "mx": x.mx_vol_scale},
        "scenarios": {"US": _scenarios(x.horizons["US"]["12m"], x.fed_current, a_us.cost_of_equity()),
                      "MX": _scenarios(x.horizons["MX"]["12m"], x.mx_current, a_mx.cost_of_equity())},
    }


def _summary(r: MacroReport, m: Markets, n: dict[str, Neutral], x: RatesOutlook) -> list[dict]:
    by = {i.name: i for i in m.indices}
    tone = lambda x: "warn" if x.stance != "cerca de neutral" else "good"
    return [
        {"label": "Prob. recesión EE.UU.", "value": f"{m.recession_prob * 100:.0f}%", "sub": f"curva 3m10y {m.us_3m10y:+.2f} pp",
         "tone": "bad" if m.recession_prob >= 0.3 else "good"},
        {"label": "Fed vs neutral", "value": f"{n['US'].gap:+.2f} pp", "sub": f"postura {n['US'].stance}", "tone": tone(n["US"])},
        {"label": "Banxico vs neutral", "value": f"{n['MX'].gap:+.2f} pp", "sub": f"postura {n['MX'].stance}", "tone": tone(n["MX"])},
        {"label": f"Fed {_dia(x.fed[0]['date'])}: alza", "value": f"{x.fed[0]['p_hike'] * 100:.0f}%",
         "sub": f"mantener {x.fed[0]['p_hold'] * 100:.0f}% · recorte {x.fed[0]['p_cut'] * 100:.0f}% (futuros)"},
        {"label": f"Banxico {_dia(x.mx_meetings[0]['date'])}: mantener" if x.mx_meetings else "Banxico",
         "value": f"{x.mx_meetings[0]['p_hold'] * 100:.0f}%" if x.mx_meetings else "—",
         "sub": (f"recorte {x.mx_meetings[0]['p_cut'] * 100:.0f}% · alza {x.mx_meetings[0]['p_hike'] * 100:.0f}% (curva de Cetes)"
                 if x.mx_meetings else "sin reunión con fecha confirmada")},
        {"label": "Spread real MX–EE.UU. 10a", "value": f"{m.mx_real_spread_10y:.2f} pp" if m.mx_real_spread_10y is not None else "—",
         "sub": f"Udibono − TIPS; nominal {m.mx_spread_10y:.2f} pp · riesgo país usado {r.assumptions[1].country_risk_premium * 100:.2f} pp"},
        {"label": "S&P 500 en el año", "value": f"{by['S&P 500'].ytd * 100:+.1f}%", "sub": f"12m {by['S&P 500'].r1y * 100:+.1f}%"},
        {"label": "IPC en el año", "value": f"{by['IPC México'].ytd * 100:+.1f}%", "sub": f"en dólares {m.ipc_usd.ytd * 100:+.1f}%"},
    ]


def _neutral_rows(n: dict[str, Neutral]) -> list[dict]:
    return [{"country": "EE.UU." if c == "US" else "México", "rstar": x.rstar, "growth": x.trend_growth, "avg_real": x.avg_real_rate,
             "external": x.external, "external_label": x.external_label, "target": x.target, "nominal": x.nominal,
             "policy": x.policy, "real_policy": x.real_policy, "gap": x.gap, "stance": x.stance} for c, x in n.items()]


def _economy_payload(e: Economy) -> dict:
    k = lambda label, value, sub, tone="neutral": {"label": label, "value": value, "sub": sub, "tone": tone}
    imf = e.imf
    return {
        "us": [k("Balanza comercial 12m", f"{e.us_trade_12m:,.0f} mmd", "bienes y servicios, miles de millones USD", "bad" if e.us_trade_12m < 0 else "good"),
               k("Cuenta corriente", f"{imf['BCA_NGDPD']['EE.UU.']:.1f}%", f"del PIB, FMI {e.year}"),
               k("Balance fiscal", f"{imf['GGXCNL_NGDP']['EE.UU.']:.1f}%", f"del PIB, FMI {e.year}", "bad" if imf['GGXCNL_NGDP']['EE.UU.'] < -5 else "neutral"),
               k("Deuda pública", f"{imf['GGXWDG_NGDP']['EE.UU.']:.0f}%", "del PIB, bruta"),
               k("Producción industrial", f"{e.us_ip_yoy * 100:+.1f}%", "anual"),
               k("Ventas minoristas", f"{e.us_retail_yoy * 100:+.1f}%", "anual, nominal"),
               k("Empleo", f"{e.us_payrolls_3m:+,.0f}k", "plazas al mes, promedio 3m", "bad" if e.us_payrolls_3m < 0 else "neutral"),
               k("Confianza consumidor", f"{e.us_sentiment:.1f}", "U. de Michigan")],
        "mx": [k("Balanza de mercancías 4T", f"{e.mx_goods_4q:+,.1f} mmd", "miles de millones USD", "good" if e.mx_goods_4q >= 0 else "bad"),
               k("Cuenta corriente", f"{imf['BCA_NGDPD']['México']:.1f}%", f"del PIB, FMI {e.year}"),
               k("Balance fiscal", f"{imf['GGXCNL_NGDP']['México']:.1f}%", f"del PIB, FMI {e.year}", "bad" if imf['GGXCNL_NGDP']['México'] < -3 else "neutral"),
               k("Deuda pública", f"{imf['GGXWDG_NGDP']['México']:.0f}%", "del PIB, bruta"),
               k("Remesas 12m", f"{e.mx_remit_12m:,.1f} mmd", f"{e.mx_remit_yoy * 100:+.1f}% anual"),
               k("Reservas", f"{e.mx_reserves:,.1f} mmd", f"{e.mx_reserves_yoy * 100:+.1f}% anual"),
               k("IGAE", f"{e.mx_igae_yoy * 100:+.1f}%", "actividad, anual", "bad" if e.mx_igae_yoy < 0 else "neutral")],
        "risk": [k("Spread corporativo EM", f"{e.em_oas:.2f} pp", f"{e.em_oas_1y:+.2f} pp en un año, ICE BofA"),
                 k("Spread high yield EE.UU.", f"{e.hy_oas:.2f} pp", f"{e.hy_oas_1y:+.2f} pp en un año", "bad" if e.hy_oas >= 5 else "good")],
        "imf": {"year": e.year, "rows": [{"ind": IMF_LABEL[i], **v} for i, v in imf.items()]},
    }


IMF_LABEL = {"BCA_NGDPD": "Cuenta corriente", "GGXCNL_NGDP": "Balance fiscal", "GGXWDG_NGDP": "Deuda bruta"}


BUCKETS = [("-2", "Recorte de 50 pb o más", "s1"), ("-1", "Recorte de 25 pb", "s3"), ("0", "Sin cambio", "muted"),
           ("1", "Alza de 25 pb", "s4"), ("2", "Alza de 50 pb o más", "s2")]


def _stack(labels: list[str], rows: list[dict]) -> dict:
    """Stacked probability bars: one bar per label, one segment per cumulative 25 bp bucket vs today."""
    return {"kind": "cat", "unit": "%", "stacked": True, "labels": labels,
            "series": [{"label": name, "color": col, "values": [round(r[k] * 100, 1) for r in rows]} for k, name, col in BUCKETS]}


def _specs(m: Markets, n: dict[str, Neutral], e: Economy, x: RatesOutlook) -> dict[str, dict]:
    """Charts that are not one forecast series: curves by tenor, bars by category, several series over time."""
    grid = np.geomspace(1 / 365, 30, 80)
    def fitted(curve, key, label, color, dash=()):
        f, yrs = curve.fits[key], curve.years_by.get(key, curve.years)
        if f is None:
            return []
        ts = np.array(sorted({min(yrs), max(yrs), *(t for t in grid if min(yrs) < t < max(yrs))}))  # no extrapolation
        return [{"label": label, "color": color, "dash": list(dash),
                 "points": [[round(float(t), 4), round(float(v), 3)] for t, v in zip(ts, f(ts))]}]
    def nodes(curve, key, label, color, real=False):
        yrs = curve.years_by.get(key, curve.years)
        name = lambda k, y: (NODE_NAMES.get(("U" if real else "") + k, k) if curve.country == "MX" else k) + f" · {y:.1f} años"
        obs = [(name(k, y), y, v) for k, y, v in zip(curve.tenors, yrs, getattr(curve, key)) if v is not None]
        return {"label": label, "color": color, "dots": True, "tenors": [k for k, _, _ in obs], "points": [[y, v] for _, y, v in obs]}
    curve = lambda c: {"kind": "tenor", "unit": "%", "series": fitted(c, "now", "Hoy (curva ajustada)", "s1")
                       + fitted(c, "m3", "Hace 3 meses", "s3", [5, 4]) + fitted(c, "y1", "Hace un año", "muted", [2, 3])
                       + [nodes(c, "now", "Hoy (nodos observados)", "s1")]}
    bars = lambda pts, label, fmt: {"kind": "cat", "unit": " mmd", "labels": [_ym(t, fmt) for t, _ in pts], "series": [{"label": label, "color": "s2", "values": [v for _, v in pts]}]}
    flat = lambda key: [[t, v] for t, v in e.charts[key]]
    spec = {
        "curve_US": curve(m.us_curve), "curve_MX": curve(m.mx_curve),
        "real_curves": {"kind": "tenor", "unit": "%", "series": fitted(m.us_real_curve, "now", "EE.UU. (TIPS)", "s1")
                        + fitted(m.mx_real_curve, "now", "México (Udibonos)", "s2")
                        + [nodes(m.us_real_curve, "now", "Nodos EE.UU.", "s1"), nodes(m.mx_real_curve, "now", "Nodos México", "s2", real=True)]},
        "mx10_daily": {"kind": "time", "daily": True, "unit": "%", "series": [
            {"label": "Bono M 7–10 años (vector de precios)", "color": "s2", "points": m.mx_10y_daily},
            {"label": "Treasury 10 años", "color": "s1", "points": m.us10_daily}]},
        "spread": {"kind": "cat", "unit": " pp", "labels": [k.replace("y", "a") for k in m.mx_us_spread],
                   "series": [{"label": "México menos EE.UU.", "color": "s2", "values": list(m.mx_us_spread.values())}]},
        "slopes": {"kind": "time", "daily": True, "unit": " pp", "ref": 0, "series": [{"label": "10a – 2a", "color": "s1", "points": m.slopes["2s10s"]},
                                                                        {"label": "10a – 3m", "color": "s2", "points": m.slopes["3m10y"]}]},
        "prob": {"kind": "time", "daily": True, "unit": "%", "ref": 30, "series": [{"label": "Probabilidad de recesión", "color": "s5", "points": m.slopes["prob"]}]},
        "us_trade": bars(flat("us_trade")[-36:], "Balanza comercial EE.UU.", "%b %y"),
        "mx_goods": bars(flat("mx_goods")[-20:], "Balanza de mercancías México", "q"),
        "mx_remit": {"kind": "time", "unit": " mmd", "series": [{"label": "Remesas, suma 12 meses", "color": "s1", "points": flat("mx_remit")}]},
        "mx_reserves": {"kind": "time", "unit": " mmd", "series": [{"label": "Reservas internacionales", "color": "s1", "points": flat("mx_reserves")}]},
        "credit": {"kind": "time", "daily": True, "unit": " pp", "series": [{"label": "Corporativos emergentes (OAS)", "color": "s1", "points": flat("em_oas")},
                                                              {"label": "High yield EE.UU. (OAS)", "color": "s2", "points": flat("hy_oas")}]},
    }
    near = x.fed[:2]  # meeting by meeting only for the next two; horizons from the option-implied distribution
    spec["fed_probs"] = _stack([_dia(r['date']) for r in near] + ["3 meses", "6 meses", "12 meses"],
                               [{str(k): v for k, v in r["cum"].items()} for r in near]
                               + [{str(k): v for k, v in x.horizons["US"][h]["buckets"].items()} for h in ("3m", "6m", "12m")])
    mx_rows = [{str(k): v for k, v in r["cum"].items()} for r in x.mx_meetings]
    spec["mx_probs"] = _stack([_dia(r['date']) for r in x.mx_meetings] + ["3 meses", "6 meses", "12 meses"],
                              mx_rows + [{str(k): v for k, v in x.horizons["MX"][h]["buckets"].items()} for h in ("3m", "6m", "12m")])
    spec["us_dist"] = _stack(["3 meses", "6 meses", "12 meses"], [{str(k): v for k, v in x.horizons["US"][h]["buckets"].items()} for h in ("3m", "6m", "12m")])
    spec["vix_term"] = {"kind": "cat", "unit": "", "labels": ["9 días", "1 mes", "3 meses", "6 meses"],
                        "series": [{"label": "VIX", "color": "s1", "values": [round(x.vix[k], 2) for k in ("vix9d", "vix", "vix3m", "vix6m")]}]}
    for c, x in n.items():
        span = [x.history[0][0], x.history[-1][0]]
        spec[f"rstar_{c}"] = {"kind": "time", "unit": "%", "series": [
            {"label": "Tasa real ex ante", "color": "s1", "points": x.history},
            {"label": "r* nuestro", "color": "s3", "dash": [5, 4], "points": [[t, round(x.rstar, 3)] for t in span]},
            {"label": x.external_label, "color": "s4", "dash": [2, 3], "points": [[t, round(x.external, 3)] for t in span]}]}
    return spec


# What each Mexican node is: price-vector bucket or money-market rate (U = Udibonos, real).
NODE_NAMES = {"1d": "TIIE de fondeo", "28d": "Cetes 28d", "91d": "Cetes 91d", "182d": "Cetes 182d", "364d": "Cetes 364d",
              "2y": "Cetes 2 años", "3y": "Bono M 0–3a", "5y": "Bono M 3–5a", "7y": "Bono M 5–7a", "10y": "Bono M 7–10a",
              "20y": "Bono M 10–20a", "30y": "Bono M 20–30a", "U3y": "Udibono 3a", "U10y": "Udibono 10a",
              "U20y": "Udibono 20a", "U30y": "Udibono 30a"}


def _ym(ms: int, fmt: str) -> str:
    t = pd.Timestamp(ms, unit="ms")
    return f"{t.year}T{(t.month - 1) // 3 + 1}" if fmt == "q" else t.strftime("%m/%y")


def _imf_points(df: pd.DataFrame, iso: str, year: int) -> pd.Series:
    """IMF annual figures for this year and the next two, plotted mid-year."""
    if iso not in df.columns:
        return pd.Series(dtype=float)
    vals = df.loc[year:year + 2, iso].dropna()
    return pd.Series(vals.values, index=[pd.Timestamp(y, 7, 1) for y in vals.index])


def _yoy_pct(series: pd.Series) -> pd.Series:
    """% change vs the same date a year earlier; by date, not position, so a missing print (FRED has no Oct 2025 CPI) leaves a gap instead of a 13-month change."""
    return (series / series.shift(freq=pd.DateOffset(years=1)) - 1) * 100


def _recent(series: pd.Series, years: int = HISTORY_YEARS) -> pd.Series:
    series = series.dropna()
    return series[series.index > series.index[-1] - pd.DateOffset(years=years)]


def _pts(series: pd.Series) -> list[list]:
    return [[int(t.timestamp() * 1000), round(float(v), 3)] for t, v in series.items()]


def _p(v: float, decimals: int = 2) -> str:
    return f"{v * 100:.{decimals}f}%"


# ---------------------------------------------------------------------------
# What changed: each KPI that maps onto a series carries its change vs the previous reading and vs a month ago
# ---------------------------------------------------------------------------

def _delta(series: pd.Series, unit: str) -> dict:
    s = series.dropna()
    if len(s) < 3:
        return {}
    prior = s[: s.index[-1] - pd.Timedelta(days=30)]
    step = s.diff().dropna().iloc[-260:].std()
    d1 = float(s.iloc[-1] - s.iloc[-2])
    return {"d1": d1, "d30": float(s.iloc[-1] - prior.iloc[-1]) if len(prior) else None,
            "z": d1 / step if step and step > 1e-9 else 0.0, "unit": unit}


def _with_deltas(kpis: dict[str, list[dict]], s: dict[str, dict]) -> dict[str, list[dict]]:
    """shortcut: only KPIs that are a plain series (rates, unemployment, growth, inflation, FX, VIX) get deltas;
    ratio-style ones (carry, gaps, breadth) stay without, extend the map when one needs them."""
    country = lambda d: {"PIB real anual": _yoy_pct(d["gdp"].resample("QS").last().dropna()), "Inflación": _yoy_pct(d["cpi"]),
                         "Tasa de política": d["policy_rate"], "Bono 10 años": d["rate_10y"], "Desempleo": d["unemployment"]}
    by_area = {"EE.UU.": country(s["US"]), "México": {**country(s["MX"]), "Peso por dólar": s["MX"]["fx_usd"]},
               "Mundo": {"VIX": s["GLOBAL"]["vix"]}}
    for area, rows in kpis.items():
        for k in rows:
            ser = by_area.get(area, {}).get(k["label"])
            if ser is not None:
                k.update(_delta(ser, "" if k["label"] in ("Peso por dólar", "VIX") else " pp"))
    return kpis


def _changes(kpis: dict[str, list[dict]]) -> list[dict]:
    """The KPIs that moved more than one standard deviation of their own changes, biggest first."""
    rows = [{"area": area, "label": k["label"], "value": k["value"], "d1": k["d1"], "z": k["z"], "unit": k["unit"]}
            for area, ks in kpis.items() for k in ks if abs(k.get("z", 0)) >= 1]
    return sorted(rows, key=lambda r: -abs(r["z"]))[:8]


def _calendar(as_of: str) -> list[dict]:
    from macro.policy import BANXICO, FOMC
    start = pd.Timestamp(as_of)
    events = [(d, "Fed") for d in FOMC] + [(d, "Banxico") for d in BANXICO]
    return [{"date": d.strftime("%Y-%m-%d"), "event": "Decisión de política monetaria", "where": who}
            for d, who in sorted(events) if start <= d <= start + pd.Timedelta(days=30)]


ANSWER_AREAS = [("Macro", "mundo", "macro/mundo"), ("Tasas", "curvas", "tasas/curvas"), ("Tipo de cambio", "nivel", "fx/nivel"),
                ("Mercados", "indices", "mercados/indices"), ("Empresas", "supuestos", "empresas/supuestos")]


def _answers(reasons: dict[str, list[str]]) -> tuple[dict[str, str], list[dict]]:
    """One-sentence answer per view = the first reason of the matching group; the list is what Hoy shows per area."""
    first = lambda key, pick=None: next((r for r in reasons.get(key, []) if pick is None or pick in r.lower()), None)
    by_view = {"mundo": first("Mundo"), "eeuu": first("EE.UU."), "mexico": first("México"), "comercio": first("Comercio"),
               "curvas": first("Curvas"), "politica": first("Probabilidades"), "riesgo-pais": first("Riesgo"),
               "indices": first("Mercados"), "supuestos": first("Supuestos"), "nivel": first("México", "peso")}
    by_view = {k: v for k, v in by_view.items() if v}
    return by_view, [{"name": n, "text": by_view[v], "href": h} for n, v, h in ANSWER_AREAS if v in by_view]
