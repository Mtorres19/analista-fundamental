"""One self-contained HTML page: every reading of the report, its history, the reasons behind it and forecasts.

The reasons are rules over our own numbers (what each indicator implies given the others), not a narrative
pulled from outside. Forecasts come from macro.forecast plus the IMF and market expectations for comparison.
"""

from __future__ import annotations

import json
from datetime import datetime
from functools import cache

import pandas as pd

from macro import sources
from macro.assumptions import DEFAULT_ERP
from macro.forecast import forecast
from macro.report import MacroReport, WeoFetch, build_report
from macro.snapshot import CountrySnapshot, _monthly

CYAN, MAGENTA, LIME, ORANGE, YELLOW, VIOLET, WHITE = (
    "#00e5ff", "#ff2bd6", "#a6ff00", "#ff9f1c", "#ffe600", "#9b5cff", "#f5f5f5")
HISTORY_YEARS = 10
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
    s = {reg: sources.load(reg, as_of, fetch) for reg in sources.SERIES}
    weo = {ind: weo_fetch(ind) for ind in sources.IMF_INDICATORS}
    year = int(as_of[:4])

    charts, forecasts = {}, []

    def add(key, title, unit, hist, color, freq="MS", imf=None, extra=(), market=None):
        fc = forecast(hist, 4 if freq == "QS" else 12, freq)
        charts[key] = _chart(title, unit, hist, fc, color, imf, extra)
        end = fc.iloc[-1]
        forecasts.append({"name": title, "unit": unit, "now": float(hist.iloc[-1]), "drift": end.drift,
                          "ar1": end.ar1, "lo": end.lo, "hi": end.hi, "ensemble": end.ensemble,
                          "imf": None if imf is None or imf.empty else float(imf.iloc[-1]),
                          "market": market, "horizon": fc.index[-1].strftime("%Y-%m")})

    for c, iso, name in (("US", "USA", "EE.UU."), ("MX", "MEX", "México")):
        d = s[c]
        imf_g = _imf_points(weo["NGDP_RPCH"], iso, year)
        imf_i = _imf_points(weo["PCPIPCH"], iso, year)
        be = _recent(_monthly(d["breakeven_10y"])) if "breakeven_10y" in d else None
        add(f"{c}_infl", f"Inflación {name}", "%", _recent(_yoy_pct(_monthly(d["cpi"]))), MAGENTA,
            imf=imf_i, extra=[("Inflación esperada 10a (mercado)", be, YELLOW)] if be is not None else (),
            market=float(be.iloc[-1]) if be is not None else None)
        extra = [("Bono 10 años", _recent(_monthly(d["rate_10y"])), VIOLET)]
        if c == "MX":
            extra.append(("Tasa Fed (EE.UU.)", _recent(_monthly(s["US"]["policy_rate"])), WHITE))
        add(f"{c}_rate", f"Tasa de política {name}", "%", _recent(_monthly(d["policy_rate"])), CYAN, extra=extra)
        add(f"{c}_unemp", f"Desempleo {name}", "%", _recent(_monthly(d["unemployment"])), LIME)
        gdp = d["gdp"].resample("QS").last().dropna()
        add(f"{c}_gdp", f"PIB real anual {name}", "%", _recent(_yoy_pct(gdp)), ORANGE, "QS", imf=imf_g)
    add("MX_fx", "Pesos por dólar", "", _recent(_monthly(s["MX"]["fx_usd"])), YELLOW)
    g = s["GLOBAL"]
    add("brent", "Petróleo Brent (USD/barril)", "", _recent(_monthly(g["brent"])), ORANGE)
    add("copper", "Cobre (USD/tonelada)", "", _recent(_monthly(g["copper"])), MAGENTA)
    add("dollar", "Dólar amplio (índice)", "", _recent(_monthly(g["dollar"])), CYAN)
    add("vix", "VIX (miedo del mercado)", "", _recent(_monthly(g["vix"])), LIME)

    growth = sorted(r.world.growth.items(), key=lambda kv: -kv[1])
    data = {
        "as_of": r.as_of, "generated": datetime.now().strftime("%Y-%m-%d %H:%M"),
        "kpis": _kpis(r), "reasons": reasons(r, forecasts), "charts": charts, "forecasts": forecasts,
        "g20": {"labels": [k for k, _ in growth], "values": [round(v * 100, 2) for _, v in growth],
                "year": r.world.year},
        "assumptions": [{"market": a.market, "currency": a.currency, "rf": a.risk_free_usd,
                         "erp": a.equity_risk_premium, "crp": a.country_risk_premium,
                         "infl": a.expected_inflation, "g": a.terminal_growth, "coe": a.cost_of_equity()}
                        for a in r.assumptions],
        "flags": {"Mundo": r.world.flags,
                  "EE.UU.": r.us.flags + r.vs_imf[0].flags,
                  "México": r.mx.flags + r.vs_imf[1].flags + r.mx_extras.flags},
    }
    payload = json.dumps(data, ensure_ascii=False, default=float).replace("</", "<\\/")
    return HTML.replace("__DATA__", payload).replace("__ASOF__", r.as_of)


# ---------------------------------------------------------------------------
# Reasons: why each reading is where it is, from the other readings
# ---------------------------------------------------------------------------

def reasons(r: MacroReport, forecasts: list[dict]) -> dict[str, list[str]]:
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
    out = [f"Régimen {s.regime}: el PIB crece {_p(s.gdp_yoy)} contra una tendencia de {_p(s.gdp_trend)} "
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

def _kpis(r: MacroReport) -> dict[str, list[dict]]:
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
              "bad" if r.us.credit_spread >= 0.03 else "good")],
        "México": mx,
    }


def _chart(title, unit, hist, fc, color, imf, extra) -> dict:
    lines = [{"label": "Histórico", "color": color, "points": _pts(hist), "width": 2.5}]
    for label, ser, c in extra:
        lines.append({"label": label, "color": c, "points": _pts(ser), "width": 1.5})
    lines += [
        {"label": "_lo", "color": color, "points": _pts(fc["lo"]), "width": 0},
        {"label": "Banda 90%", "color": color, "points": _pts(fc["hi"]), "width": 0, "fill": True},
        {"label": "Reversión a la media (AR)", "color": color, "points": _pts(fc["ar1"]), "dash": [6, 4]},
        {"label": "Tendencia (amortiguada)", "color": ORANGE if color != ORANGE else YELLOW,
         "points": _pts(fc["drift"]), "dash": [2, 3]},
        {"label": "Promedio de modelos", "color": WHITE, "points": _pts(fc["ensemble"]), "dash": [10, 4]},
    ]
    if imf is not None and not imf.empty:
        lines.append({"label": "FMI (promedio anual)", "color": YELLOW, "points": _pts(imf), "scatter": True})
    return {"title": title, "unit": unit, "lines": lines}


def _imf_points(df: pd.DataFrame, iso: str, year: int) -> pd.Series:
    """IMF annual figures for this year and the next two, plotted mid-year."""
    if iso not in df.columns:
        return pd.Series(dtype=float)
    vals = df.loc[year:year + 2, iso].dropna()
    return pd.Series(vals.values, index=[pd.Timestamp(y, 7, 1) for y in vals.index])


def _yoy_pct(series: pd.Series) -> pd.Series:
    """% change vs the same date a year earlier; by date, not position, so a missing print (FRED has no Oct 2025 CPI) leaves a gap instead of a 13-month change."""
    return (series / series.shift(freq=pd.DateOffset(years=1)) - 1) * 100


def _recent(series: pd.Series) -> pd.Series:
    series = series.dropna()
    return series[series.index > series.index[-1] - pd.DateOffset(years=HISTORY_YEARS)]


def _pts(series: pd.Series) -> list[list]:
    return [[int(t.timestamp() * 1000), round(float(v), 3)] for t, v in series.items()]


def _p(v: float, decimals: int = 2) -> str:
    return f"{v * 100:.{decimals}f}%"


HTML = """<!doctype html>
<html lang="es" data-theme="dark">
<head>
<meta charset="utf-8">
<meta name="viewport" content="width=device-width, initial-scale=1">
<title>Panorama macro</title>
<meta name="claude:viewport-fit-sides" content="cover">
<style>
:root, :root[data-theme="dark"] {
  --bg: #000; --panel: #0b0b10; --line: #1f1f2b; --text: #f2f2f7; --muted: #8b8ba3;
  --good: #a6ff00; --bad: #ff2b6a; --neutral: #00e5ff; --accent: #ff2bd6; color-scheme: dark;
}
* { box-sizing: border-box; }
body { margin: 0; background: var(--bg); color: var(--text);
  font: 15px/1.5 -apple-system, BlinkMacSystemFont, "Segoe UI", Roboto, sans-serif; }
main { max-width: 1280px; margin: 0 auto; padding-block: 24px 64px;
  padding-left: max(16px, env(safe-area-inset-left, 0px)); padding-right: max(16px, env(safe-area-inset-right, 0px)); }
header h1 { margin: 0; font-size: 28px; letter-spacing: -0.02em; }
header h1 span { background: linear-gradient(90deg, #00e5ff, #ff2bd6, #a6ff00); -webkit-background-clip: text;
  background-clip: text; color: transparent; }
header p { margin: 4px 0 0; color: var(--muted); }
nav { position: sticky; top: env(safe-area-inset-top, 0px); z-index: 5; background: var(--bg); display: flex; gap: 8px; flex-wrap: wrap;
  padding: 12px 0; margin: 12px 0 8px; border-bottom: 1px solid var(--line); }
nav a { color: var(--text); text-decoration: none; padding: 6px 12px; border: 1px solid var(--line);
  border-radius: 999px; font-size: 13px; }
nav a:hover, nav a:focus-visible { border-color: var(--accent); outline: none; }
section { margin-top: 36px; }
h2 { font-size: 20px; margin: 0 0 14px; display: flex; align-items: center; gap: 10px; }
h2::before { content: ""; width: 10px; height: 10px; border-radius: 50%; background: var(--accent);
  box-shadow: 0 0 12px var(--accent); }
.kpis { display: grid; grid-template-columns: repeat(auto-fill, minmax(170px, 1fr)); gap: 10px; }
.kpi { background: var(--panel); border: 1px solid var(--line); border-radius: 12px; padding: 12px 14px;
  border-top: 3px solid var(--tone); }
.kpi .l { color: var(--muted); font-size: 12px; text-transform: uppercase; letter-spacing: .05em; }
.kpi .v { font-size: 22px; font-weight: 700; color: var(--tone); margin: 2px 0; }
.kpi .s { color: var(--muted); font-size: 12px; }
.grid { display: grid; grid-template-columns: repeat(auto-fit, minmax(min(100%, 520px), 1fr)); gap: 14px;
  margin-top: 14px; }
.card { background: var(--panel); border: 1px solid var(--line); border-radius: 12px; padding: 14px; min-width: 0; }
.card h3 { margin: 0 0 8px; font-size: 15px; }
.chart { position: relative; height: 280px; }
.why { margin-top: 14px; }
.why ul { margin: 0; padding-left: 18px; }
.why li { margin: 6px 0; }
.flags { display: flex; flex-wrap: wrap; gap: 6px; margin-top: 10px; }
.flag { background: rgba(255,43,106,.12); color: var(--bad); border: 1px solid rgba(255,43,106,.4);
  border-radius: 999px; padding: 3px 10px; font-size: 12px; }
.table-wrap { overflow-x: auto; }
table { width: 100%; border-collapse: collapse; font-size: 14px; font-variant-numeric: tabular-nums; }
th, td { padding: 8px 10px; border-bottom: 1px solid var(--line); text-align: right; white-space: nowrap; }
th:first-child, td:first-child { text-align: left; }
th { color: var(--muted); font-weight: 600; font-size: 12px; text-transform: uppercase; letter-spacing: .04em; }
.note { color: var(--muted); font-size: 13px; }
footer { margin-top: 40px; color: var(--muted); font-size: 12px; }
</style>
</head>
<body>
<main>
<header>
  <h1><span>Panorama macro</span> al __ASOF__</h1>
  <p>Análisis propio con datos de FRED, Banxico y el FMI. Cada bloque trae las cifras, por qué están así y hacia dónde apuntan.</p>
</header>
<nav aria-label="Secciones">
  <a href="#mundo">Mundo</a><a href="#eeuu">EE.UU.</a><a href="#mexico">México</a>
  <a href="#pronosticos">Pronósticos</a><a href="#supuestos">Supuestos de valuación</a>
</nav>
<div id="app"></div>
<footer id="foot"></footer>
</main>
<script id="data" type="application/json">__DATA__</script>
<script src="https://cdnjs.cloudflare.com/ajax/libs/Chart.js/4.4.1/chart.umd.min.js"></script>
<script>
const D = JSON.parse(document.getElementById('data').textContent);
const TONE = {good: 'var(--good)', bad: 'var(--bad)', neutral: 'var(--neutral)'};
const SECTIONS = [
  ['mundo', 'Mundo', ['brent', 'copper', 'dollar', 'vix'], true],
  ['eeuu', 'EE.UU.', ['US_infl', 'US_rate', 'US_gdp', 'US_unemp']],
  ['mexico', 'México', ['MX_infl', 'MX_rate', 'MX_gdp', 'MX_unemp', 'MX_fx']],
];
const esc = s => String(s).replace(/[&<>"]/g, c => ({'&': '&amp;', '<': '&lt;', '>': '&gt;', '"': '&quot;'}[c]));
const pct = v => (v * 100).toFixed(2) + '%';
const num = (v, u) => v == null ? '—' : v.toFixed(2) + (u === '%' ? '%' : '');
let html = '';
for (const [id, name, keys, g20] of SECTIONS) {
  html += `<section id="${id}"><h2>${name}</h2><div class="kpis">` + D.kpis[name].map(k =>
    `<div class="kpi" style="--tone:${TONE[k.tone]}"><div class="l">${esc(k.label)}</div>` +
    `<div class="v">${esc(k.value)}</div><div class="s">${esc(k.sub)}</div></div>`).join('') + '</div>';
  const flags = D.flags[name];
  if (flags.length) html += '<div class="flags">' + flags.map(f => `<span class="flag">${esc(f)}</span>`).join('') + '</div>';
  html += `<div class="card why"><h3>Por qué está así</h3><ul>${D.reasons[name].map(r => `<li>${esc(r)}</li>`).join('')}</ul></div>`;
  html += '<div class="grid">';
  if (g20) html += `<div class="card"><h3>Crecimiento ${D.g20.year} en el G20 (FMI)</h3><div class="chart"><canvas id="c_g20" role="img" aria-label="Crecimiento por país del G20"></canvas></div></div>`;
  for (const k of keys) html += `<div class="card"><h3>${esc(D.charts[k].title)}</h3><div class="chart"><canvas id="c_${k}" role="img" aria-label="${esc(D.charts[k].title)}"></canvas></div></div>`;
  html += '</div></section>';
}
html += `<section id="pronosticos"><h2>Pronósticos</h2><div class="card table-wrap"><table><thead><tr>
  <th>Indicador</th><th>Horizonte</th><th>Actual</th><th>Tendencia</th><th>Reversión (AR)</th><th>Banda 90%</th>
  <th>Promedio</th><th>FMI</th><th>Mercado</th></tr></thead><tbody>` + D.forecasts.map(f => `<tr>
  <td>${esc(f.name)}</td><td>${f.horizon}</td><td>${num(f.now, f.unit)}</td><td>${num(f.drift, f.unit)}</td>
  <td>${num(f.ar1, f.unit)}</td><td>${num(f.lo, f.unit)} a ${num(f.hi, f.unit)}</td><td><b>${num(f.ensemble, f.unit)}</b></td>
  <td>${num(f.imf, f.unit)}</td><td>${num(f.market, f.unit)}</td></tr>`).join('') + `</tbody></table>
  <p class="note"><b>Tendencia</b>: el ritmo del último año, amortiguado para no proyectar un choque para siempre. <b>Reversión (AR)</b>: modelo autorregresivo ajustado a 10 años; la serie regresa a su promedio de largo plazo,  <b>Promedio</b>: de ambos modelos. <b>Banda 90%</b>: cubre ambos modelos más el error típico del AR, sin dejar que un choque como 2020 la infle. <b>FMI</b>: último año proyectado (promedio anual). <b>Mercado</b>: inflación esperada a 10 años (breakeven), solo EE.UU. Son referencias, no certezas.</p></div></section>`;
html += `<section id="supuestos"><h2>Supuestos de valuación</h2><div class="card table-wrap"><table><thead><tr>
  <th>Mercado</th><th>Libre de riesgo (USD)</th><th>Prima de mercado</th><th>Riesgo país</th><th>Inflación esperada</th>
  <th>Crec. terminal</th><th>Costo de capital (beta 1)</th></tr></thead><tbody>` + D.assumptions.map(a => `<tr>
  <td>${esc(a.market)} (${esc(a.currency)})</td><td>${pct(a.rf)}</td><td>${pct(a.erp)}</td><td>${pct(a.crp)}</td>
  <td>${pct(a.infl)}</td><td>${pct(a.g)}</td><td><b>${pct(a.coe)}</b></td></tr>`).join('') + `</tbody></table></div>
  <div class="card why"><h3>Por qué estos supuestos</h3><ul>${D.reasons['Supuestos'].map(r => `<li>${esc(r)}</li>`).join('')}</ul></div></section>`;
document.getElementById('app').innerHTML = html;
document.getElementById('foot').textContent = `Generado ${D.generated} con python -m macro dashboard. No es recomendación de inversión.`;

if (window.Chart) {
  Chart.defaults.color = '#8b8ba3';
  Chart.defaults.borderColor = '#1f1f2b';
  Chart.defaults.font.family = getComputedStyle(document.body).fontFamily;
  const year = v => new Date(v).getFullYear();
  for (const [key, c] of Object.entries(D.charts)) {
    const datasets = c.lines.map(l => ({
      label: l.label, data: l.points.map(([x, y]) => ({x, y})), borderColor: l.color,
      backgroundColor: l.fill ? l.color + '2e' : l.color, borderWidth: l.width ?? 2, borderDash: l.dash || [],
      pointRadius: l.scatter ? 5 : 0, showLine: !l.scatter, fill: l.fill ? '-1' : false, tension: 0.15,
    }));
    new Chart(document.getElementById('c_' + key), {
      type: 'line', data: {datasets},
      options: {
        maintainAspectRatio: false, animation: false, interaction: {mode: 'nearest', intersect: false},
        scales: {x: {type: 'linear', ticks: {callback: year, maxTicksLimit: 8}, grid: {display: false}},
                 y: {ticks: {callback: v => +v.toFixed(2) + (c.unit === '%' ? '%' : '')}}},
        plugins: {
          legend: {labels: {boxWidth: 12, filter: i => !i.text.startsWith('_')}},
          tooltip: {filter: i => !i.dataset.label.startsWith('_'), callbacks: {
            title: i => new Date(i[0].parsed.x).toISOString().slice(0, 7),
            label: i => `${i.dataset.label}: ${i.parsed.y.toFixed(2)}${c.unit === '%' ? '%' : ''}`}},
        },
      },
    });
  }
  new Chart(document.getElementById('c_g20'), {
    type: 'bar',
    data: {labels: D.g20.labels, datasets: [{label: 'Crecimiento real %', data: D.g20.values,
      backgroundColor: D.g20.labels.map(l => l === 'MEX' ? '#ff2bd6' : l === 'USA' ? '#00e5ff' : D.g20.values[D.g20.labels.indexOf(l)] < 0 ? '#ff2b6a' : '#a6ff0099'),
      borderRadius: 4}]},
    options: {maintainAspectRatio: false, animation: false, plugins: {legend: {display: false}},
      scales: {x: {grid: {display: false}}, y: {ticks: {callback: v => v + '%'}}}},
  });
}
</script>
</body>
</html>
"""
