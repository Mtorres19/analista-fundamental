"""Trade, external accounts, public finances, activity and credit-risk gauges, read into the peso and country risk.

No free source serves Mexico's sovereign CDS, so country risk is read from the Mexico-US 10y spread (markets.py)
and two credit gauges on FRED: the ICE BofA EM corporate OAS and the US high-yield OAS.
Money amounts are USD billions; shares of GDP and rates are percent.
"""

from __future__ import annotations

import pandas as pd
from pydantic import BaseModel

from macro import sources
from macro.markets import Markets
from macro.report import MacroReport

IMF_FISCAL = {"BCA_NGDPD": "Cuenta corriente", "GGXCNL_NGDP": "Balance fiscal", "GGXWDG_NGDP": "Deuda bruta"}


class Economy(BaseModel):
    # United States
    us_trade_12m: float           # goods & services balance, last 12 months
    us_ca_4q: float               # current account, last 4 quarters
    us_ip_yoy: float
    us_retail_yoy: float
    us_payrolls_3m: float         # average monthly change, thousands
    us_sentiment: float
    # Mexico
    mx_goods_4q: float            # goods exports minus imports, last 4 quarters
    mx_ca_4q: float
    mx_remit_12m: float
    mx_remit_yoy: float
    mx_reserves: float
    mx_reserves_yoy: float
    mx_igae_yoy: float
    # Risk
    em_oas: float
    em_oas_1y: float              # change over a year, pp
    hy_oas: float
    hy_oas_1y: float
    # IMF, current year: indicator -> {"EE.UU.", "México", "Mediana G20"} -> % GDP
    imf: dict[str, dict[str, float]]
    year: int
    charts: dict[str, list[list]]  # series for the page, [ms, value]

    @property
    def us_twin(self) -> float:
        """Current account plus fiscal balance, % GDP (both negative = twin deficits)."""
        return self.imf["BCA_NGDPD"]["EE.UU."] + self.imf["GGXCNL_NGDP"]["EE.UU."]

    @property
    def flags(self) -> dict[str, list[str]]:
        us, mx, world = [], [], []
        if self.imf["BCA_NGDPD"]["EE.UU."] < 0 and self.imf["GGXCNL_NGDP"]["EE.UU."] < 0 and self.us_twin < -8:
            us.append(f"déficits gemelos de {abs(self.us_twin):.1f}% del PIB (cuenta corriente + fiscal)")
        if self.us_payrolls_3m < 0:
            us.append("el empleo formal se está contrayendo (promedio de 3 meses)")
        if self.hy_oas >= 5:
            world.append(f"estrés de crédito: spread high yield en {self.hy_oas:.1f} pp")
        if self.imf["BCA_NGDPD"]["México"] < -3:
            mx.append("déficit de cuenta corriente mayor a 3% del PIB")
        if self.mx_remit_yoy < -0.05:
            mx.append(f"remesas cayendo {abs(self.mx_remit_yoy):.0%} anual")
        if self.mx_igae_yoy < 0:
            mx.append("actividad (IGAE) cayendo a tasa anual")
        return {"EE.UU.": us, "México": mx, "Mundo": world}


def build_economy(r: MacroReport, weo: dict[str, pd.DataFrame], fetch: sources.Fetch = sources.fetch) -> Economy:
    as_of, year = r.as_of, int(r.as_of[:4])
    us, mx = sources.load("US_ECON", as_of, fetch), sources.load("MX_ECON", as_of, fetch)
    risk = sources.load("RISK", as_of, fetch)
    yoy = lambda s, n: float(s.iloc[-1] / s.iloc[-1 - n] - 1)
    m = lambda s: s.resample("MS").last().dropna()
    goods = (mx["exports"] - mx["imports"]).dropna()
    remit_12m = m(mx["remittances"]).rolling(12).sum().dropna()
    reserves = m(mx["reserves"])
    imf = {}
    for ind in IMF_FISCAL:
        df = weo[ind]
        row = df.loc[year] if year in df.index else None
        if row is None or pd.isna(row.get("USA")) or pd.isna(row.get("MEX")):
            raise sources.DataError(f"IMF WEO {ind}: no US/Mexico value for {year}")
        imf[ind] = {"EE.UU.": float(row["USA"]), "México": float(row["MEX"]),
                    "Mediana G20": float(row.reindex(list(sources.G20)).median())}
    bn = lambda s: s / 1000
    since = pd.Timestamp(as_of) - pd.DateOffset(years=10)
    pts = lambda s: [[int(t.timestamp() * 1000), round(float(v), 3)] for t, v in s[s.index > since].items()]
    oas = lambda s, back: float(s.iloc[-1] - s.asof(s.index[-1] - pd.DateOffset(years=back)))
    return Economy(
        us_trade_12m=float(bn(us["trade_balance"].iloc[-12:].sum())),
        us_ca_4q=float(bn(us["current_account"].iloc[-4:].sum())),
        us_ip_yoy=yoy(m(us["industrial_production"]), 12), us_retail_yoy=yoy(m(us["retail_sales"]), 12),
        us_payrolls_3m=float(m(us["payrolls"]).diff().iloc[-3:].mean()), us_sentiment=float(us["sentiment"].iloc[-1]),
        mx_goods_4q=float(bn(goods.iloc[-4:].sum())), mx_ca_4q=float(bn(mx["current_account"].iloc[-4:].sum())),
        mx_remit_12m=float(bn(remit_12m.iloc[-1])), mx_remit_yoy=yoy(remit_12m, 12),
        mx_reserves=float(bn(reserves.iloc[-1])), mx_reserves_yoy=yoy(reserves, 12), mx_igae_yoy=yoy(m(mx["igae"]), 12),
        em_oas=float(risk["em_corp_oas"].iloc[-1]), em_oas_1y=oas(risk["em_corp_oas"], 1),
        hy_oas=float(risk["us_hy_oas"].iloc[-1]), hy_oas_1y=oas(risk["us_hy_oas"], 1),
        imf=imf, year=year,
        charts={"us_trade": pts(bn(us["trade_balance"])), "mx_goods": pts(bn(goods)),
                "mx_remit": pts(bn(remit_12m)), "mx_reserves": pts(bn(reserves)),
                "em_oas": pts(risk["em_corp_oas"].dropna()), "hy_oas": pts(risk["us_hy_oas"].dropna())},  # daily
    )


def reasons(e: Economy, mk: Markets, r: MacroReport) -> dict[str, list[str]]:
    """External balance, public finances and credit risk, read into the dollar, the peso and country risk: {"Comercio", "Riesgo"}."""
    us_ca, us_fb, us_debt = (e.imf[k]["EE.UU."] for k in ("BCA_NGDPD", "GGXCNL_NGDP", "GGXWDG_NGDP"))
    mx_ca, mx_fb, mx_debt = (e.imf[k]["México"] for k in ("BCA_NGDPD", "GGXCNL_NGDP", "GGXWDG_NGDP"))
    crp = r.assumptions[1].country_risk_premium * 100
    out = [
        f"EE.UU. tiene déficit comercial de {abs(e.us_trade_12m):,.0f} mil millones de dólares en 12 meses, cuenta corriente "
        f"de {us_ca:.1f}% y balance fiscal de {us_fb:.1f}% del PIB (FMI {e.year}): déficits gemelos de {abs(e.us_twin):.1f}% del PIB. "
        f"Con deuda de {us_debt:.0f}% del PIB, el mercado pide prima por plazo, lo que ayuda a explicar un bono a 10 años de "
        f"{r.us.rate_10y * 100:.2f}% con la Fed en {r.us.policy_rate * 100:.2f}%.",
        f"México tiene balanza de mercancías de {e.mx_goods_4q:+,.1f} mil millones de dólares en 4 trimestres "
        f"({'superávit' if e.mx_goods_4q >= 0 else 'déficit'}) y cuenta corriente de {mx_ca:.1f}% del PIB según el FMI. "
        f"Las remesas suman {e.mx_remit_12m:,.1f} mil millones en 12 meses ({e.mx_remit_yoy:+.1%} anual) y las reservas "
        f"{e.mx_reserves:,.1f} mil millones ({e.mx_reserves_yoy:+.1%}). "
        + ("Un balance externo cercano al equilibrio, remesas y reservas amplias reducen la necesidad de capital de fuera "
           "y respaldan al peso." if mx_ca > -3 else "Un déficit externo amplio deja al peso dependiente de que siga entrando capital."),
        f"Las finanzas públicas de México muestran balance de {mx_fb:.1f}% y deuda de {mx_debt:.0f}% del PIB, contra "
        f"{us_fb:.1f}% y {us_debt:.0f}% en EE.UU. "
        + ("El déficit fiscal mexicano es el punto a vigilar para la calificación." if mx_fb < -3 else
           "El nivel de deuda no es hoy el principal riesgo."),
    ]
    risk = [
        f"Riesgo país: no hay una fuente gratuita del CDS soberano de México, así que lo medimos con el diferencial del bono a "
        f"10 años contra el Treasury ({mk.mx_spread_10y:.2f} pp, que también paga la prima cambiaria del peso) y el spread "
        f"de bonos corporativos emergentes ({e.em_oas:.2f} pp, {e.em_oas_1y:+.2f} pp en un año), que es el que usamos como "
        f"spread de impago. Multiplicado por la volatilidad relativa de acciones contra bonos da un riesgo país de {crp:.2f} pp "
        f"para la valuación.",
    ]
    out += [        f"El spread high yield de EE.UU. está en {e.hy_oas:.2f} pp ({e.hy_oas_1y:+.2f} pp en un año): "
        + ("crédito caro, señal de estrés." if e.hy_oas >= 5 else "crédito barato, sin estrés; el mercado no ve quiebras masivas."),
        f"Actividad: producción industrial de EE.UU. {e.us_ip_yoy:+.1%} anual, ventas minoristas {e.us_retail_yoy:+.1%}, "
        f"empleo {e.us_payrolls_3m:+,.0f} mil plazas al mes (promedio 3 meses) y confianza del consumidor en {e.us_sentiment:.1f}. "
        f"En México el IGAE va {e.mx_igae_yoy:+.1%} anual.",
    ]
    return {"Comercio": out + risk, "Riesgo": risk}
