"""Put it together: snapshots, IMF comparison and valuation assumptions, as JSON and as a Spanish report."""

from __future__ import annotations

from collections.abc import Callable

import pandas as pd
from pydantic import BaseModel

from macro import sources
from macro.assumptions import DEFAULT_ERP, MarketAssumptions, mx_assumptions, us_assumptions
from macro.snapshot import (Comparison, CountrySnapshot, GlobalSnapshot, MexicoExtras, build_country,
                            build_global, build_mexico_extras, compare_with_imf)

WeoFetch = Callable[[str], pd.DataFrame]


class MacroReport(BaseModel):
    as_of: str
    us: CountrySnapshot
    mx: CountrySnapshot
    mx_extras: MexicoExtras
    world: GlobalSnapshot
    vs_imf: list[Comparison]
    assumptions: list[MarketAssumptions]


def build_report(as_of: str, erp: float = DEFAULT_ERP, fetch: sources.Fetch = sources.fetch,
                 weo_fetch: WeoFetch = sources.imf_weo) -> MacroReport:
    us_s, mx_s = sources.load("US", as_of, fetch), sources.load("MX", as_of, fetch)
    weo = {ind: weo_fetch(ind) for ind in sources.IMF_INDICATORS}
    us, mx = build_country("US", as_of, us_s), build_country("MX", as_of, mx_s)
    extras = build_mexico_extras(mx_s, us_s, mx, us)
    world = build_global(as_of, sources.load("GLOBAL", as_of, fetch), weo)

    year = int(as_of[:4])
    mx_infl = weo["PCPIPCH"].loc[year + 1:year + 5, "MEX"].dropna()
    if mx_infl.empty:
        raise sources.DataError(f"IMF WEO has no Mexico inflation projection after {year}")
    us_a = us_assumptions(us, erp)
    mx_a = mx_assumptions(mx, us_a, float(mx_infl.mean()) / 100, erp, extra_flags=extras.flags)
    return MacroReport(
        as_of=as_of[:10], us=us, mx=mx, mx_extras=extras, world=world,
        vs_imf=[compare_with_imf(us, "USA", weo), compare_with_imf(mx, "MEX", weo)],
        assumptions=[us_a, mx_a],
    )


def render(r: MacroReport) -> str:
    """Markdown report in Spanish."""
    lines = [f"# Panorama macro al {r.as_of}", "", "## Mundo", "",
             f"- Ciclo: **{r.world.cycle}**. El {_pct(r.world.g20_breadth, 0)} del G20 crece más rápido que el año pasado; "
             f"mediana de crecimiento {_pct(r.world.g20_growth_median)} (FMI {r.world.year}).",
             f"- VIX {r.world.vix:.1f} | dólar {_pct(r.world.dollar_yoy)} anual | Brent {_pct(r.world.brent_yoy)} | "
             f"cobre {_pct(r.world.copper_yoy)}",
             _flag_line(r.world.flags), ""]
    for snap, cmp in ((r.us, r.vs_imf[0]), (r.mx, r.vs_imf[1])):
        name = "Estados Unidos" if snap.country == "US" else "México"
        lines += [f"## {name}", "",
                  f"- Régimen: **{snap.regime}**",
                  f"- Crecimiento: PIB real {_pct(snap.gdp_yoy)} anual vs tendencia {_pct(snap.gdp_trend)} "
                  f"(FMI {cmp.year}: {_pct(cmp.gdp_imf)})",
                  f"- Inflación: {_pct(snap.inflation_yoy)} (hace 6m {_pct(snap.inflation_yoy_6m_ago)}; "
                  f"FMI {cmp.year}: {_pct(cmp.inflation_imf)})",
                  f"- Tasas: política {_pct(snap.policy_rate)} | real {_pct(snap.real_policy_rate)} | "
                  f"10 años {_pct(snap.rate_10y)} | curva {_pct(snap.curve)}",
                  f"- Desempleo {_pct(snap.unemployment)} (brecha Sahm {_pct(snap.sahm_gap)})"]
        if snap.country == "MX":
            e = r.mx_extras
            lines.append(f"- Peso: {e.fx_usd:.2f} por dólar ({_pct(e.fx_yoy)} anual) | brecha real vs 10 años "
                         f"{_pct(e.real_fx_gap)} | carry vs EE.UU. {_pct(e.carry_vs_us)} (real {_pct(e.real_carry_vs_us)})")
        lines += [_flag_line(snap.flags + cmp.flags + (r.mx_extras.flags if snap.country == "MX" else [])), ""]

    lines += ["## Supuestos de valuación", "",
              "| Mercado | Libre de riesgo (USD) | Prima de mercado | Riesgo país | Inflación esperada | "
              "Crec. terminal | Costo de capital (beta 1) |",
              "|---|---|---|---|---|---|---|"]
    for a in r.assumptions:
        lines.append(f"| {a.market} ({a.currency}) | {_pct(a.risk_free_usd)} | {_pct(a.equity_risk_premium)} | "
                     f"{_pct(a.country_risk_premium)} | {_pct(a.expected_inflation)} | {_pct(a.terminal_growth)} | "
                     f"{_pct(a.cost_of_equity())} |")
    return "\n".join(lines) + "\n"


def _pct(v: float, decimals: int = 2) -> str:
    return f"{v * 100:.{decimals}f}%"


def _flag_line(flags: list[str]) -> str:
    return "- Alertas: " + ("; ".join(flags) if flags else "ninguna")
