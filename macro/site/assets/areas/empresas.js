// Empresas: el ranking por upside del DCF y por múltiplos; los supuestos de valuación que salen de la macro.
const CO = D.companies || [];
const CO_SORT = {upside: r => -r.upside, peers: r => r.vs_peers ?? 1e9, pe: r => r.pe ?? 1e9};
const CO_STATE = {market: 'all', sort: 'upside'};
const VERDICT_TONE = {comprar: 'good', mantener: 'warn', vender: 'bad'};
const sgn = v => v == null ? '—' : `<span class="${v >= 0 ? 'up' : 'down'}">${v >= 0 ? '+' : '−'}${Math.abs(v * 100).toFixed(1)}%</span>`;
const money = v => v == null ? '—' : v.toLocaleString('es-MX', {minimumFractionDigits: 2, maximumFractionDigits: 2});
const mult = v => v == null ? '—' : v.toFixed(1) + '×';
// Upside bar centered at 0: right for upside, left for downside; ±60% fills the half.
const upBar = v => {
  const w = Math.min(Math.abs(v) / 0.6, 1) * 50;
  return `<div class="range upbar" aria-hidden="true"><div class="mk now" style="left:50%"></div>` +
    `<div class="bar ${v >= 0 ? 'pos' : 'neg'}" style="${v >= 0 ? 'left:50%' : `left:${50 - w}%;transform-origin:right`};width:${w}%"></div></div>`;
};
const coRow = r => `<tr><td><b>${esc(r.ticker)}</b>` +
  `<div class="note" style="margin:2px 0 0">${esc(r.name)}<span class="hide-sm"> · ${esc(r.sector)} · ${r.market === 'MX' ? 'México' : 'EE.UU.'}</span></div></td>` +
  `<td>${money(r.price)} <span style="color:var(--muted)">${esc(r.currency)}</span></td><td class="strong">${money(r.value)}</td>` +
  `<td class="strong">${sgn(r.upside)}</td><td>${upBar(r.upside)}</td><td><span class="status ${VERDICT_TONE[r.verdict]}"><i aria-hidden="true">${ICON[VERDICT_TONE[r.verdict]]}</i>${esc(r.verdict)}</span></td>` +
  `<td class="hide-sm">${mult(r.pe)}</td><td class="hide-sm">${mult(r.pe_fwd)}</td><td>${mult(r.ev_ebitda)}</td>` +
  `<td class="hide-sm">${mult(r.peer_ev_ebitda)}</td><td>${sgn(r.vs_peers)}</td>` +
  `<td class="hide-sm">${r.implied_growth == null ? '—' : pct(r.implied_growth)}<div class="note" style="margin:2px 0 0">modelo ${pct(r.growth)}</div></td>` +
  `<td class="hide-sm cons">${r.target == null ? '—' : `${money(r.target)} ${sgn(r.target_upside)}`}</td></tr>`;
const coBody = () => CO.filter(r => CO_STATE.market === 'all' || r.market === CO_STATE.market)
  .sort((a, b) => CO_SORT[CO_STATE.sort](a) - CO_SORT[CO_STATE.sort](b)).map(coRow).join('');
const seg = (name, opts) => `<div class="seg" role="group" data-k="${name}">${opts.map(([v, l]) =>
  `<button type="button" data-v="${v}" aria-pressed="${CO_STATE[name] === v}"${CO_STATE[name] === v ? ' class="on"' : ''}>${l}</button>`).join('')}</div>`;

function rankingView() {
  if (!CO.length) return viewHeader({question: '¿Qué acciones están más baratas?', sources: 'DCF propio'}) +
    '<div class="card"><p class="note">Todavía no hay valuaciones: corre <code>python -m equity lista</code> antes de generar el sitio.</p></div>';
  const top = CO[0], buys = CO.filter(r => r.verdict === 'comprar'), ups = CO.map(r => r.upside).sort((a, b) => a - b);
  const med = ups[Math.floor(ups.length / 2)], cheap = CO.filter(r => r.vs_peers != null && r.vs_peers < 0);
  return viewHeader({question: '¿Qué acciones están más baratas?',
      answer: top.upside > 0
        ? `${top.ticker} tiene el mayor upside: su valor DCF de ${money(top.value)} ${top.currency} queda ${(top.upside * 100).toFixed(1)}% arriba del precio.`
        : `Ninguna está barata según el DCF: la mejor, ${top.ticker}, vale ${Math.abs(top.upside * 100).toFixed(1)}% menos que su precio.`,
      asOf: CO.map(r => r.as_of).sort().pop(), sources: 'DCF propio con supuestos macro, SEC EDGAR, Yahoo Finance'}) +
    kpiStrip([
      {label: 'Empresas valuadas', value: String(CO.length), sub: `${CO.filter(r => r.market === 'MX').length} de México`},
      {label: 'Con veredicto comprar', value: String(buys.length), sub: 'upside de 20% o más', tone: buys.length ? 'good' : 'neutral'},
      {label: 'Upside mediano', value: (med * 100).toFixed(1) + '%', sub: 'valor DCF contra precio', tone: med > 0 ? 'good' : 'bad'},
      {label: 'Más baratas que sus pares', value: String(cheap.length), sub: 'EV/EBITDA bajo la mediana de comparables'},
    ]) +
    `<div class="card table-wrap"><div class="seg-row">${seg('market', [['all', 'Todas'], ['US', 'EE.UU.'], ['MX', 'México']])}` +
    `${seg('sort', [['upside', 'Más upside'], ['peers', 'Más baratas vs pares'], ['pe', 'Menor P/U']])}</div>` +
    `<table class="compact co"><thead><tr><th>Empresa</th><th>Precio</th><th>Valor DCF</th><th>Upside</th><th aria-label="Upside visual"></th><th>Veredicto</th>` +
    `<th class="hide-sm">P/U</th><th class="hide-sm">P/U 12m</th><th>EV/EBITDA</th><th class="hide-sm">Pares</th><th>vs pares</th>` +
    `<th class="hide-sm">Crec. implícito</th><th class="hide-sm">Consenso</th></tr></thead><tbody id="co-body">${coBody()}</tbody></table>` +
    `<p class="note" style="margin-top:10px">Upside: valor del DCF propio contra el precio; comprar desde +20%, vender desde −15%. ` +
    `vs pares: EV/EBITDA de la empresa contra la mediana de sus comparables (negativo = más barata). Crec. implícito: crecimiento de ingresos ` +
    `a 5 años que justifica el precio, contra el que supone el modelo. Consenso: precio objetivo mediano de los analistas, solo como referencia; ` +
    `no entra al modelo. Bancos y aseguradoras no se valúan con flujo libre.</p></div>`;
}

document.addEventListener('click', ev => {
  const b = ev.target.closest('.seg button'); if (!b) return;
  const g = b.parentNode; CO_STATE[g.dataset.k] = b.dataset.v;
  g.querySelectorAll('button').forEach(x => { x.classList.toggle('on', x === b); x.setAttribute('aria-pressed', x === b); });
  const body = document.getElementById('co-body'); body.innerHTML = coBody();
  body.querySelectorAll('.range').forEach(el => el.classList.add('grow'));
});

AREAS.push({id: 'empresas', name: 'Empresas', views: [
  {id: 'lista', name: 'Ranking', render: rankingView},
  {id: 'supuestos', name: 'Supuestos', render: () => viewHeader({question: '¿Qué supuestos de valuación salen de la macro?', answer: answer('supuestos'), sources: 'lecturas macro propias, Damodaran'}) +
  `  <div class="split">${why('Por qué estos supuestos', D.reasons['Supuestos'].concat(D.reasons['Riesgo']))}
  <div class="card table-wrap"><table><thead><tr><th>Mercado</th><th>Libre de riesgo</th><th>Prima</th><th>Riesgo país</th><th>Infl. esperada</th>
  <th>Crec. terminal</th><th>Costo de capital</th></tr></thead><tbody>` + D.assumptions.map(a => `<tr>
  <td>${esc(a.market)} <span style="color:var(--muted)">${esc(a.currency)}</span></td><td>${pct(a.rf)}</td><td>${pct(a.erp)}</td><td>${pct(a.crp)}</td>
  <td>${pct(a.infl)}</td><td>${pct(a.g)}</td><td class="strong">${pct(a.coe)}</td></tr>`).join('') + `</tbody></table>
  <p class="note" style="margin-top:10px">Costo de capital con beta 1, en moneda local. Libre de riesgo: bono a 10 años de EE.UU.</p></div></div>`},
]});
