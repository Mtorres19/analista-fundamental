// Macro: the economies, one view each, plus trade/fiscal and the 12-month forecasts.
const EC = D.economy;
const MUNDO_LINKS = {'VIX': '#mercados/volatilidad', 'Dólar amplio': '#mercados/materias-primas', 'Brent': '#mercados/materias-primas', 'Cobre': '#mercados/materias-primas'};
const COMPARE = {US_infl: [{label: 'México', key: 'MX_infl'}], MX_infl: [{label: 'EE.UU.', key: 'US_infl'}]};
const countryBody = (name, keys, first) => kpiStrip(D.kpis[name].filter(k => !(name === 'México' && ['Peso por dólar', 'Carry vs EE.UU.'].includes(k.label)))
    .map(k => ({...k, link: MUNDO_LINKS[k.label] ? ['ver en Mercados', MUNDO_LINKS[k.label]] : null}))) +
  flagList(D.flags[name]) + split(why('Por qué está así', D.reasons[name]), (first || '') + keys.map(k => chartCard(k, {compare: COMPARE[k]})).join(''));
const g20Card = () => `<div class="card"><h3>Crecimiento ${D.g20.year} en el G20</h3><p class="note">FMI, % real anual. EE.UU. y México resaltados.</p><div class="chart"><canvas id="c_g20" role="img" aria-label="Crecimiento por país del G20"></canvas></div></div>`;
// Each bar is centered on today's value, so a lopsided range shows which way the models lean.
const half = f => Math.max(Math.abs(f.lo - f.now), Math.abs(f.hi - f.now), Math.abs(f.ensemble - f.now)) * 1.1 || 1;
const at = (v, f) => (50 + (v - f.now) / half(f) * 50).toFixed(1) + '%';
AREAS.push({id: 'macro', name: 'Macro', views: [
  {id: 'mundo', name: 'Mundo', render: () => viewHeader({question: '¿Cómo está el ciclo global?', answer: answer('mundo'), sources: 'FRED, Banxico SIE, FMI WEO, Yahoo Finance'}) +
    countryBody('Mundo', [], g20Card())},
  {id: 'eeuu', name: 'EE.UU.', render: () => viewHeader({question: '¿Qué hace la economía de EE.UU. y qué hará la Fed?', answer: answer('eeuu'), sources: 'FRED, Banxico SIE, FMI WEO'}) +
    countryBody('EE.UU.', ['US_infl', 'US_rate', 'US_gdp', 'US_unemp'])},
  {id: 'mexico', name: 'México', render: () => viewHeader({question: '¿Cómo va México y qué hará Banxico?', answer: answer('mexico'), sources: 'FRED, Banxico SIE, FMI WEO'}) +
    countryBody('México', ['MX_infl', 'MX_rate', 'MX_gdp', 'MX_unemp'])},
  {id: 'comercio', name: 'Comercio y finanzas', render: () => viewHeader({question: '¿Qué tan sólidas son las cuentas externas y públicas?', answer: answer('comercio'), sources: 'FRED, Banxico SIE, FMI WEO'}) +
  `<h3 class="sub-h" style="margin-top:0">EE.UU.</h3>${tiles(EC.us)}<h3 class="sub-h">México</h3>${tiles(EC.mx)}<h3 class="sub-h">Riesgo de crédito</h3>${tiles(EC.risk)}
  <div class="split">${why('Qué implica', D.reasons['Comercio'])}<div class="charts">
  ${card('us_trade', 'Balanza comercial de EE.UU.', 'Bienes y servicios, miles de millones de USD al mes.')}
  ${card('mx_goods', 'Balanza de mercancías de México', 'Exportaciones menos importaciones, miles de millones de USD por trimestre.')}
  ${card('mx_remit', 'Remesas a México', 'Suma de 12 meses, miles de millones de USD.')}
  ${card('mx_reserves', 'Reservas internacionales de México', 'Miles de millones de USD.')}
  ${card('credit', 'Spreads de crédito', 'ICE BofA, sobre bonos del Tesoro, puntos porcentuales. Sustituyen al CDS, que no tiene fuente gratuita.')}
  <div class="card table-wrap"><h3>FMI ${EC.imf.year}, % del PIB</h3><table><thead><tr><th>Indicador</th><th>EE.UU.</th><th>México</th><th>Mediana G20</th></tr></thead><tbody>` +
  EC.imf.rows.map(r => `<tr><td>${r.ind}</td><td>${r['EE.UU.'].toFixed(1)}%</td><td>${r['México'].toFixed(1)}%</td><td>${r['Mediana G20'].toFixed(1)}%</td></tr>`).join('') +
  `</tbody></table></div></div></div>`},
  {id: 'pronosticos', name: 'Pronósticos', render: () => viewHeader({question: '¿Hacia dónde apuntan los modelos a 12 meses?', answer: answer('pronosticos'), sources: 'modelos propios, FMI WEO, futuros y encuesta de Banxico'}) +
  `  <div class="card table-wrap"><table class="compact"><thead><tr><th>Indicador</th><th class="hide-sm">Horizonte</th><th>Actual</th><th>Tendencia</th><th>Reversión</th><th>Promedio</th>
  <th>Rango 90%</th><th aria-label="Rango visual"></th><th>FMI</th><th>Mercado / consenso</th><th>Ancla propia</th></tr></thead><tbody>` + D.forecasts.map(f => `<tr>
  <td>${esc(f.name)}</td><td class="hide-sm">${f.horizon}</td><td>${num(f.now, f.unit)}</td><td>${num(f.drift, f.unit)}</td><td>${num(f.ar1, f.unit)}</td>
  <td class="strong">${num(f.ensemble, f.unit)}</td><td>${num(f.lo, f.unit)} – ${num(f.hi, f.unit)}</td>
  <td><div class="range" title="Centrado en hoy (línea blanca): rango 90% y promedio (punto)"><div class="bar" style="left:${at(f.lo, f)};width:calc(${at(f.hi, f)} - ${at(f.lo, f)})"></div>
  <div class="mk now" style="left:${at(f.now, f)}"></div><div class="mk ens" style="left:${at(f.ensemble, f)}"></div></div></td>
  <td>${num(f.imf, f.unit)}</td><td>${num(f.market, f.unit)}</td><td>${num(f.anchor, f.unit)}</td></tr>`).join('') + `</tbody></table></div>
  <p class="method"><b>Tendencia</b> y <b>Reversión</b> son nuestros dos modelos puros: el ritmo del último año, amortiguado, y un autorregresivo ajustado a 10 años que regresa la serie a su promedio de largo plazo. <b>Promedio</b>: el pronóstico que usamos. Donde hay una vista de mercado o de consenso, es el promedio de la reversión y esa vista; si no la hay, el promedio de los dos modelos. La tendencia queda fuera cuando hay mercado porque el precio de mercado ya incorpora el impulso reciente. <b>Rango 90%</b>: cubre los modelos y la vista externa más el error típico del modelo, sin que un choque como 2020 lo infle. En la barra, la línea blanca es hoy y el punto verde el promedio. <b>FMI</b>: último año proyectado. <b>Mercado / consenso</b>: inflación esperada a 1 año de la Fed de Cleveland (EE.UU.) y mediana de la encuesta de Banxico a 12 meses (México); futuros de Fed funds; Cete 28 esperado al cierre de año por la encuesta de Banxico (no el forward de la curva, que trae prima por plazo); curva de futuros de Brent y cobre. <b>Ancla propia</b>: en las tasas de política, la convergencia a una regla de Taylor (neutral nominal + la mitad de la brecha de inflación + la mitad de la brecha de producto leída del desempleo), cuya distancia se reduce a la mitad cada año; en los índices, el nivel al que llegarían si rinden exactamente nuestro costo de capital. Son referencias, no certezas.</p>`},
]});
