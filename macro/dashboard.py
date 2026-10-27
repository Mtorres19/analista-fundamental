"""One self-contained HTML page: every reading of the report, its history, the reasons behind it and forecasts.

The reasons are rules over our own numbers (what each indicator implies given the others), not a narrative
pulled from outside. Forecasts come from macro.forecast plus the IMF and market expectations for comparison.
"""

from __future__ import annotations

import json
from datetime import datetime
from functools import cache

import numpy as np
import pandas as pd

from macro import sources
from macro.assumptions import DEFAULT_ERP
from macro.forecast import forecast
from macro.economy import Economy, build_economy
from macro.economy import reasons as economy_reasons
from macro.markets import Markets, build_markets
from macro.markets import reasons as market_reasons
from macro.neutral import Neutral, build_neutral
from macro.report import MacroReport, WeoFetch, build_report
from macro.snapshot import CountrySnapshot, _monthly

HISTORY_YEARS = 10
REGIME_ES = {"goldilocks": "goldilocks", "reflation": "reflación", "stagflation": "estanflación", "slowdown": "desaceleración"}
REGIME_TEXT = {
    "goldilocks": "crece arriba de su tendencia con inflación bajando: el mejor cuadrante para acciones",
    "reflation": "crece arriba de su tendencia con inflación subiendo: favorece cíclicas y materias primas, presiona tasas",
    "stagflation": "crece debajo de su tendencia con inflación subiendo: el cuadrante más difícil para acciones y bonos",
    "slowdown": "crece debajo de su tendencia con inflación bajando: abre espacio a recortes de tasa, favorece defensivas y bonos",
}


def build_dashboard(as_of: str, erp: float = DEFAULT_ERP, fetch: sources.Fetch = sources.fetch,
                    weo_fetch: WeoFetch = sources.imf_weo) -> str:
    fetch, weo_fetch = cache(fetch), cache(weo_fetch)  # the report and the charts read the same series once
    r = build_report(as_of, erp=erp, fetch=fetch, weo_fetch=weo_fetch)
    m = build_markets(r, fetch)
    n = build_neutral(r, fetch)
    s = {reg: sources.load(reg, as_of, fetch) for reg in sources.SERIES}
    weo = {ind: weo_fetch(ind) for ind in sources.IMF_INDICATORS}
    e = build_economy(r, weo, fetch)
    year = int(as_of[:4])

    charts, forecasts = {}, []

    def add(key, title, unit, hist, freq="MS", imf=None, extra=(), market=None, anchor=None, chart=True, daily=None):
        """anchor: (label, index -> Series), a path the macro side implies (neutral rate, cost of equity).
        daily: the same series day by day, drawn instead of the monthly history (models still fit monthly)."""
        fc = forecast(hist, 4 if freq == "QS" else 12, freq)
        if anchor is not None:
            fc["anchor"] = anchor[1](fc.index)
        if chart:
            charts[key] = _chart(title, unit, hist if daily is None else _recent(daily.dropna(), 5), fc, imf, extra,
                                 anchor[0] if anchor else None)
            charts[key]["daily"] = daily is not None
        end = fc.iloc[-1]
        forecasts.append({"name": title, "unit": unit, "now": float(hist.iloc[-1]), "drift": end.drift,
                          "ar1": end.ar1, "lo": end.lo, "hi": end.hi, "ensemble": end.ensemble,
                          "imf": None if imf is None or imf.empty else float(imf.iloc[-1]),
                          "market": market, "anchor": float(end.anchor) if anchor is not None else None,
                          "horizon": fc.index[-1].strftime("%Y-%m")})

    for c, iso, name in (("US", "USA", "EE.UU."), ("MX", "MEX", "México")):
        d = s[c]
        imf_g = _imf_points(weo["NGDP_RPCH"], iso, year)
        imf_i = _imf_points(weo["PCPIPCH"], iso, year)
        be = _recent(_monthly(d["breakeven_10y"])) if "breakeven_10y" in d else None
        add(f"{c}_infl", f"Inflación {name}", "%", _recent(_yoy_pct(_monthly(d["cpi"]))),
            imf=imf_i, extra=[("Inflación esperada 10a (mercado)", be)] if be is not None else (),
            market=float(be.iloc[-1]) if be is not None else None)
        extra = [("Bono 10 años", _recent(_monthly(d["rate_10y"])))]
        if c == "MX":
            extra.append(("Tasa Fed (EE.UU.)", _recent(_monthly(s["US"]["policy_rate"]))))
        # Market-implied path: where the 2y Treasury / 1y CETES sit against today's policy rate.
        implied = m.us_curve.at("2y") if c == "US" else m.mx_curve.at("364d")
        add(f"{c}_rate", f"Tasa de política {name}", "%", _recent(_monthly(d["policy_rate"])), extra=extra, market=implied,
            anchor=("Convergencia a la tasa neutral", n[c].path))
        add(f"{c}_unemp", f"Desempleo {name}", "%", _recent(_monthly(d["unemployment"])))
        gdp = d["gdp"].resample("QS").last().dropna()
        add(f"{c}_gdp", f"PIB real anual {name}", "%", _recent(_yoy_pct(gdp)), "QS", imf=imf_g)
    g, dly = s["GLOBAL"], s["DAILY"]
    for key, title, ser in (("MX_fx", "Pesos por dólar", s["MX"]["fx_usd"]), ("brent", "Petróleo Brent (USD/barril)", g["brent"]),
                            ("copper", "Cobre (USD/libra, futuro COMEX)", dly["copper"]),
                            ("dollar", "Dólar amplio (índice)", g["dollar"]), ("vix", "VIX (miedo del mercado)", g["vix"])):
        add(key, title, "", _recent(_monthly(ser)), daily=ser)
    for ix in m.indices:
        last = float(s["INDICES"][ix.name].iloc[-1])
        # The macro side's required return, compounded monthly from the last close.
        required = lambda idx, last=last, coe=ix.cost_of_equity: last * (1 + coe) ** (pd.Series(range(1, len(idx) + 1), index=idx) / 12)
        add("ix_" + ix.name, ix.name, "", _recent(_monthly(s["INDICES"][ix.name])),
            anchor=("Rentabilidad exigida (costo de capital)", required), daily=s["INDICES"][ix.name])

    growth = sorted(r.world.growth.items(), key=lambda kv: -kv[1])
    data = {
        "as_of": r.as_of, "generated": datetime.now().strftime("%Y-%m-%d %H:%M"),
        "headline": {"Mundo": r.world.cycle, "EE.UU.": r.us.regime, "México": r.mx.regime},
        "regimes": [{"name": n, "regime": c.regime, "x": round((c.gdp_yoy - c.gdp_trend) * 100, 2),
                     "y": round((c.inflation_yoy - c.inflation_yoy_6m_ago) * 100, 2)}
                    for n, c in (("EE.UU.", r.us), ("México", r.mx))],
        "kpis": _kpis(r, m, n), "reasons": {**reasons(r, forecasts, m, n), **market_reasons(m, r),
                                             **economy_reasons(e, m, r)},
        "markets": _markets_payload(m), "charts": charts, "forecasts": forecasts,
        "specs": _specs(m, n, e), "neutral": _neutral_rows(n), "economy": _economy_payload(e),
        "summary": _summary(r, m, n),
        "g20": {"labels": [k for k, _ in growth], "values": [round(v * 100, 2) for _, v in growth],
                "year": r.world.year},
        "assumptions": [{"market": a.market, "currency": a.currency, "rf": a.risk_free_usd,
                         "erp": a.equity_risk_premium, "crp": a.country_risk_premium,
                         "infl": a.expected_inflation, "g": a.terminal_growth, "coe": a.cost_of_equity()}
                        for a in r.assumptions],
        "flags": {"Mundo": r.world.flags + m.flags["Mundo"] + e.flags["Mundo"],
                  "EE.UU.": r.us.flags + r.vs_imf[0].flags + m.flags["EE.UU."] + e.flags["EE.UU."],
                  "México": r.mx.flags + r.vs_imf[1].flags + r.mx_extras.flags + m.flags["México"] + e.flags["México"]},
    }
    payload = json.dumps(data, ensure_ascii=False, default=float).replace("</", "<\\/")
    return HTML.replace("__DATA__", payload).replace("__ASOF__", r.as_of)


# ---------------------------------------------------------------------------
# Reasons: why each reading is where it is, from the other readings
# ---------------------------------------------------------------------------

def reasons(r: MacroReport, forecasts: list[dict], m: Markets, n: dict[str, Neutral]) -> dict[str, list[str]]:
    fc = {f["name"]: f for f in forecasts}
    w = r.world
    world = [f"El ciclo global es de {w.cycle}: solo el {_p(w.g20_breadth, 0)} del G20 crece más rápido que el año "
             f"pasado según el FMI, con una mediana de {_p(w.g20_growth_median)}."]
    world.append(f"El petróleo {'sube' if w.brent_yoy > 0 else 'baja'} {_p(abs(w.brent_yoy))} en un año: "
                 + ("eso empuja la inflación de energía y transporte en todo el mundo y limita los recortes de tasa."
                    if w.brent_yoy > 0.10 else "eso le quita presión a la inflación."
                    if w.brent_yoy < -0.10 else "su efecto sobre la inflación es moderado."))
    world.append(f"El cobre {'sube' if w.copper_yoy > 0 else 'baja'} {_p(abs(w.copper_yoy))} anual: "
                 + ("demanda industrial y de electrificación fuerte (o restricción de oferta), buena señal para minería."
                    if w.copper_yoy > 0.05 else "demanda industrial débil." if w.copper_yoy < -0.05
                    else "demanda industrial estable."))
    world.append(f"El dólar amplio cambia {_p(w.dollar_yoy)} en un año: "
                 + ("un dólar más fuerte aprieta a emergentes y a quien debe en dólares." if w.dollar_yoy > 0.03
                    else "un dólar más débil alivia a emergentes como México." if w.dollar_yoy < -0.03
                    else "sin presión relevante sobre emergentes."))
    world.append(f"VIX en {w.vix:.1f}: " + ("el mercado está nervioso y paga caro por protegerse." if w.vix >= 25
                                            else "nerviosismo moderado, arriba de lo normal en calma." if w.vix >= 18
                                            else "mercado tranquilo, apetito por riesgo."))
    out = {"Mundo": world}
    for snap, cmp, name in ((r.us, r.vs_imf[0], "EE.UU."), (r.mx, r.vs_imf[1], "México")):
        out[name] = _country_reasons(snap, cmp, fc, name)
    for c, name in (("US", "EE.UU."), ("MX", "México")):
        x = n[c]
        out[name].append(f"Tasa neutral: nuestro r* es {x.rstar:.2f}% real (promedio de crecimiento tendencial {x.trend_growth:.2f}% "
                         f"y tasa real ex ante de 10 años {x.avg_real_rate:.2f}%); la referencia externa ({x.external_label}) da "
                         f"{x.external:.2f}%. Con la meta de {x.target:.0f}%, la neutral nominal es {x.nominal:.2f}% y la tasa está "
                         f"en {x.policy:.2f}%: {x.gap:+.2f} pp, postura {x.stance}. El pronóstico agrega la convergencia a la neutral.")
    out["EE.UU."].append(f"La curva (3m10y en {m.us_3m10y:+.2f} pp) da {m.recession_prob:.0%} de probabilidad de recesión en "
                         f"12 meses, y el bono a 2 años ({m.us_curve.at('2y'):.2f}%) "
                         + ("descuenta recortes de la Fed." if m.us_policy_gap < -0.15 else "descuenta alzas de la Fed."
                            if m.us_policy_gap > 0.15 else "no descuenta cambios grandes en la tasa."))
    e = r.mx_extras
    out["México"] += [
        f"El carry contra EE.UU. es de {_p(e.carry_vs_us)} ({_p(e.real_carry_vs_us)} real): "
        + ("pagar más que la Fed atrae dinero de fuera a pesos y sostiene al peso." if e.real_carry_vs_us > 0.01
           else "el premio por estar en pesos es chico, el peso queda vulnerable a salidas de capital."),
        f"El peso real está {_p(abs(e.real_fx_gap))} {'más fuerte' if e.real_fx_gap < 0 else 'más débil'} que su "
        "promedio de 10 años: " + ("abarata importaciones y ayuda a bajar la inflación, pero resta competitividad "
                                   "a exportadores y al turismo." if e.real_fx_gap < 0
                                   else "encarece importaciones y empuja precios, pero favorece a exportadores."),
    ]
    a_us, a_mx = r.assumptions
    out["Supuestos"] = [
        f"El costo de capital en dólares ({_p(a_us.cost_of_equity())}) sale de la tasa a 10 años de EE.UU. "
        f"({_p(a_us.risk_free_usd)}) más una prima de mercado de {_p(a_us.equity_risk_premium)}.",
        f"En México se suma un riesgo país de {_p(a_mx.country_risk_premium)} (diferencial soberano real ×1.5) y se "
        f"convierte a pesos con la brecha de inflación esperada ({_p(a_mx.expected_inflation)} vs "
        f"{_p(a_us.expected_inflation)}): por eso exige {_p(a_mx.cost_of_equity())}.",
        f"El crecimiento terminal se topa con la tasa a 10 años local: {_p(a_us.terminal_growth)} en EE.UU. y "
        f"{_p(a_mx.terminal_growth)} en México. Si una empresa necesita crecer más que eso para valer su precio, "
        "la valuación es exigente.",
    ]
    return out


def _country_reasons(s: CountrySnapshot, cmp, fc: dict, name: str) -> list[str]:
    up_g, up_i = s.gdp_yoy >= s.gdp_trend, s.inflation_yoy >= s.inflation_yoy_6m_ago
    out = [f"Régimen de {REGIME_ES[s.regime]}: el PIB crece {_p(s.gdp_yoy)} contra una tendencia de {_p(s.gdp_trend)} "
           f"({'arriba' if up_g else 'abajo'}) y la inflación {'subió' if up_i else 'bajó'} de "
           f"{_p(s.inflation_yoy_6m_ago)} a {_p(s.inflation_yoy)} en seis meses. Es decir, "
           f"{REGIME_TEXT[s.regime]}."]
    rr = s.real_policy_rate
    stance = ("restrictiva" if rr > 0.02 else "algo restrictiva" if rr > 0.005 else "neutral" if rr > -0.005
              else "laxa")
    out.append(f"La tasa real de política es {_p(rr)} (tasa {_p(s.policy_rate)} menos inflación): la política "
               f"monetaria es {stance}. " + ("Eso frena crédito y consumo y tiende a bajar la inflación; deja espacio "
                                            "para recortar." if rr > 0.02 else
                                            "Hay poco freno: si la inflación no cede, la tasa podría tener que subir."
                                            if rr < 0.005 else "El banco central está cerca de su punto neutral."))
    out.append(f"La curva (10 años menos tasa de política) es {_p(s.curve)}: "
               + ("invertida, el mercado espera recortes y una economía más débil." if s.curve < 0 else
                  "positiva y amplia: el mercado no anticipa recesión y cobra prima por plazo, o duda de que "
                  "la inflación baje." if s.curve > 0.01 else "plana, el mercado no ve grandes cambios."))
    out.append(f"Desempleo en {_p(s.unemployment)}; la brecha Sahm es {_p(s.sahm_gap)} "
               + ("(activada: el empleo se está deteriorando rápido)." if s.sahm_gap >= 0.005 else
                  "(sin señal de recesión por empleo)."))
    if s.credit_spread is not None:
        out.append(f"El spread de crédito corporativo Baa es {_p(s.credit_spread)}: "
                   + ("estrés, las empresas pagan caro por financiarse." if s.credit_spread >= 0.03 else
                      "crédito abierto, sin estrés financiero."))
    gap_g, gap_i = cmp.gdp_ours - cmp.gdp_imf, cmp.inflation_ours - cmp.inflation_imf
    out.append(f"Contra el FMI: crecimiento {'arriba' if gap_g >= 0 else 'abajo'} por {_p(abs(gap_g))} e inflación "
               f"{'arriba' if gap_i >= 0 else 'abajo'} por {_p(abs(gap_i))} de lo que espera para {cmp.year}.")
    f = fc[f"Inflación {name}"]
    view = (f"Pronóstico de inflación a {f['horizon']}: {f['ensemble']:.2f}% (promedio de modelos; reversión a la "
            f"media {f['ar1']:.2f}%, tendencia {f['drift']:.2f}%)")
    if f["imf"] is not None:
        view += f"; el FMI espera {f['imf']:.2f}% en promedio el próximo año"
    if f["market"] is not None:
        view += f"; el mercado descuenta {f['market']:.2f}% anual a 10 años"
    out.append(view + ".")
    return out


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _kpis(r: MacroReport, m: Markets, n: dict[str, Neutral]) -> dict[str, list[dict]]:
    def k(label, value, sub="", tone="neutral"):
        return {"label": label, "value": value, "sub": sub, "tone": tone}

    def country(s: CountrySnapshot, cmp):
        return [k("Régimen", s.regime, "crecimiento vs tendencia × inflación",
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
        k("Peso por dólar", f"{e.fx_usd:.2f}", f"{_p(e.fx_yoy)} anual · real vs 10a {_p(e.real_fx_gap)}"),
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


def _chart(title, unit, hist, fc, imf, extra, anchor_label=None) -> dict:
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
                     {"label": "Spread MX–EE.UU. 10a", "value": f"{m.mx_spread_10y:.2f} pp", "sub": "bono M menos Treasury"},
                     {"label": "Curva México", "value": f"{m.mx_28d10y:+.2f} pp", "sub": "bono 10a menos CETES 28d",
                      "tone": "bad" if m.mx_28d10y < 0 else "neutral"}]}


def _summary(r: MacroReport, m: Markets, n: dict[str, Neutral]) -> list[dict]:
    by = {i.name: i for i in m.indices}
    tone = lambda x: "warn" if x.stance != "cerca de neutral" else "good"
    return [
        {"label": "Prob. recesión EE.UU.", "value": f"{m.recession_prob * 100:.0f}%", "sub": f"curva 3m10y {m.us_3m10y:+.2f} pp",
         "tone": "bad" if m.recession_prob >= 0.3 else "good"},
        {"label": "Fed vs neutral", "value": f"{n['US'].gap:+.2f} pp", "sub": f"postura {n['US'].stance}", "tone": tone(n["US"])},
        {"label": "Banxico vs neutral", "value": f"{n['MX'].gap:+.2f} pp", "sub": f"postura {n['MX'].stance}", "tone": tone(n["MX"])},
        {"label": "Spread MX–EE.UU. 10a", "value": f"{m.mx_spread_10y:.2f} pp", "sub": "riesgo país de mercado"},
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


def _specs(m: Markets, n: dict[str, Neutral], e: Economy) -> dict[str, dict]:
    """Charts that are not one forecast series: curves by tenor, bars by category, several series over time."""
    grid = np.geomspace(1 / 365, 30, 80)
    def fitted(curve, key, label, color, dash=()):
        f = curve.fits[key]
        return [] if f is None else [{"label": label, "color": color, "dash": list(dash),
                                      "points": [[round(float(t), 4), round(float(v), 3)] for t, v in zip(grid, f(grid))
                                                 if min(curve.years) <= t <= max(curve.years)]}]  # no extrapolation
    def nodes(curve, key, label, color):
        obs = [(k, y, v) for k, y, v in zip(curve.tenors, curve.years, getattr(curve, key)) if v is not None]
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
                        + [nodes(m.us_real_curve, "now", "Nodos EE.UU.", "s1"), nodes(m.mx_real_curve, "now", "Nodos México", "s2")]},
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
    for c, x in n.items():
        span = [x.history[0][0], x.history[-1][0]]
        spec[f"rstar_{c}"] = {"kind": "time", "unit": "%", "series": [
            {"label": "Tasa real ex ante", "color": "s1", "points": x.history},
            {"label": "r* nuestro", "color": "s3", "dash": [5, 4], "points": [[t, round(x.rstar, 3)] for t in span]},
            {"label": x.external_label, "color": "s4", "dash": [2, 3], "points": [[t, round(x.external, 3)] for t in span]}]}
    return spec


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


HTML = """<!doctype html>
<html lang="es">
<head>
<meta charset="utf-8">
<meta name="viewport" content="width=device-width, initial-scale=1, viewport-fit=cover">
<title>Panorama macro</title>
<meta http-equiv="refresh" content="3600">
<meta name="claude:viewport-fit-sides" content="cover">
<link rel="preconnect" href="https://fonts.googleapis.com">
<link rel="preconnect" href="https://fonts.gstatic.com" crossorigin>
<link rel="stylesheet" href="https://fonts.googleapis.com/css2?family=Bricolage+Grotesque:opsz,wght@12..96,400;12..96,600;12..96,800&family=IBM+Plex+Sans:wght@400;500;600&family=IBM+Plex+Mono:wght@400;500&display=swap">
<style>
/* Layout: a trading-desk night view. Hero = the regime map; then one band per economy (tiles, reasons, charts); forecasts as range bars. */
:root {
  color-scheme: dark;
  --page: #0d0d0d; --card: #1a1a19; --card-2: #222220; --ring: rgba(255,255,255,0.08);
  --ink: #f0efec; --ink-2: #c3c2b7; --muted: #898781; --grid: #2c2c2a; --axis: #383835;
  --s1: #3987e5; --s2: #d95926; --s3: #199e70; --s4: #c98500; --s5: #d55181; --s6: #9085e9;
  --good: #0ca30c; --warn: #fab219; --bad: #d03b3b;
  --display: "Bricolage Grotesque", "Avenir Next", system-ui, sans-serif;
  --body: "IBM Plex Sans", system-ui, -apple-system, "Segoe UI", sans-serif;
  --mono: "IBM Plex Mono", ui-monospace, "SF Mono", Menlo, monospace;
  --r: 14px; --ease: cubic-bezier(.2,.8,.2,1);
}
* { box-sizing: border-box; }
html { background: var(--page); scroll-behavior: smooth; }
body { margin: 0; background: var(--page); color: var(--ink); font: 15px/1.55 var(--body); -webkit-font-smoothing: antialiased; }
body::before { content: ""; position: fixed; inset: 0 0 auto; height: env(safe-area-inset-top, 0px); z-index: 10; background: var(--page); }
main { max-width: 1240px; margin: 0 auto; padding-block: 8px 72px;
  padding-left: max(16px, env(safe-area-inset-left, 0px)); padding-right: max(16px, env(safe-area-inset-right, 0px)); }
a { color: inherit; }
:focus-visible { outline: 2px solid var(--s1); outline-offset: 2px; border-radius: 6px; }

/* Hero */
.hero { display: grid; grid-template-columns: minmax(0, 1.15fr) minmax(0, 1fr); gap: 28px; align-items: stretch; }
.eyebrow { font: 500 12px/1 var(--mono); color: var(--muted); letter-spacing: .12em; text-transform: uppercase; }
h1 { font: 800 clamp(34px, 5.2vw, 60px)/1.02 var(--display); letter-spacing: -0.03em; margin: 14px 0 18px; text-wrap: balance; }
h1 .tag { display: inline; color: var(--ink); background-image: linear-gradient(var(--hl), var(--hl)); background-repeat: no-repeat;
  background-size: 100% .14em; background-position: 0 92%; }
.lede { color: var(--ink-2); max-width: 58ch; margin: 0; }
.chips { display: flex; flex-wrap: wrap; gap: 8px; margin-top: 22px; }
.regime-card { flex: 1 1 150px; background: var(--card); border: 1px solid var(--ring); border-radius: var(--r); padding: 14px 16px; min-width: 0; }
.regime-card .k { font: 500 11px/1 var(--mono); letter-spacing: .1em; text-transform: uppercase; color: var(--muted); }
.regime-card .v { font: 600 19px/1.2 var(--display); margin-top: 8px; display: flex; align-items: center; gap: 8px; }
.quad { margin: 0; background: var(--card); border: 1px solid var(--ring); border-radius: var(--r); padding: 18px; min-width: 0; display: flex; flex-direction: column; }
.quad h2 { font: 600 16px/1.3 var(--display); margin: 0; }
.quad p { color: var(--muted); font-size: 13px; margin: 4px 0 10px; }
.quad svg { width: 100%; height: auto; display: block; }
.quad text { font-family: var(--body); }

/* Nav */
nav { position: sticky; top: env(safe-area-inset-top, 0px); z-index: 5; margin: 0 0 28px; padding: 10px 0;
  background: color-mix(in srgb, var(--page) 88%, transparent); backdrop-filter: blur(10px); -webkit-backdrop-filter: blur(10px);
  border-bottom: 1px solid var(--grid); }
nav .row { display: flex; gap: 6px; overflow-x: auto; scrollbar-width: none; }
nav a { flex: none; text-decoration: none; font: 500 13px/1 var(--body); color: var(--ink-2); padding: 9px 14px; border-radius: 999px;
  border: 1px solid transparent; transition: color .2s, background .2s, border-color .2s; }
nav a:hover { color: var(--ink); border-color: var(--ring); }
nav a.on { color: var(--ink); background: var(--card-2); border-color: var(--ring); }

/* Sections */
section.tab > * + * { margin-top: 0; }
.tab .block { padding-top: 40px; }
.sec-head { display: flex; align-items: baseline; justify-content: space-between; gap: 16px; flex-wrap: wrap; margin-bottom: 18px; }
h2.sec { font: 800 clamp(26px, 3.4vw, 38px)/1.05 var(--display); letter-spacing: -0.02em; margin: 0; }
.sec-head .sub { color: var(--muted); font-size: 13px; }
.tiles { display: grid; grid-template-columns: repeat(auto-fill, minmax(min(100%, 160px), 1fr)); gap: 10px; }
.tile { background: var(--card); border: 1px solid var(--ring); border-radius: var(--r); padding: 14px 16px 15px; min-width: 0;
  transition: transform .25s var(--ease), border-color .25s; }
.tile:hover { transform: translateY(-2px); border-color: rgba(255,255,255,.16); }
.tile .l { font: 500 11px/1.2 var(--mono); letter-spacing: .08em; text-transform: uppercase; color: var(--muted); }
.tile .v { font: 600 28px/1.1 var(--display); letter-spacing: -0.02em; margin: 10px 0 6px; white-space: nowrap; overflow: hidden; text-overflow: ellipsis; }
.tile .v.word { font-size: 20px; white-space: normal; }
.tile .s { color: var(--ink-2); font-size: 12.5px; }
.status { display: inline-flex; align-items: center; gap: 6px; font: 500 11.5px/1 var(--body); color: var(--ink-2); margin-top: 10px; }
.status i { width: 16px; height: 16px; border-radius: 50%; display: inline-grid; place-items: center; font: 700 10px/1 var(--body); font-style: normal; color: #0d0d0d; }
.status.good i { background: var(--good); } .status.bad i { background: var(--bad); color: var(--ink); } .status.warn i { background: var(--warn); }
.flags { display: flex; flex-wrap: wrap; gap: 8px; margin-top: 14px; }
.flag { display: inline-flex; align-items: center; gap: 8px; background: rgba(250,178,25,.08); border: 1px solid rgba(250,178,25,.28);
  color: var(--ink); border-radius: 999px; padding: 6px 12px; font-size: 13px; }
.flag::before { content: "!"; width: 16px; height: 16px; border-radius: 50%; background: var(--warn); color: #0d0d0d;
  display: inline-grid; place-items: center; font: 700 11px/1 var(--body); flex: none; }
.split { display: grid; grid-template-columns: minmax(0, 1fr) minmax(0, 2fr); gap: 14px; margin-top: 14px; align-items: start; }
.why { background: linear-gradient(180deg, var(--card-2), var(--card)); border: 1px solid var(--ring); border-radius: var(--r); padding: 18px 18px 8px; min-width: 0; }
.why h3, .card h3 { font: 600 15px/1.3 var(--display); margin: 0 0 4px; }
.why ol { list-style: none; margin: 10px 0 0; padding: 0; counter-reset: w; }
.why li { position: relative; padding: 0 0 12px 22px; color: var(--ink-2); font-size: 14px; }
.why li::before { content: ""; position: absolute; left: 2px; top: .55em; width: 8px; height: 8px; border-radius: 2px; background: var(--s1); transform: rotate(45deg); }
.why li b { color: var(--ink); font-weight: 600; }
.charts { display: grid; grid-template-columns: repeat(auto-fit, minmax(min(100%, 340px), 1fr)); gap: 14px; min-width: 0; }
.card { background: var(--card); border: 1px solid var(--ring); border-radius: var(--r); padding: 16px 16px 12px; min-width: 0; }
.card .note { color: var(--muted); font-size: 12px; margin: 0 0 8px; }
.chart { position: relative; height: 230px; }
.chart.wide { height: 260px; }
.legend { display: flex; flex-wrap: wrap; gap: 6px 14px; margin-top: 10px; font-size: 12px; color: var(--ink-2); }
.legend span { display: inline-flex; align-items: center; gap: 6px; }
.legend svg { flex: none; }
.legend-card { display: flex; flex-wrap: wrap; gap: 8px 18px; padding: 12px 16px; margin-top: 14px; background: var(--card); border: 1px solid var(--ring);
  border-radius: var(--r); font-size: 12.5px; color: var(--ink-2); align-items: center; }
.legend-card b { font: 500 11px/1 var(--mono); letter-spacing: .08em; text-transform: uppercase; color: var(--muted); margin-right: 4px; }

/* Tables */
.table-wrap { overflow-x: auto; }
table { width: 100%; border-collapse: collapse; font-size: 13.5px; }
th, td { padding: 11px 10px; border-bottom: 1px solid var(--grid); text-align: right; white-space: nowrap; font-variant-numeric: tabular-nums; }
td { font-family: var(--mono); font-size: 13px; color: var(--ink-2); }
th:first-child, td:first-child { text-align: left; font-family: var(--body); color: var(--ink); }
th { font: 500 11px/1.2 var(--mono); letter-spacing: .08em; text-transform: uppercase; color: var(--muted); }
tbody tr { transition: background .2s; }
tbody tr:hover { background: rgba(255,255,255,.025); }
td.strong { color: var(--ink); font-weight: 500; }
.range { position: relative; width: 180px; height: 22px; }
.range .bar { position: absolute; top: 8px; height: 6px; border-radius: 3px; background: color-mix(in srgb, var(--s1) 45%, transparent); }
.range .mk { position: absolute; top: 3px; width: 2px; height: 16px; border-radius: 1px; transform: translateX(-1px); }
.range .now { background: var(--ink); } .range .ens { background: var(--s3); width: 8px; height: 8px; top: 7px; border-radius: 50%; transform: translateX(-4px); box-shadow: 0 0 0 2px var(--card); }
.method { color: var(--muted); font-size: 13px; margin: 14px 2px 0; max-width: 90ch; }
.method b { color: var(--ink-2); font-weight: 600; }

/* Tooltip */
#tip { position: fixed; z-index: 20; pointer-events: none; background: #262624; border: 1px solid rgba(255,255,255,.12); border-radius: 10px;
  padding: 8px 10px; font-size: 12px; box-shadow: 0 10px 30px rgba(0,0,0,.45); opacity: 0; transition: opacity .12s; min-width: 160px; }
#tip .d { color: var(--muted); font: 500 11px/1 var(--mono); margin-bottom: 6px; }
#tip .r { display: flex; align-items: center; gap: 8px; color: var(--ink-2); padding: 2px 0; }
#tip .r b { margin-left: auto; color: var(--ink); font: 500 12px/1 var(--mono); }
#tip .sw { width: 10px; height: 3px; border-radius: 2px; flex: none; }
footer { margin-top: 56px; padding-top: 18px; border-top: 1px solid var(--grid); color: var(--muted); font-size: 12px; display: flex; justify-content: space-between; gap: 12px; flex-wrap: wrap; }

/* Motion: everything rests visible; these only play once on load or on first view. */
@media (prefers-reduced-motion: no-preference) {
  .rise { animation: rise .8s var(--ease) both; animation-delay: calc(var(--i, 0) * 70ms); }
  @keyframes rise { from { transform: translateY(14px); opacity: .001; } to { transform: none; opacity: 1; } }
  .chart.draw canvas { animation: wipe 1.5s var(--ease) both; }
  @keyframes wipe { from { clip-path: inset(0 100% 0 0); } to { clip-path: inset(0 0 0 0); } }
  .range.grow .bar { animation: grow 1s var(--ease) both; transform-origin: left; }
  @keyframes grow { from { transform: scaleX(0); } to { transform: scaleX(1); } }
  .dot-pulse { animation: pulse 2.4s ease-out infinite; transform-box: fill-box; transform-origin: center; }
  @keyframes pulse { 0% { transform: scale(1); opacity: .55; } 80%, 100% { transform: scale(3.2); opacity: 0; } }
}
.ranges { display: flex; flex-wrap: wrap; align-items: center; gap: 6px; margin: -16px 0 18px; font: 500 11px/1 var(--mono); color: var(--muted);
  letter-spacing: .08em; text-transform: uppercase; }
.ranges span { margin-right: 4px; }
.ranges button { font: 500 12px/1 var(--mono); color: var(--ink-2); background: transparent; border: 1px solid var(--ring); border-radius: 999px;
  padding: 7px 11px; cursor: pointer; transition: color .2s, background .2s, border-color .2s; }
.ranges button:hover { color: var(--ink); border-color: rgba(255,255,255,.2); }
.ranges button.on { color: var(--ink); background: var(--card-2); border-color: rgba(255,255,255,.22); }
.ixgrid { display: grid; grid-template-columns: repeat(auto-fill, minmax(min(100%, 210px), 1fr)); gap: 10px; margin-top: 14px; }
.ix { background: var(--card); border: 1px solid var(--ring); border-radius: var(--r); padding: 14px 16px 12px; min-width: 0;
  transition: transform .25s var(--ease), border-color .25s; }
.ix:hover { transform: translateY(-2px); border-color: rgba(255,255,255,.16); }
.ix .top { display: flex; justify-content: space-between; align-items: baseline; gap: 8px; }
.ix .n { font: 600 14px/1.2 var(--display); }
.ix .cur { font: 500 10.5px/1 var(--mono); color: var(--muted); letter-spacing: .08em; }
.ix .v { font: 600 24px/1.1 var(--display); letter-spacing: -0.02em; margin: 8px 0 2px; }
.ix .d { display: flex; gap: 10px; flex-wrap: wrap; font: 500 12px/1.3 var(--mono); color: var(--ink-2); }
.up { color: var(--good); } .down { color: var(--bad); }
.spark { width: 100%; height: 44px; display: block; margin-top: 8px; overflow: visible; }
.sub-h { font: 600 18px/1.2 var(--display); margin: 28px 0 0; }
@media (prefers-reduced-motion: no-preference) {
  .spark path.l { stroke-dasharray: 1; animation: dash 1.6s var(--ease) both; animation-delay: calc(var(--i, 0) * 80ms); }
  @keyframes dash { from { stroke-dashoffset: 1; } to { stroke-dashoffset: 0; } }
}
@media (max-width: 860px) { .hero, .split { grid-template-columns: minmax(0, 1fr); } }
@media (max-width: 480px) { .tile .v { font-size: 24px; } .chart { height: 210px; } main { padding-block: 24px 56px; } }
</style>
</head>
<body>
<main>
<nav aria-label="Pestañas"><div class="row" role="tablist">
  <a href="#resumen">Resumen</a><a href="#mundo">Mundo</a><a href="#eeuu">EE.UU.</a><a href="#mexico">México</a><a href="#curvas">Curvas y tasas</a>
  <a href="#mercados">Mercados</a><a href="#comercio">Comercio y finanzas</a><a href="#pronosticos">Pronósticos</a><a href="#valuacion">Valuación</a>
</div></nav>
<section id="resumen" class="tab">
<header class="hero">
  <div class="rise">
    <div class="eyebrow">Panorama macro · corte __ASOF__</div>
    <h1 id="headline">Panorama macro</h1>
    <p class="lede">Lectura propia con datos de FRED, Banxico y el FMI: cada indicador con su historia, por qué está donde está y hacia dónde apuntan los modelos a 12 meses.</p>
    <div class="chips" id="regimes"></div>
  </div>
  <figure class="quad rise" style="--i:2" aria-labelledby="qt">
    <h2 id="qt">Mapa de régimen</h2>
    <p>Crecimiento contra su tendencia de 10 años (horizontal) y cambio de la inflación en seis meses (vertical).</p>
    <svg id="quad" viewBox="0 0 420 300" role="img" aria-label="Mapa de régimen de EE.UU. y México"></svg>
  </figure>
</header>
<div class="legend-card rise" style="--i:3" id="legend"></div>
<div id="resumen-body"></div>
</section>
<div class="ranges" role="group" aria-label="Periodo de las gráficas"><span>Periodo</span>
  <button type="button" data-r="auto" class="on">Auto</button><button type="button" data-r="1m">1M</button><button type="button" data-r="3m">3M</button>
  <button type="button" data-r="6m">6M</button><button type="button" data-r="ytd">Año</button><button type="button" data-r="1y">1A</button>
  <button type="button" data-r="5y">5A</button><button type="button" data-r="all">Todo</button></div>
<div id="app"></div>
<footer><span id="foot"></span><span>No es recomendación de inversión.</span></footer>
</main>
<div id="tip" role="presentation"></div>
<script id="data" type="application/json">__DATA__</script>
<script src="https://cdnjs.cloudflare.com/ajax/libs/Chart.js/4.4.1/chart.umd.min.js"></script>
<script>
const D = JSON.parse(document.getElementById('data').textContent);
const css = n => getComputedStyle(document.documentElement).getPropertyValue(n).trim();
const C = {ink: css('--ink'), ink2: css('--ink-2'), muted: css('--muted'), grid: css('--grid'), axis: css('--axis'), card: css('--card'),
  s1: css('--s1'), s2: css('--s2'), s3: css('--s3'), s4: css('--s4'), s5: css('--s5'), s6: css('--s6')};
// Every chart maps the same role to the same color, so the legend at the top holds for all of them.
const ROLE = {
  hist:   {color: C.s1, width: 2, dash: []},
  extra1: {color: C.s2, width: 1.5, dash: []},
  extra2: {color: C.s6, width: 1.5, dash: []},
  band:   {color: C.s1, width: 0, dash: []},
  ar:     {color: C.s3, width: 2, dash: [5, 4]},
  drift:  {color: C.s4, width: 2, dash: [2, 3]},
  ens:    {color: C.ink, width: 2, dash: [9, 4]},
  imf:    {color: C.s5, width: 0, dash: []},
  anchor: {color: C.s6, width: 2, dash: [3, 3]},
};
const REG = {goldilocks: 'goldilocks', reflation: 'reflación', stagflation: 'estanflación', slowdown: 'desaceleración'};
const REG_TONE = {goldilocks: 'good', reflation: 'warn', stagflation: 'bad', slowdown: 'warn'};
const ICON = {good: '✓', bad: '✕', warn: '!'};
const TONE_LABEL = {good: 'favorable', bad: 'en contra', warn: 'vigilar'};
const reduce = matchMedia('(prefers-reduced-motion: reduce)').matches;
const esc = s => String(s).replace(/[&<>"]/g, c => ({'&': '&amp;', '<': '&lt;', '>': '&gt;', '"': '&quot;'}[c]));
const pct = v => (v * 100).toFixed(2) + '%';
const num = (v, u) => v == null ? '—' : (u === '%' ? v.toFixed(2) + '%' : v >= 1000 ? v.toLocaleString('es-MX', {maximumFractionDigits: 0}) : v.toFixed(2));
const status = t => !t || t === 'neutral' ? '' : `<span class="status ${t}"><i aria-hidden="true">${ICON[t]}</i>${TONE_LABEL[t]}</span>`;
// Bold the figures (decimals or percentages), not plain counts like "12 meses" or "S&P 500".
const emph = s => esc(s).replace(/(^|[^\\w.])([+-]?\\d+(?:\\.\\d+%?|%))(?![\\w])/g, '$1<b>$2</b>');

// Hero
const H = D.headline;
document.getElementById('headline').innerHTML =
  `Mundo en <span class="tag" style="--hl:${C.s4}">${esc(H['Mundo'].replace(' global', ''))}</span>, EE.UU. en ` +
  `<span class="tag" style="--hl:${C.s1}">${esc(REG[H['EE.UU.']])}</span> y México en <span class="tag" style="--hl:${C.s2}">${esc(REG[H['México']])}</span>.`;
document.getElementById('regimes').innerHTML = [['Mundo', H['Mundo'], null], ['EE.UU.', REG[H['EE.UU.']], REG_TONE[H['EE.UU.']]],
  ['México', REG[H['México']], REG_TONE[H['México']]]].map(([k, v, t]) =>
  `<div class="regime-card"><div class="k">${k}</div><div class="v">${esc(v)}</div>${t ? status(t) : ''}</div>`).join('');

// Regime map
(function quad() {
  const svg = document.getElementById('quad'), W = 420, Hh = 300, P = {l: 18, r: 18, t: 14, b: 26};
  const m = Math.max(1, ...D.regimes.flatMap(r => [Math.abs(r.x), Math.abs(r.y)])) * 1.35;
  const X = v => P.l + (v + m) / (2 * m) * (W - P.l - P.r), Y = v => P.t + (m - v) / (2 * m) * (Hh - P.t - P.b);
  const cx = X(0), cy = Y(0);
  const q = [['estanflación', P.l + 8, P.t + 18, 'start'], ['reflación', W - P.r - 8, P.t + 18, 'end'],
             ['desaceleración', P.l + 8, Hh - P.b - 10, 'start'], ['goldilocks', W - P.r - 8, Hh - P.b - 10, 'end']];
  let s = `<rect x="${P.l}" y="${P.t}" width="${W - P.l - P.r}" height="${Hh - P.t - P.b}" rx="10" fill="#151514" stroke="${C.grid}"/>`;
  s += `<line x1="${cx}" y1="${P.t}" x2="${cx}" y2="${Hh - P.b}" stroke="${C.axis}"/><line x1="${P.l}" y1="${cy}" x2="${W - P.r}" y2="${cy}" stroke="${C.axis}"/>`;
  s += q.map(([t, x, y, a]) => `<text x="${x}" y="${y}" text-anchor="${a}" fill="${C.muted}" font-size="12" letter-spacing=".04em">${t}</text>`).join('');
  s += `<text x="${W - P.r}" y="${Hh - 8}" text-anchor="end" fill="${C.muted}" font-size="11">crece más que su tendencia →</text>`;
  s += `<text x="${P.l}" y="${Hh - 8}" fill="${C.muted}" font-size="11">↑ inflación subiendo</text>`;
  D.regimes.forEach((r, i) => {
    const col = i ? C.s2 : C.s1, x = X(r.x), y = Y(r.y), right = x > W - 120;
    s += `<circle class="dot-pulse" cx="${x}" cy="${y}" r="7" fill="${col}" style="animation-delay:${i * 1.2}s"/>`;
    s += `<circle cx="${x}" cy="${y}" r="7" fill="${col}" stroke="${C.card}" stroke-width="2"><title>${esc(r.name)}: ${r.x.toFixed(2)} pp vs tendencia, inflación ${r.y >= 0 ? '+' : ''}${r.y.toFixed(2)} pp</title></circle>`;
    s += `<text x="${x + (right ? -13 : 13)}" y="${y - 2}" text-anchor="${right ? 'end' : 'start'}" fill="${C.ink}" font-size="13" font-weight="600">${esc(r.name)}</text>`;
    s += `<text x="${x + (right ? -13 : 13)}" y="${y + 13}" text-anchor="${right ? 'end' : 'start'}" fill="${C.ink2}" font-size="11">PIB ${r.x >= 0 ? '+' : ''}${r.x.toFixed(2)} pp · infl. ${r.y >= 0 ? '+' : ''}${r.y.toFixed(2)} pp</text>`;
  });
  svg.innerHTML = s;
})();

// Shared legend
const swatch = (role, scatter) => scatter
  ? `<svg width="12" height="12" aria-hidden="true"><circle cx="6" cy="6" r="4.5" fill="${ROLE[role].color}"/></svg>`
  : role === 'band' ? `<svg width="18" height="10" aria-hidden="true"><rect width="18" height="10" rx="3" fill="${ROLE.band.color}" opacity=".28"/></svg>`
  : `<svg width="22" height="6" aria-hidden="true"><line x1="1" y1="3" x2="21" y2="3" stroke="${ROLE[role].color}" stroke-width="2" stroke-linecap="round" stroke-dasharray="${ROLE[role].dash.join(' ')}"/></svg>`;
document.getElementById('legend').innerHTML = '<b>Cómo leer las gráficas</b>' + [['hist', 'Histórico'], ['band', 'Banda 90%'], ['ar', 'Reversión a la media'],
  ['drift', 'Tendencia amortiguada'], ['ens', 'Promedio de modelos'], ['anchor', 'Ancla (tasa neutral o costo de capital)'], ['imf', 'FMI', true]].map(([r, l, sc]) => `<span>${swatch(r, sc)}${l}</span>`).join('');

// Sections
const SECTIONS = [
  ['mundo', 'Mundo', 'Ciclo, materias primas y apetito por riesgo', ['brent', 'copper', 'dollar', 'vix'], true],
  ['eeuu', 'EE.UU.', 'Crecimiento, precios, Fed y crédito', ['US_infl', 'US_rate', 'US_gdp', 'US_unemp']],
  ['mexico', 'México', 'Crecimiento, precios, Banxico y el peso', ['MX_infl', 'MX_rate', 'MX_gdp', 'MX_unemp', 'MX_fx']],
];
let html = '';
for (const [id, name, sub, keys, g20] of SECTIONS) {
  html += `<section id="${id}" class="tab" hidden><div class="sec-head"><h2 class="sec">${name}</h2><span class="sub">${sub}</span></div><div class="tiles">` +
    D.kpis[name].map((k, i) => {
      const isNum = /\\d/.test(k.value);
      return `<div class="tile rise" style="--i:${i}"><div class="l">${esc(k.label)}</div>` +
        `<div class="v${isNum ? '' : ' word'}"${isNum ? ` data-count="${esc(k.value)}"` : ''}>${esc(isNum ? k.value : (REG[k.value] || k.value))}</div>` +
        `<div class="s">${esc(k.sub)}</div>${status(k.tone)}</div>`;
    }).join('') + '</div>';
  const flags = D.flags[name];
  if (flags.length) html += '<div class="flags">' + flags.map(f => `<span class="flag">${esc(f)}</span>`).join('') + '</div>';
  html += `<div class="split"><div class="why"><h3>Por qué está así</h3><ol>${D.reasons[name].map(r => `<li>${emph(r)}</li>`).join('')}</ol></div><div class="charts">`;
  if (g20) html += `<div class="card"><h3>Crecimiento ${D.g20.year} en el G20</h3><p class="note">FMI, % real anual. EE.UU. y México resaltados.</p><div class="chart"><canvas id="c_g20" role="img" aria-label="Crecimiento por país del G20"></canvas></div></div>`;
  for (const k of keys) {
    const c = D.charts[k], extras = c.lines.filter(l => l.role.startsWith('extra'));
    html += `<div class="card"><h3>${esc(c.title)}</h3><div class="chart"><canvas id="c_${k}" role="img" aria-label="${esc(c.title)}"></canvas></div>` +
      (extras.length ? `<div class="legend">${[{role: 'hist', label: c.title}].concat(extras).map(l => `<span>${swatch(l.role)}${esc(l.label)}</span>`).join('')}</div>` : '') + '</div>';
  }
  html += '</div></div></section>';
}
// Markets
const MK = D.markets;
const ixChart = ix => `<div class="card"><h3>${esc(ix.name)}</h3><p class="note">Cierre diario en ${ix.currency}; modelos y rentabilidad exigida a 12 meses.</p><div class="chart"><canvas id="c_ix_${esc(ix.name)}" role="img" aria-label="${esc(ix.name)}"></canvas></div></div>`;
const delta = v => `<span class="${v >= 0 ? 'up' : 'down'}">${v >= 0 ? '▲' : '▼'} ${Math.abs(v * 100).toFixed(1)}%</span>`;
function spark(pts) {
  const xs = pts.map(p => p[0]), ys = pts.map(p => p[1]), x0 = Math.min(...xs), x1 = Math.max(...xs), y0 = Math.min(...ys), y1 = Math.max(...ys);
  const X = x => (x - x0) / ((x1 - x0) || 1) * 200, Y = y => 40 - (y - y0) / ((y1 - y0) || 1) * 36;
  const d = pts.map((p, i) => `${i ? 'L' : 'M'}${X(p[0]).toFixed(1)},${Y(p[1]).toFixed(1)}`).join('');
  const last = pts[pts.length - 1];
  return `<svg class="spark" viewBox="0 0 200 44" preserveAspectRatio="none" aria-hidden="true"><path d="${d}L200,44L0,44Z" fill="${C.s1}" opacity=".10"/>` +
    `<path class="l" d="${d}" pathLength="1" fill="none" stroke="${C.s1}" stroke-width="1.6" stroke-linejoin="round" stroke-linecap="round" vector-effect="non-scaling-stroke"/>` +
    `<circle cx="${X(last[0])}" cy="${Y(last[1])}" r="2.6" fill="${C.ink}"/></svg>`;
}
const ixCard = (ix, i) => `<div class="ix rise" style="--i:${i}"><div class="top"><span class="n">${esc(ix.name)}</span><span class="cur">${ix.currency}</span></div>
  <div class="v" data-count="${num(ix.last, '')}">${num(ix.last, '')}</div>
  <div class="d"><span>año ${delta(ix.ytd)}</span><span>12m ${delta(ix.r1y)}</span></div>
  <div class="d" style="margin-top:4px;color:var(--muted)"><span>máx. 52s ${(ix.drawdown * 100).toFixed(1)}%</span><span>vol ${(ix.vol_3m * 100).toFixed(0)}%</span></div>${spark(ix.spark)}</div>`;
const why = (title, list) => `<div class="why"><h3>${title}</h3><ol>${list.map(r => `<li>${emph(r)}</li>`).join('')}</ol></div>`;
const tiles = list => '<div class="tiles">' + list.map((k, i) => `<div class="tile rise" style="--i:${i}"><div class="l">${esc(k.label)}</div>` +
  `<div class="v" data-count="${esc(k.value)}">${esc(k.value)}</div><div class="s">${esc(k.sub)}</div>${status(k.tone)}</div>`).join('') + '</div>';
const card = (key, title, note, legend = true) => `<div class="card"><h3>${title}</h3>${note ? `<p class="note">${note}</p>` : ''}` +
  `<div class="chart"><canvas id="c_${key}" role="img" aria-label="${esc(title)}"></canvas></div>` +
  (legend && D.specs[key] && D.specs[key].series.length > 1 ? `<div class="legend">${D.specs[key].series.map(x => `<span>${x.dots ? `<svg width="12" height="12" aria-hidden="true"><circle cx="6" cy="6" r="4" fill="${SLOT(x.color)}"/></svg>` : line(x.color, x.dash)}${esc(x.label)}</span>`).join('')}</div>` : '') + '</div>';
const SLOT = k => k === 'muted' ? 'rgba(195,194,183,.55)' : C[k];
const line = (k, dash = []) => `<svg width="22" height="6" aria-hidden="true"><line x1="1" y1="3" x2="21" y2="3" stroke="${SLOT(k)}" stroke-width="2" stroke-linecap="round" stroke-dasharray="${(dash || []).join(' ')}"/></svg>`;
const sec = (id, title, sub, body) => `<section id="${id}" class="tab" hidden><div class="sec-head"><h2 class="sec">${title}</h2><span class="sub">${sub}</span></div>${body}</section>`;

// Curves and rates
const NR = D.neutral;
html += sec('curvas', 'Curvas y tasas', 'Curvas nominales y reales, pendiente, recesión y tasa neutral',
  tiles(MK.kpis) +
  `<div class="charts" style="margin-top:14px">${card('curve_US', 'Curva de Treasuries', 'Rendimiento por plazo, %.')}${card('curve_MX', 'Curva de México', 'CETES y Bonos M en subasta, %.')}</div>
  <div class="split">${why('Qué dicen las curvas', D.reasons['Curvas'])}<div class="charts">
  ${card('real_curves', 'Curvas reales', 'TIPS de EE.UU. y Udibonos de México, % real por plazo.')}
  ${card('spread', 'Diferencial México – EE.UU.', 'Puntos porcentuales por plazo.')}
  ${card('slopes', 'Pendiente de la curva de EE.UU.', 'Abajo de cero, curva invertida.')}
  ${card('prob', 'Probabilidad de recesión a 12 meses', 'Probit de la Fed de Nueva York sobre la pendiente 10a – 3m. La línea punteada marca 30%.')}
  </div></div>
  <h3 class="sub-h">Tasa neutral</h3>
  <div class="card table-wrap" style="margin-top:14px"><table><thead><tr><th>País</th><th>r* nuestro</th><th>Crec. tendencial</th><th>Tasa real ex ante 10a</th>
  <th>Referencia externa</th><th>Meta</th><th>Neutral nominal</th><th>Tasa actual</th><th>Brecha</th><th>Postura</th></tr></thead><tbody>` +
  NR.map(x => `<tr><td>${x.country}</td><td class="strong">${x.rstar.toFixed(2)}%</td><td>${x.growth.toFixed(2)}%</td><td>${x.avg_real.toFixed(2)}%</td>
  <td>${x.external.toFixed(2)}% <span style="color:var(--muted)">${esc(x.external_label)}</span></td><td>${x.target.toFixed(0)}%</td>
  <td class="strong">${x.nominal.toFixed(2)}%</td><td>${x.policy.toFixed(2)}%</td><td class="strong">${x.gap >= 0 ? '+' : ''}${x.gap.toFixed(2)} pp</td><td>${x.stance}</td></tr>`).join('') +
  `</tbody></table><p class="note" style="margin-top:10px">r* nuestro: promedio del crecimiento tendencial (10 años de PIB real) y de la tasa real ex ante de 10 años (tasa de política menos inflación esperada a un año en EE.UU., inflación observada en México). Neutral nominal = r* + meta de inflación. Brecha arriba de 0.75 pp: restrictiva; abajo de −0.75 pp: laxa.</p></div>
  <div class="charts" style="margin-top:14px">${card('rstar_US', 'Tasa real ex ante vs r*, EE.UU.', 'Fed funds menos inflación esperada a un año (Fed de Cleveland).')}${card('rstar_MX', 'Tasa real ex ante vs r*, México', 'Tasa Banxico menos inflación anual.')}</div>`);

// Markets
html += sec('mercados', 'Mercados', 'Índices y lo que les dice la macro',
  `<div class="ixgrid">${MK.indices.concat([MK.ipc_usd]).map(ixCard).join('')}</div>
  <div class="split">${why('Qué dicen los mercados', D.reasons['Mercados'])}<div class="charts">
  ${MK.indices.slice(0, 2).map(ixChart).join('')}</div></div>
  <div class="charts" style="margin-top:14px">${MK.indices.slice(2).map(ixChart).join('')}</div>`);

// Trade and public finances
const EC = D.economy;
html += sec('comercio', 'Comercio y finanzas públicas', 'Cuentas externas, deuda, actividad y riesgo de crédito',
  `<h3 class="sub-h" style="margin-top:0">EE.UU.</h3>${tiles(EC.us)}<h3 class="sub-h">México</h3>${tiles(EC.mx)}<h3 class="sub-h">Riesgo de crédito</h3>${tiles(EC.risk)}
  <div class="split">${why('Qué implica', D.reasons['Comercio'])}<div class="charts">
  ${card('us_trade', 'Balanza comercial de EE.UU.', 'Bienes y servicios, miles de millones de USD al mes.')}
  ${card('mx_goods', 'Balanza de mercancías de México', 'Exportaciones menos importaciones, miles de millones de USD por trimestre.')}
  ${card('mx_remit', 'Remesas a México', 'Suma de 12 meses, miles de millones de USD.')}
  ${card('mx_reserves', 'Reservas internacionales de México', 'Miles de millones de USD.')}
  ${card('credit', 'Spreads de crédito', 'ICE BofA, sobre bonos del Tesoro, puntos porcentuales. Sustituyen al CDS, que no tiene fuente gratuita.')}
  <div class="card table-wrap"><h3>FMI ${EC.imf.year}, % del PIB</h3><table><thead><tr><th>Indicador</th><th>EE.UU.</th><th>México</th><th>Mediana G20</th></tr></thead><tbody>` +
  EC.imf.rows.map(r => `<tr><td>${r.ind}</td><td>${r['EE.UU.'].toFixed(1)}%</td><td>${r['México'].toFixed(1)}%</td><td>${r['Mediana G20'].toFixed(1)}%</td></tr>`).join('') +
  `</tbody></table></div></div></div>`);

// Each bar is centered on today's value, so a lopsided range shows which way the models lean.
const half = f => Math.max(Math.abs(f.lo - f.now), Math.abs(f.hi - f.now), Math.abs(f.ensemble - f.now)) * 1.1 || 1;
const at = (v, f) => (50 + (v - f.now) / half(f) * 50).toFixed(1) + '%';
html += `<section id="pronosticos" class="tab" hidden><div class="sec-head"><h2 class="sec">Pronósticos a 12 meses</h2><span class="sub">Dos modelos, su promedio y las referencias del FMI y del mercado</span></div>
  <div class="card table-wrap"><table><thead><tr><th>Indicador</th><th>Horizonte</th><th>Actual</th><th>Tendencia</th><th>Reversión</th><th>Promedio</th>
  <th>Rango 90%</th><th aria-label="Rango visual"></th><th>FMI</th><th>Mercado</th><th>Ancla</th></tr></thead><tbody>` + D.forecasts.map(f => `<tr>
  <td>${esc(f.name)}</td><td>${f.horizon}</td><td>${num(f.now, f.unit)}</td><td>${num(f.drift, f.unit)}</td><td>${num(f.ar1, f.unit)}</td>
  <td class="strong">${num(f.ensemble, f.unit)}</td><td>${num(f.lo, f.unit)} – ${num(f.hi, f.unit)}</td>
  <td><div class="range" title="Centrado en hoy (línea blanca): rango 90% y promedio (punto)"><div class="bar" style="left:${at(f.lo, f)};width:calc(${at(f.hi, f)} - ${at(f.lo, f)})"></div>
  <div class="mk now" style="left:${at(f.now, f)}"></div><div class="mk ens" style="left:${at(f.ensemble, f)}"></div></div></td>
  <td>${num(f.imf, f.unit)}</td><td>${num(f.market, f.unit)}</td><td>${num(f.anchor, f.unit)}</td></tr>`).join('') + `</tbody></table></div>
  <p class="method"><b>Tendencia</b>: el ritmo del último año, amortiguado para no proyectar un choque para siempre. <b>Reversión</b>: modelo autorregresivo ajustado a 10 años; la serie regresa a su promedio de largo plazo. <b>Promedio</b>: de ambos modelos. <b>Rango 90%</b>: cubre ambos modelos más el error típico del modelo, sin que un choque como 2020 lo infle. En la barra, la línea blanca es hoy y el punto verde el promedio. <b>FMI</b>: último año proyectado. <b>Mercado</b>: inflación esperada a 10 años en la inflación de EE.UU.; en las tasas de política, el bono a 2 años (EE.UU.) o los CETES a un año (México), que reflejan la tasa que el mercado espera. <b>Ancla</b>: lo que implica la macro. En las tasas de política, la convergencia a nuestra tasa neutral nominal (la brecha se reduce a la mitad cada año); en los índices, el nivel al que llegarían si rinden exactamente nuestro costo de capital (EE.UU. para los índices en dólares y extranjeros, México para el IPC). Son referencias, no certezas.</p></section>`;
html += `<section id="valuacion" class="tab" hidden><div class="sec-head"><h2 class="sec">Supuestos de valuación</h2><span class="sub">Lo que estas lecturas implican para descontar flujos</span></div>
  <div class="split"><div class="why"><h3>Por qué estos supuestos</h3><ol>${D.reasons['Supuestos'].concat(D.reasons['Riesgo']).map(r => `<li>${emph(r)}</li>`).join('')}</ol></div>
  <div class="card table-wrap"><table><thead><tr><th>Mercado</th><th>Libre de riesgo</th><th>Prima</th><th>Riesgo país</th><th>Infl. esperada</th>
  <th>Crec. terminal</th><th>Costo de capital</th></tr></thead><tbody>` + D.assumptions.map(a => `<tr>
  <td>${esc(a.market)} <span style="color:var(--muted)">${esc(a.currency)}</span></td><td>${pct(a.rf)}</td><td>${pct(a.erp)}</td><td>${pct(a.crp)}</td>
  <td>${pct(a.infl)}</td><td>${pct(a.g)}</td><td class="strong">${pct(a.coe)}</td></tr>`).join('') + `</tbody></table>
  <p class="note" style="margin-top:10px">Costo de capital con beta 1, en moneda local. Libre de riesgo: bono a 10 años de EE.UU.</p></div></div></section>`;
document.getElementById('app').innerHTML = html;
const allFlags = ['Mundo', 'EE.UU.', 'México'].flatMap(k => D.flags[k].map(f => `${k}: ${f}`));
document.getElementById('resumen-body').innerHTML = `<div class="block"><div class="sec-head"><h2 class="sec">Lo más importante</h2><span class="sub">Curva, tasas neutrales y mercados</span></div>` +
  tiles(D.summary) + (allFlags.length ? '<div class="flags">' + allFlags.map(f => `<span class="flag">${esc(f)}</span>`).join('') + '</div>' : '') + '</div>';
document.getElementById('foot').textContent = `Generado ${D.generated} con python -m macro dashboard · FRED, Banxico SIE, FMI WEO`;

// Count-up on tiles: animate the number, then put back the exact text.
function countUp(el) {
  const final = el.dataset.count, m = final.match(/-?[\\d,]*\\d(\\.\\d+)?/);
  if (!m || reduce) return;
  const grouped = m[0].includes(','), target = parseFloat(m[0].replace(/,/g, '')), dec = m[1] ? m[1].length - 1 : 0;
  const fmt = v => grouped ? Math.round(v).toLocaleString('es-MX') : v.toFixed(dec), t0 = performance.now(), dur = 1100;
  const step = t => {
    const k = Math.min(1, (t - t0) / dur), e = 1 - Math.pow(1 - k, 3);
    el.textContent = final.replace(m[0], fmt(target * e));
    if (k < 1) requestAnimationFrame(step); else el.textContent = final;
  };
  requestAnimationFrame(step);
}

// Tooltip shared by every chart
const tip = document.getElementById('tip');
function external({chart, tooltip}) {
  if (!tooltip.opacity || !tooltip.dataPoints?.length) { tip.style.opacity = 0; return; }
  const c = chart.$meta, pts = tooltip.dataPoints.filter(p => !p.dataset.label.startsWith('_'));
  const date = c.bar ? tooltip.title[0] : c.curve ? 'Plazo ' + (pts.find(p => p.raw.t)?.raw.t || +pts[0].parsed.x.toFixed(2) + ' años')
    : new Date(pts[0].parsed.x).toISOString().slice(0, c.daily ? 10 : 7);
  tip.innerHTML = `<div class="d">${esc(date)}</div>` + pts.map(p => `<div class="r"><span class="sw" style="background:${p.dataset.borderColor || p.dataset.backgroundColor}"></span>${esc(p.dataset.label === 'Histórico' ? c.title : p.dataset.label)}<b>${c.fmt ? c.fmt(p.parsed.y) : num(p.parsed.y, c.unit)}</b></div>`).join('');
  const r = chart.canvas.getBoundingClientRect(), w = tip.offsetWidth, h = tip.offsetHeight;
  let x = r.left + tooltip.caretX + 14, y = r.top + tooltip.caretY - h / 2;
  if (x + w > innerWidth - 8) x = r.left + tooltip.caretX - w - 14;
  tip.style.left = Math.max(8, x) + 'px'; tip.style.top = Math.min(innerHeight - h - 8, Math.max(8, y)) + 'px'; tip.style.opacity = 1;
}
addEventListener('scroll', () => { tip.style.opacity = 0; }, {passive: true});

// Crosshair: a hairline at the hovered x.
const crosshair = {id: 'crosshair', afterDatasetsDraw(chart) {
  const a = chart.tooltip?.getActiveElements?.();
  if (!a?.length || chart.$meta.bar) return;
  const x = a[0].element.x, {top, bottom} = chart.chartArea, g = chart.ctx;
  g.save(); g.strokeStyle = 'rgba(240,239,236,.28)'; g.lineWidth = 1; g.beginPath(); g.moveTo(x, top); g.lineTo(x, bottom); g.stroke(); g.restore();
}};

// Charts described by D.specs: curves by tenor (x in years), bars by category, or several series over time.
function specChart(key) {
  const sp = D.specs[key], el = document.getElementById('c_' + key), mono = {color: C.muted, font: {family: css('--mono'), size: 10.5}};
  const fmt = v => sp.unit === '%' ? v.toFixed(2) + '%' : v.toFixed(2) + sp.unit;
  if (sp.kind === 'cat') {
    const o = base({bar: true, unit: ''});
    o.scales.y.ticks.callback = v => +v.toFixed(1) + sp.unit;
    o.scales.x.ticks = {...mono, autoSkip: true, maxRotation: 0, maxTicksLimit: 8};
    const ch = new Chart(el, {type: 'bar', plugins: [crosshair], options: o, data: {labels: sp.labels,
      datasets: sp.series.map(x => ({label: x.label, data: x.values, borderRadius: 4, borderSkipped: 'start', maxBarThickness: 28,
        backgroundColor: x.values.map(v => v < 0 ? C.s2 : C.s1)}))}});
    ch.$meta = {bar: true, unit: sp.unit, title: sp.series[0].label, fmt}; return;
  }
  const o = base({unit: sp.unit === '%' ? '%' : ''}), xs = sp.series.flatMap(x => x.points.map(p => p[0]));
  o.scales.y.ticks.callback = v => +v.toFixed(1) + (sp.unit === '%' ? '%' : '');
  if (sp.kind === 'tenor') o.scales.x = {type: 'linear', min: 0, max: 30, grid: {display: false}, border: {color: C.axis}, ticks: {...mono, stepSize: 5, callback: v => v + 'a'}};
  else Object.assign(o.scales.x, {min: Math.min(...xs), max: Math.max(...xs)});
  const ref = sp.ref == null ? [] : [{id: 'ref', afterDraw(c) { const y = c.scales.y.getPixelForValue(sp.ref), {left, right} = c.chartArea, g = c.ctx;
    g.save(); g.setLineDash([4, 4]); g.strokeStyle = C.axis; g.beginPath(); g.moveTo(left, y); g.lineTo(right, y); g.stroke(); g.restore(); }}];
  const ch = new Chart(el, {type: 'line', plugins: [crosshair, ...ref], options: o, data: {datasets: sp.series.map(x => ({
    label: x.label, borderColor: SLOT(x.color), backgroundColor: SLOT(x.color), borderWidth: 2, borderDash: x.dash || [], tension: x.dots ? 0 : 0.3,
    showLine: !x.dots, pointRadius: x.dots ? 3.5 : 0, pointHoverRadius: 5, pointBorderColor: C.card, pointBorderWidth: x.dots ? 1.5 : 0,
    pointHoverBorderColor: C.card, pointHoverBorderWidth: 2,
    data: x.points.map(([a, b], i) => ({x: a, y: b, t: x.tenors ? x.tenors[i] : null}))}))}});
  ch.$meta = {unit: sp.unit, title: sp.series[0].label, curve: sp.kind === 'tenor', fmt, daily: !!sp.daily};
  if (sp.kind === 'time') track(ch, xs, Math.max(...xs), !!sp.daily);
}

function makeChart(key) {
  if (D.specs[key]) return specChart(key);
  if (key === 'g20') {
    const labels = D.g20.labels, vals = D.g20.values;
    const ch = new Chart(document.getElementById('c_g20'), {
      type: 'bar', plugins: [crosshair],
      data: {labels, datasets: [{label: 'Crecimiento real', data: vals, borderRadius: 4, borderSkipped: 'start', maxBarThickness: 18,
        backgroundColor: labels.map(l => l === 'USA' ? C.s1 : l === 'MEX' ? C.s2 : 'rgba(195,194,183,.28)')}]},
      options: base({bar: true, unit: '%'}),
    });
    ch.$meta = {bar: true, unit: '%', title: 'Crecimiento real'};
    return;
  }
  const c = D.charts[key];
  const datasets = c.lines.map(l => {
    const r = ROLE[l.role];
    return {label: l.label, data: l.points.map(([x, y]) => ({x, y})), borderColor: r.color,
      backgroundColor: l.fill ? r.color + '38' : r.color, borderWidth: r.width, borderDash: r.dash,
      borderCapStyle: 'round', borderJoinStyle: 'round', pointRadius: l.scatter ? 4.5 : 0, pointHoverRadius: l.scatter ? 6 : (r.width ? 4 : 0),
      pointBorderColor: C.card, pointBorderWidth: l.scatter ? 2 : 0, pointHoverBorderWidth: 2, pointHoverBorderColor: C.card, pointHoverBackgroundColor: r.color,
      showLine: !l.scatter, fill: l.fill ? '-1' : false, tension: 0, spanGaps: false};
  });
  const xs = c.lines.flatMap(l => l.points.map(p => p[0])), opts = base({unit: c.unit});
  Object.assign(opts.scales.x, {min: Math.min(...xs), max: Math.max(...xs)});
  const ch = new Chart(document.getElementById('c_' + key), {type: 'line', data: {datasets}, plugins: [crosshair], options: opts});
  ch.$meta = {unit: c.unit, title: c.title, daily: c.daily};
  const hist = c.lines.find(l => l.role === 'hist').points;
  track(ch, xs, hist[hist.length - 1][0], c.daily);
}

function base({bar, unit}) {
  const tick = {color: C.muted, font: {family: css('--mono'), size: 10.5}};
  return {
    maintainAspectRatio: false, animation: false, normalized: true,
    interaction: bar ? {mode: 'index', intersect: false} : {mode: 'nearest', axis: 'x', intersect: false},
    layout: {padding: {top: 4, right: 14}},
    scales: {
      x: bar ? {grid: {display: false}, border: {color: C.axis}, ticks: {...tick, autoSkip: false, maxRotation: 90, minRotation: 0}}
             : {type: 'linear', grid: {display: false}, border: {color: C.axis}, ticks: {...tick, maxTicksLimit: 6, callback(v) {
               const d = new Date(v), span = this.max - this.min;  // label by the window shown, not by the data
               return span < 120 * 864e5 ? d.toLocaleDateString('es-MX', {day: 'numeric', month: 'short', timeZone: 'UTC'})
                 : span < 800 * 864e5 ? d.toLocaleDateString('es-MX', {month: 'short', year: '2-digit', timeZone: 'UTC'}) : d.getUTCFullYear(); }}},
      y: {grid: {color: C.grid, drawTicks: false}, border: {display: false}, ticks: {...tick, padding: 8, maxTicksLimit: 5,
        callback: v => unit === '%' ? +v.toFixed(1) + '%' : v >= 1000 ? (v / 1000).toLocaleString('es-MX', {maximumFractionDigits: 1}) + 'k' : +v.toFixed(1)}},
    },
    plugins: {legend: {display: false}, tooltip: {enabled: false, external, filter: i => !i.dataset.label.startsWith('_')}},
  };
}

// Period selector: one window for every time chart. "Auto" = last year for daily charts, everything for monthly ones.
// The forecast stays visible but never takes more room than the history shown.
let range = 'auto';
const timed = [];
const MONTH = 30.44 * 864e5;
function windowFor(r, last, xmin, xmax, daily) {
  const k = r === 'auto' ? (daily ? '1y' : 'all') : r;
  if (k === 'all') return [xmin, xmax];
  const lo = k === 'ytd' ? Date.UTC(new Date(last).getUTCFullYear(), 0, 1) : last - {'1m': 1, '3m': 3, '6m': 6, '1y': 12, '5y': 60}[k] * MONTH;
  return [Math.max(lo, xmin), Math.min(xmax, last + Math.max(last - lo, MONTH))];
}
function applyRange(t) {
  const [lo, hi] = windowFor(range, t.last, t.xmin, t.xmax, t.daily), ys = [];
  t.chart.data.datasets.forEach(d => d.data.forEach(p => { if (p.x >= lo && p.x <= hi && p.y != null) ys.push(p.y); }));
  const ymin = Math.min(...ys), ymax = Math.max(...ys);
  // Round the y bounds to a 1-2-5 step so the end ticks read as round numbers.
  const raw = (ymax - ymin) / 4 || Math.abs(ymax) * 0.05 || 1, mag = 10 ** Math.floor(Math.log10(raw));
  const step = [1, 2, 2.5, 5, 10].map(f => f * mag).find(x => x >= raw);
  Object.assign(t.chart.options.scales.x, {min: lo, max: hi});
  Object.assign(t.chart.options.scales.y, {min: Math.floor(ymin / step) * step, max: Math.ceil(ymax / step) * step});
  t.chart.update('none');
}
function track(chart, xs, last, daily) {
  const t = {chart, last, daily, xmin: Math.min(...xs), xmax: Math.max(...xs)};
  timed.push(t); applyRange(t);
}
document.querySelectorAll('.ranges button').forEach(b => b.addEventListener('click', () => {
  range = b.dataset.r;
  document.querySelectorAll('.ranges button').forEach(x => x.classList.toggle('on', x === b));
  timed.forEach(applyRange);
}));

// Tabs: one section at a time, routed on the hash; a tab's charts and counters are built the first time it is shown.
const built = new Set();
if (window.Chart?.defaults) { Chart.defaults.font.family = css('--body'); Chart.defaults.color = C.muted; }
const tabs = [...document.querySelectorAll('section.tab')], links = [...document.querySelectorAll('nav a')];
function show(id) {
  const tab = tabs.find(t => t.id === id) || tabs[0];
  tabs.forEach(t => { t.hidden = t !== tab; });
  links.forEach(a => { const on = a.getAttribute('href') === '#' + tab.id; a.classList.toggle('on', on); a.setAttribute('aria-selected', on); });
  if (built.has(tab.id)) return; built.add(tab.id);
  setTimeout(() => {  // after the tab is laid out; a timer, not rAF, so a background tab still builds
    tab.querySelectorAll('.chart').forEach(el => { if (window.Chart) { el.classList.add('draw'); makeChart(el.querySelector('canvas').id.slice(2)); } });
    tab.querySelectorAll('[data-count]').forEach(countUp);
    tab.querySelectorAll('.range').forEach(el => el.classList.add('grow'));
  }, 0);
}
links.forEach(a => a.addEventListener('click', ev => { ev.preventDefault(); const id = a.getAttribute('href').slice(1);
  history.replaceState(null, '', '#' + id); show(id); scrollTo({top: 0}); a.scrollIntoView({block: 'nearest', inline: 'center'}); }));
addEventListener('hashchange', () => show(location.hash.slice(1)));
show(location.hash.slice(1));
</script>
</body>
</html>
"""
