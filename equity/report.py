"""Company report in Spanish: verdict, thesis, valuation, financial health, sensitivity and risks."""

from __future__ import annotations

from equity.dcf import Valuation
from macro.assumptions import MarketAssumptions

REGIME = {"goldilocks": "goldilocks", "reflation": "reflación", "stagflation": "estanflación", "slowdown": "desaceleración"}
VERDICT = {"comprar": "COMPRAR", "mantener": "MANTENER", "vender": "VENDER"}


def thesis(v: Valuation) -> list[str]:
    h, x = v.health, v.inputs
    lines = [f"Los ingresos crecieron {_p(h['revenue_cagr_3y'])} anual en tres años con margen operativo de "
             f"{_p(h['operating_margin'])} y ROIC de {_p(h['roic'])}"
             + (f", contra un costo de capital de {_p(x.wacc)}: crea valor." if h["roic"] and h["roic"] > x.wacc
                else f", contra un costo de capital de {_p(x.wacc)}: no cubre su costo de capital." if h["roic"] else "."),
             f"Nuestro DCF da {_m(v.value_per_share)} por acción contra {_m(x.price)} de mercado "
             f"({v.upside:+.1%}), con WACC de {_p(x.wacc)} y crecimiento terminal de {_p(x.terminal_growth)}."]
    if v.implied_growth is not None:
        lines.append(f"El precio actual implica crecer {_p(v.implied_growth)} anual los próximos cinco años, contra "
                     f"{_p(x.growth)} que supone el modelo"
                     + (": el mercado es más optimista que nosotros." if v.implied_growth > x.growth + 0.01 else
                        ": el mercado es más pesimista que nosotros." if v.implied_growth < x.growth - 0.01 else
                        ": coincide con nuestro supuesto."))
    return lines


def risks(v: Valuation, a: MarketAssumptions) -> list[str]:
    h, x, out = v.health, v.inputs, []
    share = v.pv_terminal / v.enterprise_value
    if share > 0.7:
        out.append(f"El valor terminal es {share:.0%} del valor de la empresa: la valuación depende sobre todo del largo plazo.")
    if h["capex_to_revenue"] is not None and h["capex_to_revenue"] > 0.15:
        out.append(f"La inversión en activos fijos es {_p(h['capex_to_revenue'])} de los ingresos: si no rinde, el ROIC baja.")
    if h["sbc_to_revenue"] is not None and h["sbc_to_revenue"] > 0.05:
        out.append(f"La compensación en acciones es {_p(h['sbc_to_revenue'])} de los ingresos: diluye al accionista.")
    if h["interest_coverage"] is not None and h["interest_coverage"] < 3:
        out.append(f"La utilidad operativa cubre {h['interest_coverage']:.1f} veces los intereses: deuda alta.")
    if x.beta > 1.3:
        out.append(f"Beta de {x.beta:.2f}: más volátil que el mercado.")
    spread = v.sensitivity["+1 pp"]["+0 pp"] / v.value_per_share - 1
    out.append(f"Si las tasas suben 100 pb el valor por acción cambia {spread:+.0%}.")
    out += [f"Macro ({a.market}): {f}." for f in a.flags]
    return out


def render(v: Valuation, a: MarketAssumptions) -> str:
    x, h = v.inputs, v.health
    hist = [f"| {y[:4]} | {_m(r, 0)} | {_p(mg)} |" for y, r, mg in
            zip(v.history["years"], v.history["revenue"], v.history["margin"])]
    proj = [f"| {y.year} | {_p(y.growth)} | {_m(y.revenue, 0)} | {_m(y.fcff, 0)} |" for y in v.years]
    sens = [f"| WACC {dw} | " + " | ".join(_m(val) for val in row.values()) + " |" for dw, row in v.sensitivity.items()]
    comps = [f"| {k} | {_m(val)} | {val / x.price - 1:+.1%} |" for k, val in v.comparables.items()]
    peers = ", ".join(v.peers) or "sin comparables"
    return "\n".join([
        f"# {v.name} ({v.ticker}): {VERDICT[v.verdict]}", "",
        f"Corte {v.as_of}. Cifras en {v.currency}"
        + (f"; base de ingresos: últimos doce meses al {v.ttm_end}" if v.ttm_end else "") + ". No es recomendación de inversión.", "",
        f"**Valor por acción {_m(v.value_per_share)} vs precio {_m(x.price)} ({v.upside:+.1%}).**", "",
        "## Tesis", "", *[f"{i}. {t}" for i, t in enumerate(thesis(v), 1)], "",
        "## Valuación", "",
        "| Supuesto | Valor |", "| --- | --- |",
        f"| Crecimiento años 1-5 | {_p(x.growth)} |", f"| Crecimiento terminal | {_p(x.terminal_growth)} |",
        f"| Margen operativo | {_p(x.margin)} |", f"| Impuesto efectivo → marginal | {_p(x.tax_effective)} → {_p(x.tax_marginal)} |",
        f"| Ventas por unidad de capital | {x.sales_to_capital:.2f} |", f"| ROIC terminal | {_p(x.terminal_roic)} |",
        f"| Beta | {x.beta:.2f} |", f"| Costo de capital accionario | {_p(x.cost_of_equity)} |",
        f"| Costo de deuda antes de impuestos | {_p(x.cost_of_debt)} |", f"| WACC | {_p(x.wacc)} |", "",
        "| Año | Crecimiento | Ingresos | Flujo libre |", "| --- | --- | --- | --- |", *proj, "",
        f"Valor de la empresa {_m(v.enterprise_value, 0)} (terminal {v.pv_terminal / v.enterprise_value:.0%}); "
        f"más caja {_m(x.cash, 0)}, menos deuda {_m(x.debt, 0)}: capital {_m(v.equity_value, 0)} entre "
        f"{x.shares / 1e6:,.0f} millones de acciones.", "",
        f"Comparables ({peers}):", "", "| Método | Valor por acción | Vs precio |", "| --- | --- | --- |", *comps, "",
        "## Salud financiera", "",
        "| Año fiscal | Ingresos | Margen operativo |", "| --- | --- | --- |", *hist, "",
        f"- Margen de flujo libre {_p(h['fcf_margin'])}; ROIC {_p(h['roic'])}; caja neta {_m(h['net_cash'], 0)}.",
        f"- Cobertura de intereses {_x(h['interest_coverage'])}; inversión {_p(h['capex_to_revenue'])} de ingresos; "
        f"compensación en acciones {_p(h['sbc_to_revenue'])}.", "",
        "## Sensibilidad", "", "Valor por acción según WACC (filas) y crecimiento de los años 1-5 (columnas).", "",
        "| | −5 pp | base | +5 pp |", "| --- | --- | --- | --- |", *sens, "",
        "## Riesgos", "", *[f"- {r}" for r in risks(v, a)], "",
        "## Supuestos macro", "",
        f"Mercado {a.market} ({a.currency}), régimen {REGIME.get(a.regime, a.regime)}: libre de riesgo {_p(a.risk_free_usd)}, prima de mercado "
        f"{_p(a.equity_risk_premium)}, riesgo país {_p(a.country_risk_premium)}, inflación esperada {_p(a.expected_inflation)}.",
    ]) + "\n"


def _p(v: float | None) -> str:
    return "—" if v is None else f"{v * 100:.1f}%"


def _x(v: float | None) -> str:
    return "sin deuda" if v is None else f"{v:.1f}x"


def _m(v: float | None, decimals: int = 2) -> str:
    if v is None:
        return "—"
    if abs(v) >= 1e9:
        return f"{v / 1e9:,.1f} mil millones"
    return f"{v:,.{decimals}f}"
