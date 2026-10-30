"""One self-contained HTML page: every reading of the report, its history, the reasons behind it and forecasts.

build_dashboard computes the payload (macro.site.payload / reasons) and assembles the page from macro/site/assets:
an HTML skeleton, one stylesheet and the scripts, with the data embedded in <script id="data">.
"""

from __future__ import annotations

import json
from datetime import datetime
from functools import cache
from importlib.resources import files
from zoneinfo import ZoneInfo

import numpy as np
import pandas as pd

from macro import sources
from macro.economy import build_economy
from macro.economy import reasons as economy_reasons
from macro.forecast import forecast
from macro.markets import build_markets
from macro.markets import reasons as market_reasons
from macro.neutral import build_neutral
from macro.policy import build_rates
from macro.report import WeoFetch, build_report
from macro.site.payload import (_along, _answers, _calendar, _changes, _chart, _economy_payload, _imf_points, _kpis,
                                _markets_payload, _neutral_rows, _rate_flags, _rates_payload, _recent, _specs, _summary, _with_deltas,
                                _at_horizon, _yoy_pct)
from macro.site.reasons import _rate_reasons, reasons
from macro.snapshot import _monthly

ASSETS = files("macro.site") / "assets"
# Scripts are concatenated in this order; an area that has no file yet simply is not in the navigation.
JS_ORDER = ["core.js", "components.js", *(f"areas/{a}.js" for a in ("hoy", "macro", "tasas", "fx", "mercados", "sectores", "empresas", "reportes")), "router.js"]


def _asset(name: str) -> str:
    return (ASSETS / name).read_text(encoding="utf-8")


def _js() -> str:
    return "\n".join(_asset(n) for n in JS_ORDER if (ASSETS / n).is_file())


def build_dashboard(as_of: str, erp: float | None = None, fetch: sources.Fetch = sources.fetch,
                    weo_fetch: WeoFetch = sources.imf_weo, options=sources.option_chain) -> str:
    fetch, weo_fetch = cache(fetch), cache(weo_fetch)  # the report and the charts read the same series once
    r = build_report(as_of, erp=erp, fetch=fetch, weo_fetch=weo_fetch)
    m = build_markets(r, fetch)
    n = build_neutral(r, fetch)
    s = {reg: sources.load(reg, as_of, fetch) for reg in sources.SERIES if reg != "FUTURES"}
    weo = {ind: weo_fetch(ind) for ind in sources.IMF_INDICATORS}
    e = build_economy(r, weo, fetch)
    rates = build_rates(as_of, fetch, options)
    cons = s["CONSENSUS"]
    year = int(as_of[:4])

    charts, forecasts = {}, []

    def add(key, title, unit, hist, freq="MS", imf=None, extra=(), market=None, anchor=None, chart=True, daily=None,
            outside=None, sigma12=None, auto_from=None):
        """anchor: (label, index -> Series), a path the macro side implies (Taylor rate, cost of equity).
        outside: (label, Series by date), the market's or the consensus's path (futures, expectations, survey);
        when given, the headline forecast is the average of our AR model and it, and our two pure models stay drawn.
        daily: the same series day by day, drawn instead of the monthly history (models still fit monthly)."""
        fc = forecast(hist, 4 if freq == "QS" else 12, freq)
        if anchor is not None:
            fc["anchor"] = anchor[1](fc.index)
        if outside is not None:
            fc["outside"] = _along(outside[1], float(hist.iloc[-1]), hist.index[-1], fc.index)
            fc["ensemble"] = (fc["ar1"] + fc["outside"]) / 2
            fc["lo"], fc["hi"] = np.minimum(fc["lo"], fc["outside"]), np.maximum(fc["hi"], fc["outside"])
        if sigma12 is not None:  # band from option-implied vol (MOVE), not from model residuals
            spread = 1.645 * sigma12 * np.sqrt(np.arange(1, len(fc) + 1) / (4 if freq == "QS" else 12))
            fc["lo"], fc["hi"] = fc["ensemble"] - spread, fc["ensemble"] + spread
            market = float(fc["outside"].iloc[-1])
        if chart:
            charts[key] = _chart(title, unit, hist if daily is None else _recent(daily.dropna(), 5), fc, imf, extra,
                                 anchor[0] if anchor else None, outside[0] if outside else None)
            charts[key]["daily"] = daily is not None
            charts[key]["freq"] = freq
            # Default window start (the GDP charts skip the 2020 collapse, which flattens the rest).
            charts[key]["auto_from"] = int(pd.Timestamp(auto_from).timestamp() * 1000) if auto_from else None
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
        # Outside view at 12 months: Cleveland Fed 1y expectation (US), Banxico survey next-12-months median (MX).
        expected_12m = float(s["US_ECON"]["inflation_exp_1y"].iloc[-1]) if c == "US" else float(cons["mx_infl_12m"].iloc[-1])
        add(f"{c}_infl", f"Inflación {name}", "%", _recent(_yoy_pct(_monthly(d["cpi"]))),
            imf=imf_i, extra=[("Inflación esperada 10a (mercado)", be)] if be is not None else (),
            outside=("Fed de Cleveland, 1 año" if c == "US" else "Encuesta Banxico, 12 meses",
                     _at_horizon(expected_12m, d["cpi"].index[-1], 12)))
        extra = [("Bono 10 años", _recent(_monthly(d["rate_10y"])))]
        if c == "MX":
            extra.append(("Tasa Fed (EE.UU.)", _recent(_monthly(s["US"]["policy_rate"]))))
        # Outside view, probability-weighted: the FedWatch path from Fed funds futures (US); for Mexico the average of
        # the Banxico survey (Cete 28 at year end) and the Cetes-implied path net of term premium.
        hist_rate = _recent(_monthly(d["policy_rate"]))
        if c == "US":
            outside = ("Futuros de Fed funds (FedWatch)", pd.Series([x["expected"] for x in rates.fed], index=[x["date"] for x in rates.fed]))
        else:
            grid = pd.date_range(hist_rate.index[-1], periods=13, freq="MS")[1:]
            survey = _along(pd.Series([float(cons["mx_cete28_t"].iloc[-1]), float(cons["mx_cete28_t1"].iloc[-1])],
                                      index=[pd.Timestamp(year, 12, 1), pd.Timestamp(year + 1, 12, 1)]),
                            float(hist_rate.iloc[-1]), hist_rate.index[-1], grid)
            cetes = _along(pd.Series([v for _, v in rates.mx_path], index=[pd.Timestamp(t, unit="ms") for t, _ in rates.mx_path]),
                           float(hist_rate.iloc[-1]), hist_rate.index[-1], grid)
            outside = ("Encuesta Banxico + curva de Cetes", (survey + cetes) / 2)
        add(f"{c}_rate", f"Tasa de política {name}", "%", hist_rate, extra=extra,
            anchor=("Regla de Taylor (neutral + brechas)", n[c].path), outside=outside,
            sigma12=rates.horizons[c]["12m"]["sigma"])
        add(f"{c}_unemp", f"Desempleo {name}", "%", _recent(_monthly(d["unemployment"])))
        gdp = d["gdp"].resample("QS").last().dropna()
        add(f"{c}_gdp", f"PIB real anual {name}", "%", _recent(_yoy_pct(gdp)), "QS", imf=imf_g, auto_from="2022-01-01")
    g = s["GLOBAL"]
    for key, title, ser in (("MX_fx", "Pesos por dólar", s["MX"]["fx_usd"]), ("brent", "Petróleo Brent (USD/barril)", g["brent"]),
                            ("copper", "Cobre (USD/libra, futuro COMEX)", g["copper"]),
                            ("dollar", "Dólar amplio (índice)", g["dollar"]), ("vix", "VIX (miedo del mercado)", g["vix"])):
        fut = {"brent": "BZ.NYM", "copper": "HG.CMX"}.get(key)
        add(key, title, "", _recent(_monthly(ser)), daily=ser,
            outside=("Curva de futuros", fetch("yahoo_curve", fut)) if fut else None)
    for ix in m.indices:
        last = float(s["INDICES"][ix.name].iloc[-1])
        # The macro side's required return, compounded monthly from the last close.
        required = lambda idx, last=last, coe=ix.cost_of_equity: last * (1 + coe) ** (pd.Series(range(1, len(idx) + 1), index=idx) / 12)
        add("ix_" + ix.name, ix.name, "", _recent(_monthly(s["INDICES"][ix.name])),
            anchor=("Rentabilidad exigida (costo de capital)", required), daily=s["INDICES"][ix.name])

    kpis = _with_deltas(_kpis(r, m, n), s)
    why = {**reasons(r, forecasts, m, n), **market_reasons(m, r), "Probabilidades": _rate_reasons(rates, n, r), **economy_reasons(e, m, r)}
    answers, answer_list = _answers(why)
    growth = sorted(r.world.growth.items(), key=lambda kv: -kv[1])
    data = {
        "as_of": r.as_of, "generated": datetime.now(ZoneInfo("America/Mexico_City")).strftime("%Y-%m-%d %H:%M") + " (hora de Ciudad de México)",
        "headline": {"Mundo": r.world.cycle, "EE.UU.": r.us.regime, "México": r.mx.regime},
        "regimes": [{"name": n, "regime": c.regime, "x": round((c.gdp_yoy - c.gdp_trend) * 100, 2),
                     "y": round((c.inflation_yoy - c.inflation_yoy_6m_ago) * 100, 2)}
                    for n, c in (("EE.UU.", r.us), ("México", r.mx))],
        "kpis": kpis, "reasons": why,
        "markets": _markets_payload(m), "charts": charts, "forecasts": forecasts,
        "specs": _specs(m, n, e, rates), "neutral": _neutral_rows(n), "economy": _economy_payload(e),
        "changes": _changes(kpis), "calendar": _calendar(as_of), "answers": answers, "answer_list": answer_list,
        "summary": _summary(r, m, n, rates), "rates": _rates_payload(rates, r),
        "g20": {"labels": [k for k, _ in growth], "values": [round(v * 100, 2) for _, v in growth],
                "year": r.world.year},
        "assumptions": [{"market": a.market, "currency": a.currency, "rf": a.risk_free_usd,
                         "erp": a.equity_risk_premium, "crp": a.country_risk_premium,
                         "infl": a.expected_inflation, "g": a.terminal_growth, "coe": a.cost_of_equity()}
                        for a in r.assumptions],
        "flags": {"Mundo": r.world.flags + m.flags["Mundo"] + e.flags["Mundo"],
                  "EE.UU.": r.us.flags + r.vs_imf[0].flags + m.flags["EE.UU."] + e.flags["EE.UU."] + _rate_flags(rates),
                  "México": r.mx.flags + r.vs_imf[1].flags + r.mx_extras.flags + m.flags["México"] + e.flags["México"]},
    }
    payload = json.dumps(data, ensure_ascii=False, default=float).replace("</", "<\\/")
    return (_asset("page.html").replace("__CSS__", _asset("styles.css")).replace("__JS__", _js())
            .replace("__DATA__", payload))
