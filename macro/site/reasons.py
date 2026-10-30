"""Why each reading is where it is, from the other readings: rules over our own numbers, not outside narrative."""

from __future__ import annotations

from macro.markets import Markets
from macro.neutral import Neutral
from macro.policy import RatesOutlook
from macro.report import MacroReport
from macro.site.payload import REGIME_ES, REGIME_TEXT, _p, _scenarios
from macro.snapshot import CountrySnapshot


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
                         f"en {x.policy:.2f}%: {x.gap:+.2f} pp, postura {x.stance}. "
                         f"La regla de Taylor, con inflación de {x.inflation:.2f}% y desempleo de {x.unemployment:.2f}% contra {x.unemployment_star:.2f}% de largo plazo, pide {x.taylor:.2f}%.")
    out["EE.UU."].append(f"La curva (3m10y en {m.us_3m10y:+.2f} pp) da {m.recession_prob:.0%} de probabilidad de recesión en "
                         f"12 meses, y el bono a 2 años ({m.us_curve.at('2y'):.2f}%) "
                         + ("descuenta recortes de la Fed." if m.us_policy_gap < -0.15 else "descuenta alzas de la Fed."
                            if m.us_policy_gap > 0.15 else "no descuenta cambios grandes en la tasa."))
    e = r.mx_extras
    out["México"] += [
        f"El carry contra EE.UU. es de {_p(e.carry_vs_us)} ({_p(e.real_carry_vs_us)} real): "
        + ("pagar más que la Fed atrae dinero de fuera a pesos y sostiene al peso." if e.real_carry_vs_us > 0.01
           else "el premio por estar en pesos es chico, el peso queda vulnerable a salidas de capital."),
        f"El peso real (tipo de cambio real efectivo del BIS, contra todos sus socios) está {_p(abs(e.real_fx_gap))} "
        f"{'más fuerte' if e.real_fx_gap < 0 else 'más débil'} que su promedio de 10 años; solo contra el dólar, "
        f"{_p(abs(e.real_fx_gap_bilateral))} {'más fuerte' if e.real_fx_gap_bilateral < 0 else 'más débil'}. " + ("Un peso caro abarata importaciones y ayuda a bajar la inflación, pero resta competitividad "
                                   "a exportadores y al turismo." if e.real_fx_gap < 0
                                   else "Un peso barato encarece importaciones y empuja precios, pero favorece a exportadores."),
    ]
    a_us, a_mx = r.assumptions
    out["Supuestos"] = [
        f"El costo de capital en dólares ({_p(a_us.cost_of_equity())}) sale de la tasa a 10 años de EE.UU. "
        f"({_p(a_us.risk_free_usd)}) más la prima de mercado implícita del S&P 500 que publica Damodaran "
        f"({_p(a_us.equity_risk_premium)}; antes usábamos un 5% fijo).",
        f"En México se suma un riesgo país de {_p(a_mx.country_risk_premium)}: el spread de impago, medido con el spread de "
        f"bonos corporativos emergentes ({_p(a_mx.default_spread)}, porque no hay CDS soberano gratuito), por "
        f"{a_mx.equity_bond_vol:.2f}, cuánto más volátil es el IPC que el Bono M a 10 años en 5 años de datos. "
        f"Después se convierte a pesos una sola vez, con la inflación esperada de la encuesta de Banxico "
        f"({_p(a_mx.expected_inflation)} a 1–4 años) contra la de EE.UU. ({_p(a_us.expected_inflation)}): exige {_p(a_mx.cost_of_equity())}.",
        f"El crecimiento terminal es el crecimiento real de largo plazo del consenso (Fed en EE.UU., encuesta de Banxico a 10 años "
        f"en México) más la inflación esperada de largo plazo, con tope en la tasa a 10 años local: {_p(a_us.terminal_growth)} en "
        f"EE.UU. ({_p(a_us.real_growth_long_run)} real; nuestra tendencia sin 2020-2021 da {_p(a_us.real_growth_ours)}) y "
        f"{_p(a_mx.terminal_growth)} en México ({_p(a_mx.real_growth_long_run)} real; la nuestra da {_p(a_mx.real_growth_ours)}). "
        "Si una empresa necesita crecer más que eso para valer su precio, la valuación es exigente.",
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
    outside = "la Fed de Cleveland" if name == "EE.UU." else "la encuesta de Banxico"
    view = f"Pronóstico de inflación a {f['horizon']}: {f['ensemble']:.2f}%"
    if f["market"] is not None:
        view += (f", promedio de nuestra reversión a la media ({f['ar1']:.2f}%) y de lo que espera {outside} a 12 meses "
                 f"({f['market']:.2f}%); nuestra tendencia pura da {f['drift']:.2f}%")
    else:
        view += f" (promedio de modelos; reversión a la media {f['ar1']:.2f}%, tendencia {f['drift']:.2f}%)"
    if f["imf"] is not None:
        view += f". El FMI espera {f['imf']:.2f}% en promedio el próximo año"
    out.append(view + ".")
    return out


def _rate_reasons(x: RatesOutlook, n: dict[str, Neutral], r: MacroReport) -> list[str]:
    f0 = x.fed[0]
    h_us, h_mx = x.horizons["US"]["12m"], x.horizons["MX"]["12m"]
    up = lambda h: h["buckets"][1] + h["buckets"][2]
    down = lambda h: h["buckets"][-1] + h["buckets"][-2]
    out = [f"Fed: los futuros de Fed funds dan {f0['p_hike']:.0%} de probabilidad de alza, {f0['p_hold']:.0%} de mantener y "
           f"{f0['p_cut']:.0%} de recorte en la reunión del {f0['date']:%d-%m-%Y}, con tasa esperada de {f0['expected']:.2f}% "
           f"(hoy {x.fed_current:.2f}%). A 12 meses los futuros esperan {h_us['mean']:.2f}%; con la volatilidad de las opciones "
           f"(MOVE) eso es {up(h_us):.0%} de probabilidad de terminar arriba de hoy, {h_us['buckets'][0]:.0%} sin cambio y "
           f"{down(h_us):.0%} abajo. Más allá de dos reuniones usamos esta distribución y no el método de reunión por reunión, "
           "que no tiene en cuenta la incertidumbre.",
           f"Nuestra regla de Taylor pide {n['US'].taylor:.2f}% para la Fed; el mercado espera más alzas que la regla, "
           f"porque ve la inflación ({r.us.inflation_yoy * 100:.1f}%) por encima de la meta por más tiempo." if h_us["mean"] > n["US"].taylor + 0.25 else
           f"Nuestra regla de Taylor pide {n['US'].taylor:.2f}% para la Fed, en línea con lo que descuentan los futuros."]
    if x.mx_meetings:
        m0 = x.mx_meetings[0]
        out.append(f"Banxico: la curva de Cetes, descontando su prima por plazo histórica, da {m0['p_hold']:.0%} de mantener, "
                   f"{m0['p_cut']:.0%} de recorte y {m0['p_hike']:.0%} de alza el {m0['date']:%d-%m-%Y}. No hay futuros ni opciones "
                   "de TIIE gratuitos (MexDer es de pago), así que esta lectura es aproximada; el pronóstico la promedia con la encuesta de Banxico. "
                   f"Que noviembre se vea casi seguro sin cambio y a 12 meses la curva apunte a {h_mx['mean']:.2f}% no se contradice: "
                   "el mercado no espera mover la tasa ya, sino más adelante, y los plazos largos de Cetes traen además prima por plazo.")
    out.append(f"Volatilidad: el MOVE (opciones de Treasuries) está en {x.move:.0f} pb al año. Con él la tasa de la Fed a 12 meses tiene "
               f"una media de {h_us['mean']:.2f}% y una desviación de {h_us['sigma']:.2f} pp; la de Banxico, {h_mx['mean']:.2f}% ± {h_mx['sigma']:.2f} pp "
               "(escalada por la volatilidad observada de los Cetes, sin opciones gratuitas en México). Esas son las bandas de los pronósticos de tasas.")
    term = "con pendiente positiva (calma)" if x.vix["vix3m"] > x.vix["vix"] else "invertida (estrés de corto plazo)"
    skew = f" El sesgo de opciones de SPY a un mes (put 25Δ − call 25Δ) es {x.spy_skew['skew']:.1f} puntos de volatilidad." if x.spy_skew else ""
    out.append(f"Acciones: la curva del VIX ({x.vix['vix9d']:.1f} a 9 días, {x.vix['vix']:.1f} a 1 mes, {x.vix['vix3m']:.1f} a 3 y "
               f"{x.vix['vix6m']:.1f} a 6) está {term}; las opciones implican {x.p_spx_down10:.1%} de probabilidad de que el S&P 500 caiga más de "
               f"10% en un mes.{skew} El peso tiene una volatilidad realizada de {x.usdmxn_vol:.1f}% anual a 3 meses (no hay opciones de USD/MXN gratuitas).")
    a_us, a_mx = r.assumptions
    sc = {c: _scenarios(x.horizons[c]["12m"], now, a.cost_of_equity()) for c, now, a in (("US", x.fed_current, a_us), ("MX", x.mx_current, a_mx))}
    out.append("Escenarios de costo de capital a 12 meses (sensibilidad de 0.5 de la tasa a 10 años a la sorpresa en la tasa de política): "
               + "; ".join(f"{'EE.UU.' if c == 'US' else 'México'} " + ", ".join(
                   f"{ {'cut': 'recorte', 'hold': 'sin cambio', 'hike': 'alza'}[z['scenario']]} {z['prob']:.0%} → {z['coe'] * 100:.2f}%" for z in sc[c])
                 for c in ("US", "MX")) + ".")
    return out
