import pandas as pd
import pytest

from macro import sources
from macro.report import build_report, render

LEVELS = {"DGS10": 4.2, "DFF": 4.3, "T10YIE": 2.3, "BAA10Y": 1.8, "IRLTLT01MXM156N": 9.0,
          "SF61745": 8.0, "LRHUTTTTMXM156S": 2.8, "UNRATE": 4.0, "VIXCLS": 18.0}
# Index series and their annual growth rate.
GROWING = {"CPIAUCSL": 0.03, "SP1": 0.04, "GDPC1": 0.02, "NGDPRSAXDCMXQ": 0.01,
           "DEXMXUS": 0.0, "DTWEXBGS": 0.0, "DCOILBRENTEU": 0.0, "PCOPPUSDM": 0.0}


# Curves: an inverted Treasury curve (3m 5.0 > 10y 4.2), real 10y above 2%, a normal Mexican curve.
CURVES = {"DGS1MO": 5.0, "DGS3MO": 5.0, "DGS6MO": 4.9, "DGS1": 4.8, "DGS2": 4.5, "DGS3": 4.4, "DGS5": 4.3,
          "DGS7": 4.25, "DGS20": 4.4, "DGS30": 4.5, "DFII5": 2.1, "DFII10": 2.2, "DFII30": 2.3,
          "DFII7": 2.15, "DFII20": 2.25, "SF331451": 7.9,
          "SF45470": 8.0, "SF45471": 8.1, "SF45472": 8.2, "SF45473": 8.3, "SF43883": 8.6, "SF43886": 8.8,
          "SF44071": 9.0, "SF45384": 9.3, "SF60696": 9.5,
          "SF61592": 4.0, "SF43924": 4.2, "SF46958": 4.4, "SF46961": 4.5}
# Price vector: every bucket priced at par (dirty 100, Udibonos 100 UDIs at UDI = 8) with whole coupon periods,
# so each yield equals its coupon: Bonos 8.6..9.5, Udibonos 4.0..4.5.
VECTOR = {"SF349889": 8.4, "SF349886": 728, "SP68257": 8.0}
for ids, cpn, periods in ((("SF45427", "SF45449", "SF45475"), 8.6, 6), (("SF45428", "SF45451", "SF45476"), 8.8, 10),
                          (("SF45429", "SF45453", "SF45477"), 8.9, 14), (("SF45430", "SF45455", "SF45478"), 9.0, 20),
                          (("SF45431", "SF45457", "SF45479"), 9.3, 40), (("SF60720", "SF60722", "SF60723"), 9.5, 56),
                          (("SF61784", "SF61786", "SF61787"), 4.0, 6), (("SF45432", "SF45459", "SF45480"), 4.2, 20),
                          (("SF50761", "SF50766", "SF50763"), 4.4, 40), (("SF50762", "SF50768", "SF50764"), 4.5, 60)):
    VECTOR.update({ids[0]: 182 * periods, ids[1]: 800.0 if cpn < 5 else 100.0, ids[2]: cpn})

# Activity, external and risk series: flat levels (zero growth) are enough for the cross-feeds under test.
ECON = {"BOPGSTB": -60000, "IEABC": -250000, "INDPRO": 100, "RSAFS": 700000, "PAYEMS": 150000, "UMCSENT": 60,
        "EXPINF1YR": 2.5, "SE44352": -2000, "SE44355": 150000, "SE44374": 140000, "SE27803": 5000, "SF43707": 230000,
        "SR17692": 110, "BAMLEMCBPIOAS": 2.0, "BAMLH0A0HYM2": 6.0, "rstar": 0.8}


def fake_fetch(source: str, sid: str) -> pd.Series:
    quarterly = sid in ("GDPC1", "NGDPRSAXDCMXQ")
    idx = pd.date_range("2010-01-01", "2026-12-31", freq="QS" if quarterly else "MS")
    if sid in LEVELS:
        return pd.Series(LEVELS[sid], index=idx)
    if sid in CURVES:
        return pd.Series(CURVES[sid], index=idx)
    if sid in VECTOR:
        return pd.Series(float(VECTOR[sid]), index=idx)
    if sid in ECON:
        return pd.Series(float(ECON[sid]), index=idx)
    if source == "yahoo":  # indices grow 8% a year; the IPC falls 20% from June 2026
        s = pd.Series([1000 * 1.08 ** (i / 12) for i in range(len(idx))], index=idx)
        if sid == "^MXX":
            s[s.index >= "2026-06-01"] *= 0.8
        return s
    per_year = 4 if quarterly else 12
    base = 18.0 if sid == "DEXMXUS" else 100.0
    return pd.Series([base * (1 + GROWING[sid]) ** (i / per_year) for i in range(len(idx))], index=idx)


def fake_weo(indicator: str) -> pd.DataFrame:
    years = range(2020, 2032)
    if indicator == "NGDP_RPCH":
        # Half the G20 accelerate in 2026; US 2.0 -> IMF 2.0; MX 1.0 -> IMF 2.5 (we're well below).
        cols = {c: [2.0 + (0.5 if i % 2 == 0 and y == 2026 else 0) for y in years] for i, c in enumerate(sources.G20)}
        cols["USA"] = [2.0] * len(years)
        cols["MEX"] = [2.5] * len(years)
    else:
        cols = {c: [3.0] * len(years) for c in sources.G20}
        cols["MEX"] = [4.0] * len(years)
    return pd.DataFrame(cols, index=list(years))


@pytest.fixture
def report():
    return build_report("2026-06-30", erp=0.05, fetch=fake_fetch, weo_fetch=fake_weo)


def test_country_readings(report):
    assert report.us.inflation_yoy == pytest.approx(0.03, abs=1e-6)
    assert report.us.gdp_trend == pytest.approx(0.02, abs=1e-6)
    assert report.us.curve == pytest.approx(-0.001)
    assert report.mx.real_policy_rate == pytest.approx(0.04, abs=1e-6)
    assert report.mx.regime == "reflation"  # growth at trend, inflation flat
    assert "curva invertida (10a < tasa de política)" in report.us.flags
    assert "política monetaria restrictiva (tasa real > 2%)" in report.mx.flags


def test_mexico_extras(report):
    e = report.mx_extras
    assert e.carry_vs_us == pytest.approx(0.037)
    assert e.real_carry_vs_us == pytest.approx(0.04 - 0.013, abs=1e-6)
    # Flat nominal peso + higher MX inflation => real peso keeps appreciating: below its 10y average.
    assert e.real_fx_gap < 0


def test_global_and_imf_comparison(report):
    assert report.world.g20_breadth == pytest.approx(0.5, abs=0.06)  # USA/MEX overridden to flat
    assert report.world.cycle == "ciclo global mixto"
    mx_cmp = report.vs_imf[1]
    assert mx_cmp.gdp_imf == pytest.approx(0.025)
    assert "crecimiento observado >1pp debajo del FMI: riesgo de recorte" in mx_cmp.flags


def test_assumptions(report):
    us, mx = report.assumptions
    assert us.cost_of_equity() == pytest.approx(0.042 + 0.05)
    assert us.cost_of_equity(1.5) == pytest.approx(0.042 + 0.075)
    assert us.terminal_growth == pytest.approx(0.042)  # 2.3% + 2% = 4.3%, capped at the 10y

    # MX 10y 9% in dollars: 1.09 * 1.023 / 1.04 - 1 = 7.22%; spread over 4.2% = 3.02pp; x1.5
    spread = 1.09 * 1.023 / 1.04 - 1 - 0.042
    assert mx.country_risk_premium == pytest.approx(spread * 1.5)
    usd = 0.042 + 0.05 + spread * 1.5
    assert mx.cost_of_equity() == pytest.approx((1 + usd) * 1.04 / 1.023 - 1)
    assert mx.terminal_growth == pytest.approx(0.04 + 0.01, abs=1e-6)


def test_publication_lag_hides_unreleased_prints():
    # A US CPI spike dated June 2026 is released mid-July: invisible on July 1st.
    def spiked(source, sid):
        s = fake_fetch(source, sid)
        if sid == "CPIAUCSL":
            s = s.copy()
            s[pd.Timestamp("2026-06-01")] *= 1.10
        return s

    early = build_report("2026-07-01", fetch=spiked, weo_fetch=fake_weo)
    late = build_report("2026-07-20", fetch=spiked, weo_fetch=fake_weo)
    assert early.us.inflation_yoy == pytest.approx(0.03, abs=1e-6)
    assert late.us.inflation_yoy > 0.10


def test_missing_history_raises():
    with pytest.raises(sources.DataError):
        build_report("2010-03-01", fetch=fake_fetch, weo_fetch=fake_weo)


def test_render_is_spanish_markdown(report):
    text = render(report)
    assert "# Panorama macro al 2026-06-30" in text
    assert "| MX (MXN) |" in text


def test_parsers():
    bmx = {"bmx": {"series": [{"idSerie": "SP1", "datos": [
        {"fecha": "01/01/2026", "dato": "1,140.5"}, {"fecha": "01/02/2026", "dato": "N/E"}]}]}}
    s = sources.parse_banxico(bmx)
    assert list(s) == [1140.5] and s.index[0] == pd.Timestamp("2026-01-01")

    imf = {"values": {"NGDP_RPCH": {"MEX": {"2025": 0.5, "2026": 1.2}, "USA": {"2026": 2.0}}}}
    df = sources.parse_imf(imf, "NGDP_RPCH")
    assert df.loc[2026, "MEX"] == 1.2 and pd.isna(df.loc[2025, "USA"])
    with pytest.raises(sources.DataError):
        sources.parse_imf({}, "NGDP_RPCH")


def test_forecast_reverts_to_mean():
    from macro.forecast import forecast
    # Oscillating around 5 and currently far above it: AR pulls back down, the band brackets it.
    idx = pd.date_range("2016-01-01", periods=120, freq="MS")
    s = pd.Series([5 + 3 * (0.8 ** (i % 24)) * (-1) ** (i // 24) for i in range(120)], index=idx)
    s.iloc[-1] = 9.0
    fc = forecast(s, 12)
    assert len(fc) == 12 and fc.index[0] == pd.Timestamp("2026-01-01")
    assert fc["ar1"].iloc[-1] < 9.0
    assert (fc["lo"] <= fc["ar1"]).all() and (fc["ar1"] <= fc["hi"]).all()


def test_dashboard_page():
    import json

    from macro.dashboard import build_dashboard
    page = build_dashboard("2026-06-30", fetch=fake_fetch, weo_fetch=fake_weo)
    data = json.loads(page.split('type="application/json">')[1].split("</script>")[0])
    assert {"Mundo", "EE.UU.", "México", "Supuestos"} <= data["reasons"].keys()
    assert {"US_infl", "MX_fx", "brent", "vix"} <= data["charts"].keys()
    assert all(f["ensemble"] is not None for f in data["forecasts"])
    assert "Régimen" in data["reasons"]["México"][0]


def test_yoy_pct_skips_missing_month():
    from macro.dashboard import _yoy_pct
    idx = pd.date_range("2024-01-01", "2025-12-01", freq="MS").drop(pd.Timestamp("2024-10-01"))
    s = pd.Series(range(100, 100 + len(idx)), index=idx, dtype=float)
    yoy = _yoy_pct(s).dropna()
    assert pd.Timestamp("2025-10-01") not in yoy.index
    assert yoy[pd.Timestamp("2025-11-01")] == (s["2025-11-01"] / s["2024-11-01"] - 1) * 100


def test_recession_probability_probit():
    from macro.markets import recession_probability
    assert recession_probability(0) == pytest.approx(0.297, abs=1e-3)
    assert recession_probability(-1) == pytest.approx(0.540, abs=1e-3)
    assert recession_probability(2) < recession_probability(0) < recession_probability(-1)


def test_markets_cross_feeds(report):
    from macro.markets import build_markets
    m = build_markets(report, fake_fetch)
    assert m.us_3m10y == pytest.approx(-0.8)
    assert m.recession_prob == pytest.approx(0.5, abs=0.05)
    assert m.us_policy_gap == pytest.approx(4.5 - 4.3)        # 2y over fed funds
    assert m.mx_spread_10y == pytest.approx(9.0 - 4.2)
    assert m.mx_us_spread["1y"] == pytest.approx(8.3 - 4.8, abs=0.15)   # on the fitted curves
    assert m.us_curve.years[0] == pytest.approx(1 / 12)
    flags = m.flags
    assert any("invertida" in f for f in flags["EE.UU."])
    assert any("tasa real" in f for f in flags["EE.UU."])
    assert any("IPC México" in f for f in flags["México"])
    ipc = next(i for i in m.indices if i.name == "IPC México")
    assert ipc.drawdown == pytest.approx(-0.2, abs=0.01) and ipc.cost_of_equity == report.assumptions[1].cost_of_equity()


def test_neutral_rate_and_stance(report):
    from macro.neutral import build_neutral, neutral_from
    n = build_neutral(report, fake_fetch)
    us, mx = n["US"], n["MX"]
    # US: trend 2%, ex-ante real = 4.3 fed funds - 2.5 expected = 1.8 -> r* 1.9, nominal 3.9, policy 4.3.
    assert us.rstar == pytest.approx((2.0 + 1.8) / 2, abs=1e-6)
    assert us.gap == pytest.approx(4.3 - 3.9, abs=1e-6) and us.stance == "cerca de neutral"
    assert us.external == pytest.approx(0.8)
    # MX: trend 1%, real = 8.0 - 4.0 inflation = 4.0 -> r* 2.5, nominal 5.5, policy 8.0: restrictive.
    assert mx.rstar == pytest.approx(2.5, abs=1e-6) and mx.stance == "restrictiva"
    path = mx.path(pd.date_range("2026-07-01", periods=12, freq="MS"))
    assert path.iloc[-1] == pytest.approx(mx.nominal + mx.gap / 2)   # the gap halves in a year
    idx = pd.date_range("2020-01-01", periods=12, freq="MS")
    with pytest.raises(sources.DataError):
        neutral_from("US", pd.Series(4.0, index=idx), pd.Series(2.0, index=idx), 2.0, None, "")


def test_economy_flags_and_risk(report):
    from macro.economy import build_economy
    from macro.economy import reasons as econ_reasons
    from macro.markets import build_markets
    weo = {i: fake_weo(i) for i in sources.IMF_INDICATORS}
    e = build_economy(report, weo, fake_fetch)
    assert e.us_trade_12m == pytest.approx(-720.0)          # 12 x -60 bn
    assert e.mx_goods_4q == pytest.approx(4 * 10.0)         # (150 - 140) bn a period
    assert e.hy_oas == 6.0 and any("high yield" in f for f in e.flags["Mundo"])
    r = econ_reasons(e, build_markets(report, fake_fetch), report)
    assert "CDS" in r["Riesgo"][0] and r["Riesgo"][0] in r["Comercio"]


def test_parse_hlw_rejects_unknown_layout():
    import io as _io
    buf = _io.BytesIO()
    pd.DataFrame({"a": [1, 2]}).to_excel(buf, sheet_name="HLW Estimates", index=False, header=False)
    with pytest.raises(sources.DataError):
        sources.parse_hlw(buf.getvalue())


def test_nss_fit_recovers_known_curve():
    import numpy as np
    from macro.markets import NSS, fit_nss
    true = NSS(betas=[5.0, -1.5, 2.0, -1.0], tau1=1.8, tau2=8.0)
    years = [1 / 12, 0.25, 0.5, 1, 2, 3, 5, 7, 10, 20, 30]
    fit = fit_nss(years, list(true(years)))
    grid = np.linspace(0.1, 30, 60)
    assert np.abs(fit(grid) - true(grid)).max() < 0.03          # within 3bp across the curve
    assert fit(30) == pytest.approx(true(30), abs=0.01)
    ns = fit_nss([3, 10, 20, 30], [4.0, 4.2, 4.4, 4.5])        # few nodes -> plain Nelson-Siegel
    assert ns.tau2 is None and len(ns.betas) == 3
    with pytest.raises(sources.DataError):
        fit_nss([1, 2, 3], [4, 4, 4])


def test_ytm_mexican_convention():
    import numpy as np
    from macro.markets import ytm
    # Coupon = yield and whole coupon periods -> par; a cheaper price means a higher yield.
    assert ytm([100.0], [8.0], [182 * 20])[0] == pytest.approx(8.0, abs=1e-6)
    assert ytm([95.0], [8.0], [182 * 20])[0] > 8.0
    assert np.isnan(ytm([np.nan], [8.0], [3640])[0])


def test_mexico_curve_from_price_vector(report):
    from macro.markets import build_markets
    m = build_markets(report, fake_fetch)
    assert m.mx_curve.at("10y") == pytest.approx(9.0, abs=1e-4)          # par bond yields its coupon
    assert m.mx_real_curve.at("10y") == pytest.approx(4.2, abs=1e-4)     # Udibono price / UDI value
    assert m.mx_curve.years_by["now"][m.mx_curve.tenors.index("30y")] == pytest.approx(182 * 56 / 365, abs=1e-3)
