import pandas as pd
import pytest

from macro import sources
from macro.report import build_report, render

LEVELS = {"DGS10": 4.2, "DFF": 4.3, "T10YIE": 2.3, "BAA10Y": 1.8, "IRLTLT01MXM156N": 9.0,
          "SF61745": 8.0, "LRHUTTTTMXM156S": 2.8, "UNRATE": 4.0, "VIXCLS": 18.0}
# Index series and their annual growth rate.
GROWING = {"CPIAUCSL": 0.03, "SP1": 0.04, "GDPC1": 0.02, "NGDPRSAXDCMXQ": 0.01,
           "DEXMXUS": 0.0, "DTWEXBGS": 0.0, "DCOILBRENTEU": 0.0, "PCOPPUSDM": 0.0}


def fake_fetch(source: str, sid: str) -> pd.Series:
    quarterly = sid in ("GDPC1", "NGDPRSAXDCMXQ")
    idx = pd.date_range("2010-01-01", "2026-12-31", freq="QS" if quarterly else "MS")
    if sid in LEVELS:
        return pd.Series(LEVELS[sid], index=idx)
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
