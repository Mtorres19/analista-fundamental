// Tasas: policy expectations, curves, our neutral rate and country risk.
const MK = D.markets;
const NR = D.neutral;
const RT = D.rates, pc = v => (v * 100).toFixed(0) + '%';
// Wide tables keep the key columns on phones: the cumulative buckets hide below 860px.
const probRow = r => ({...r, cls: r.horizon ? 'hz' : ''});
const probTable = (rows, note) => denseTable({keyColumn: 'expected', rows: rows.map(probRow), columns: [
  {key: 'date', label: 'Reunión u horizonte'}, {key: 'expected', label: 'Tasa esperada', render: r => r.expected.toFixed(2) + '%'},
  {key: 'change', label: 'Cambio', hideSm: true, render: r => (r.change >= 0 ? '+' : '') + (r.change * 100).toFixed(0) + ' pb'},
  {key: 'p_cut', label: 'Recorte', render: r => pc(r.p_cut)}, {key: 'p_hold', label: 'Mantener', render: r => pc(r.p_hold)}, {key: 'p_hike', label: 'Alza', render: r => pc(r.p_hike)},
  ...[['-2', '−50 pb o más'], ['-1', '−25'], ['0', '0'], ['1', '+25'], ['2', '+50 o más']].map(([k, l]) => ({key: 'cum' + k, label: l, hideSm: true, render: r => pc(r.cum[k])}))],
  note: `En las reuniones, Recorte / Mantener / Alza es la probabilidad de esa decisión; en los horizontes, de terminar abajo, igual o arriba de hoy. Las últimas cinco columnas son el cambio acumulado contra hoy. ${note}`});
const scen = c => RT.scenarios[c].map(z => `<tr><td>${{cut: 'Recorte', hold: 'Sin cambio', hike: 'Alza'}[z.scenario]}</td><td>${pc(z.prob)}</td>
  <td>${z.rate.toFixed(2)}%</td><td class="strong">${(z.coe * 100).toFixed(2)}%</td></tr>`).join('');
const f0 = RT.fed[0], m0 = RT.mx[0], fmtDay = d => new Date(d + 'T12:00:00Z').toLocaleDateString('es-MX', {day: 'numeric', month: 'short', timeZone: 'UTC'});
AREAS.push({id: 'tasas', name: 'Tasas', views: [
  {id: 'politica', name: 'Política monetaria', render: () => viewHeader({question: '¿Qué descuenta el mercado para la Fed y Banxico?', answer: answer('politica'), sources: 'futuros de Fed funds, curva de Cetes, MOVE'}) +
  kpiStrip([
    {label: `Fed ${fmtDay(f0.date)}: alza`, value: pc(f0.p_hike), sub: `mantener ${pc(f0.p_hold)} · recorte ${pc(f0.p_cut)} (futuros)`, tone: 'neutral'},
    {label: 'Fed a 12 meses', value: RT.horizons.US['12m'].mean.toFixed(2) + '%', sub: `± ${RT.horizons.US['12m'].sigma.toFixed(2)} pp (1σ, MOVE) · hoy ${RT.fed_current.toFixed(2)}%`},
    m0 && !m0.horizon ? {label: `Banxico ${fmtDay(m0.date)}: mantener`, value: pc(m0.p_hold), sub: `recorte ${pc(m0.p_cut)} · alza ${pc(m0.p_hike)} (curva de Cetes)`} : {label: 'Banxico', value: '—', sub: 'sin fecha confirmada'},
    {label: 'Banxico a 12 meses', value: RT.horizons.MX['12m'].mean.toFixed(2) + '%', sub: `± ${RT.horizons.MX['12m'].sigma.toFixed(2)} pp · curva de Cetes`},
  ]) +
  `<div class="split">${why('Qué descuenta el mercado', D.reasons['Probabilidades'])}<div class="charts">
  ${card('fed_probs', 'Fed: probabilidad acumulada', 'Próximas dos reuniones con el método FedWatch sobre futuros de Fed funds (CME vía Yahoo); a 3, 6 y 12 meses, distribución con la volatilidad del MOVE. Cambio acumulado contra hoy.')}
  ${card('us_dist', 'Fed: distribución de la tasa a 3, 6 y 12 meses', 'Media de los futuros y dispersión del MOVE ajustada al tramo corto.')}
  ${card('mx_probs', 'Banxico: probabilidad acumulada', 'Curva de Cetes del vector de precios menos su prima por plazo de 5 años; reuniones con fecha confirmada y horizontes.')}
  </div></div><h3 class="sub-h">Fed</h3>` +
  probTable(RT.fed, `Tasa de referencia: fed funds efectiva ${RT.fed_current.toFixed(2)}%. Calendario oficial de la Fed para 2026–2027.` +
    (RT.sofr ? ` Comprobación con futuros de SOFR a 3 meses (${RT.sofr.month}): ${RT.sofr.sofr.toFixed(2)}% contra ${RT.sofr.fed_funds.toFixed(2)}% de los Fed funds en los mismos meses.` : '') +
    ' Cálculo propio con datos de Yahoo; no son las cifras oficiales de CME FedWatch.') +
  `<h3 class="sub-h">Banxico</h3>` +
  probTable(RT.mx, `Tasa de referencia: ${RT.mx_current.toFixed(2)}%. Prima por plazo restada a los forwards de Cetes (promedio de 5 años): ${RT.mx_premium.map(p => (p >= 0 ? '+' : '') + p.toFixed(2)).join(' / ')} pp. Banxico solo tiene publicadas las fechas de 2026; para 2027 se usan horizontes. Sin futuros ni opciones de TIIE gratuitos, es una aproximación.`) +
  `<h3 class="sub-h">Costo de capital por escenario de tasas, 12 meses</h3>
  <div class="charts" style="margin-top:14px">${['US', 'MX'].map(c => `<div class="card table-wrap"><h3>${c === 'US' ? 'EE.UU. (USD)' : 'México (MXN)'}</h3><table><thead><tr><th>Escenario</th><th>Probabilidad</th><th>Tasa de política</th><th>Costo de capital</th></tr></thead><tbody>${scen(c)}</tbody></table>
  <p class="note" style="margin-top:10px">El costo de capital se mueve con la mitad de la sorpresa en la tasa de política (supuesto de traspaso a la tasa a 10 años). El promedio ponderado por probabilidad es el costo base.</p></div>`).join('')}</div>`},
  {id: 'curvas', name: 'Curvas', render: () => viewHeader({question: '¿Qué dicen las curvas de tasas?', answer: answer('curvas'), sources: 'FRED, vector de precios Banxico'}) +
  kpiStrip(MK.kpis) +
    `<div class="charts" style="margin-top:14px">${card('curve_US', 'Curva de Treasuries', 'Rendimiento por plazo, %.')}${card('curve_MX', 'Curva de México', 'Vector de precios Banxico (mercado secundario): TIIE de fondeo, Cetes y Bonos M; rendimiento al vencimiento calculado del precio, %.')}</div>
  <div class="split">${why('Qué dicen las curvas', D.reasons['Curvas'])}<div class="charts">
  ${card('real_curves', 'Curvas reales', 'TIPS de EE.UU. y Udibonos de México (vector de precios Banxico), % real por plazo.')}
  ${card('mx10_daily', 'Bono M a 10 años vs Treasury, diario', 'Rendimiento de mercado del tramo 7–10 años del vector de precios y del Treasury a 10 años.')}
  ${card('slopes', 'Pendiente de la curva de EE.UU.', 'Abajo de cero, curva invertida.')}
  ${card('prob', 'Probabilidad de recesión a 12 meses', 'Probit de la Fed de Nueva York sobre la pendiente 10a – 3m. La línea punteada marca 30%.')}
  </div></div>`},
  {id: 'neutral', name: 'Tasa neutral', render: () => viewHeader({question: '¿La política monetaria es restrictiva o laxa?', answer: answer('neutral'), sources: 'FRED, Banxico SIE, Fed de Cleveland'}) +
  `<div class="card table-wrap" style="margin-top:14px"><table class="compact"><thead><tr><th>País</th><th>r* nuestro</th><th class="hide-sm">Crec. tendencial</th><th class="hide-sm">Tasa real ex ante 10a</th>
  <th class="hide-sm">Referencia externa</th><th class="hide-sm">Meta</th><th>Neutral nominal</th><th>Tasa actual</th><th>Brecha</th><th>Postura</th></tr></thead><tbody>` +
  NR.map(x => `<tr><td>${x.country}</td><td class="strong">${x.rstar.toFixed(2)}%</td><td class="hide-sm">${x.growth.toFixed(2)}%</td><td class="hide-sm">${x.avg_real.toFixed(2)}%</td>
  <td class="hide-sm">${x.external.toFixed(2)}% <span style="color:var(--muted)">${esc(x.external_label)}</span></td><td class="hide-sm">${x.target.toFixed(0)}%</td>
  <td class="strong">${x.nominal.toFixed(2)}%</td><td>${x.policy.toFixed(2)}%</td><td class="strong">${x.gap >= 0 ? '+' : ''}${x.gap.toFixed(2)} pp</td><td>${x.stance}</td></tr>`).join('') +
  `</tbody></table><p class="note" style="margin-top:10px">r* nuestro: promedio del crecimiento tendencial (10 años de PIB real) y de la tasa real ex ante de 10 años (tasa de política menos inflación esperada a un año en EE.UU., inflación observada en México). Neutral nominal = r* + meta de inflación. Brecha arriba de 0.75 pp: restrictiva; abajo de −0.75 pp: laxa.</p></div>
  <div class="charts" style="margin-top:14px">${card('rstar_US', 'Tasa real ex ante vs r*, EE.UU.', 'Fed funds menos inflación esperada a un año (Fed de Cleveland).')}${card('rstar_MX', 'Tasa real ex ante vs r*, México', 'Tasa Banxico menos la inflación esperada a 12 meses (encuesta de Banxico).')}</div>`},
  {id: 'riesgo-pais', name: 'Riesgo país', render: () => viewHeader({question: '¿Cuánto riesgo cobra el mercado por México?', answer: answer('riesgo-pais'), sources: 'vector de precios Banxico, FRED'}) +
  kpiStrip(D.summary.filter(k => k.label.startsWith('Spread real'))) +
  split(why('Qué implica', D.reasons['Riesgo']), card('spread', 'Diferencial México – EE.UU.', 'Puntos porcentuales por plazo.')) +
  subH('Riesgo país usado en la valuación') +
  denseTable({keyColumn: 'crp', rows: D.assumptions, columns: [{key: 'market', label: 'Mercado', render: a => `${esc(a.market)} <span style="color:var(--muted)">${esc(a.currency)}</span>`},
    {key: 'rf', label: 'Libre de riesgo', render: a => pct(a.rf)}, {key: 'crp', label: 'Riesgo país', render: a => pct(a.crp)}, {key: 'coe', label: 'Costo de capital', render: a => pct(a.coe)}],
    note: 'Riesgo país = diferencial real soberano de 10 años × 1.5 (Damodaran), convertido a pesos con la brecha de inflación.'})},
]});
