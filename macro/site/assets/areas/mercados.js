// Mercados: indices, commodities and volatility.
const ixChart = ix => `<div class="card"><h3>${esc(ix.name)}</h3><p class="note">Cierre diario en ${ix.currency}; modelos y rentabilidad exigida a 12 meses.</p><div class="chart"><canvas id="c_ix_${esc(ix.name)}" role="img" aria-label="${esc(ix.name)}"></canvas></div>${chartStamp('ix_' + ix.name)}</div>`;
const delta = v => `<span class="${v >= 0 ? 'up' : 'down'}">${v >= 0 ? '▲' : '▼'} ${Math.abs(v * 100).toFixed(1)}%</span>`;
function spark(pts) {
  const xs = pts.map(p => p[0]), ys = pts.map(p => p[1]), x0 = Math.min(...xs), x1 = Math.max(...xs), y0 = Math.min(...ys), y1 = Math.max(...ys);
  const X = x => (x - x0) / ((x1 - x0) || 1) * 200, Y = y => 40 - (y - y0) / ((y1 - y0) || 1) * 36;
  const d = pts.map((p, i) => `${i ? 'L' : 'M'}${X(p[0]).toFixed(1)},${Y(p[1]).toFixed(1)}`).join('');
  const last = pts[pts.length - 1];
  return `<svg class="spark" viewBox="0 0 200 44" preserveAspectRatio="none" aria-hidden="true"><path d="${d}L200,44L0,44Z" fill="${C.s1}" opacity=".10"/>` +
    `<path class="l" d="${d}" pathLength="1" fill="none" stroke="${C.s1}" stroke-width="1.6" stroke-linejoin="round" stroke-linecap="round" vector-effect="non-scaling-stroke"/>` +
    `<circle cx="${X(last[0])}" cy="${Y(last[1])}" r="2.6" fill="${C.ink}"/></svg>`;
}
const ixCard = (ix, i) => `<div class="ix rise" style="--i:${i}"><div class="top"><span class="n">${esc(ix.name)}</span><span class="cur">${ix.currency}</span></div>
  <div class="v" data-count="${num(ix.last, '')}">${num(ix.last, '')}</div>
  <div class="d"><span>año ${delta(ix.ytd)}</span><span>12m ${delta(ix.r1y)}</span></div>
  <div class="d" style="margin-top:4px;color:var(--muted)"><span>máx. 52s ${(ix.drawdown * 100).toFixed(1)}%</span><span>vol ${(ix.vol_3m * 100).toFixed(0)}%</span></div>${spark(ix.spark)}</div>`;
AREAS.push({id: 'mercados', name: 'Mercados', views: [
  {id: 'indices', name: 'Índices', render: () => viewHeader({question: '¿Cómo van los índices frente a lo que exige la macro?', answer: answer('indices'), sources: 'Yahoo Finance, modelos propios'}) +
  `<div class="ixgrid">${MK.indices.concat([MK.ipc_usd]).map(ixCard).join('')}</div>
  <div style="margin-top:14px">${why('Qué dicen los mercados', D.reasons['Mercados'])}</div>
  <div class="charts" style="margin-top:14px">${MK.indices.map(ixChart).join('')}</div>`},
  {id: 'materias-primas', name: 'Materias primas', render: () => viewHeader({question: '¿Qué pasa con petróleo, cobre y dólar?', answer: answer('materias-primas'), sources: 'FRED, Yahoo Finance (futuros)'}) +
    kpiStrip(D.kpis['Mundo'].filter(k => ['Brent', 'Cobre', 'Dólar amplio'].includes(k.label))) +
    `<div class="charts" style="margin-top:14px">${['brent', 'copper', 'dollar'].map(k => card(k)).join('')}</div>`},
  {id: 'volatilidad', name: 'Volatilidad', render: () => viewHeader({question: '¿Cuánto miedo hay en el mercado?', answer: answer('volatilidad'), sources: 'Cboe vía Yahoo Finance, FRED'}) +
  kpiStrip([D.kpis['Mundo'].find(k => k.label === 'VIX'),
    {label: 'MOVE', value: RT.move.toFixed(0), sub: 'volatilidad implícita de Treasuries, pb al año', tone: RT.move > 120 ? 'bad' : 'neutral'},
    {label: 'VIX 1 mes / 3 meses', value: `${RT.vix.vix.toFixed(1)} / ${RT.vix.vix3m.toFixed(1)}`, sub: RT.vix.vix3m > RT.vix.vix ? 'curva con pendiente positiva' : 'curva invertida: estrés', tone: RT.vix.vix3m > RT.vix.vix ? 'good' : 'bad'},
    {label: 'P(S&P 500 −10% en 1 mes)', value: (RT.p_down10 * 100).toFixed(1) + '%', sub: 'implícita en el VIX'},
    RT.skew ? {label: 'Sesgo SPY 25Δ', value: RT.skew.skew.toFixed(1) + ' pts', sub: `put ${RT.skew.put_iv.toFixed(1)}% vs call ${RT.skew.call_iv.toFixed(1)}%, ${RT.skew.days} días`} : {label: 'Sesgo SPY 25Δ', value: '—', sub: 'cadena de opciones no disponible'},
  ]) +
    `<div class="charts" style="margin-top:14px">${card('vix')}${card('vix_term', 'Curva del VIX', 'Volatilidad implícita del S&P 500 por plazo (Cboe vía Yahoo).')}</div>`},
]});
