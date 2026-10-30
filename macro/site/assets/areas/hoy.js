// Hoy: what to look at first.
function quadSvg() {
  const W = 420, Hh = 300, P = {l: 18, r: 18, t: 14, b: 26};
  const m = Math.max(1, ...D.regimes.flatMap(r => [Math.abs(r.x), Math.abs(r.y)])) * 1.35;
  const X = v => P.l + (v + m) / (2 * m) * (W - P.l - P.r), Y = v => P.t + (m - v) / (2 * m) * (Hh - P.t - P.b);
  const cx = X(0), cy = Y(0);
  const q = [['estanflación', P.l + 8, P.t + 18, 'start'], ['reflación', W - P.r - 8, P.t + 18, 'end'],
             ['desaceleración', P.l + 8, Hh - P.b - 10, 'start'], ['goldilocks', W - P.r - 8, Hh - P.b - 10, 'end']];
  let s = `<rect x="${P.l}" y="${P.t}" width="${W - P.l - P.r}" height="${Hh - P.t - P.b}" rx="10" fill="#151514" stroke="${C.grid}"/>`;
  s += `<line x1="${cx}" y1="${P.t}" x2="${cx}" y2="${Hh - P.b}" stroke="${C.axis}"/><line x1="${P.l}" y1="${cy}" x2="${W - P.r}" y2="${cy}" stroke="${C.axis}"/>`;
  s += q.map(([t, x, y, a]) => `<text x="${x}" y="${y}" text-anchor="${a}" fill="${C.muted}" font-size="12" letter-spacing=".04em">${t}</text>`).join('');
  s += `<text x="${W - P.r}" y="${Hh - 8}" text-anchor="end" fill="${C.muted}" font-size="11">crece más que su tendencia →</text>`;
  s += `<text x="${P.l}" y="${Hh - 8}" fill="${C.muted}" font-size="11">↑ inflación subiendo</text>`;
  D.regimes.forEach((r, i) => {
    const col = i ? C.s2 : C.s1, x = X(r.x), y = Y(r.y), right = x > W - 120;
    s += `<circle class="dot-pulse" cx="${x}" cy="${y}" r="7" fill="${col}" style="animation-delay:${i * 1.2}s"/>`;
    s += `<circle cx="${x}" cy="${y}" r="7" fill="${col}" stroke="${C.card}" stroke-width="2"><title>${esc(r.name)}: ${r.x.toFixed(2)} pp vs tendencia, inflación ${r.y >= 0 ? '+' : ''}${r.y.toFixed(2)} pp</title></circle>`;
    s += `<text x="${x + (right ? -13 : 13)}" y="${y - 2}" text-anchor="${right ? 'end' : 'start'}" fill="${C.ink}" font-size="13" font-weight="600">${esc(r.name)}</text>`;
    s += `<text x="${x + (right ? -13 : 13)}" y="${y + 13}" text-anchor="${right ? 'end' : 'start'}" fill="${C.ink2}" font-size="11">PIB ${r.x >= 0 ? '+' : ''}${r.x.toFixed(2)} pp · infl. ${r.y >= 0 ? '+' : ''}${r.y.toFixed(2)} pp</text>`;
  });
  return s;
}

const LEGEND = '<b>Cómo leer las gráficas</b>' + [['hist', 'Histórico'], ['band', 'Banda 90%'], ['ar', 'Reversión a la media'],
  ['drift', 'Tendencia amortiguada'], ['ens', 'Promedio de modelos'], ['anchor', 'Ancla propia (regla de Taylor o costo de capital)'], ['outside', 'Mercado o consenso (futuros, expectativas, encuesta)'], ['imf', 'FMI', true]].map(([r, l, sc]) => `<span>${swatch(r, sc)}${l}</span>`).join('');

const AREA_NAMES = {macro: 'Macro', tasas: 'Tasas', fx: 'Tipo de cambio', mercados: 'Mercados', empresas: 'Empresas'};
const hero = () => {
  const H = D.headline;
  return `<header class="hero"><div class="rise"><div class="eyebrow">Panorama macro · corte ${esc(D.as_of)}</div>
    <h1 id="headline">Mundo en <span class="tag" style="--hl:${C.s4}">${esc(H['Mundo'].replace(' global', ''))}</span>, EE.UU. en ` +
    `<span class="tag" style="--hl:${C.s1}">${esc(REG[H['EE.UU.']])}</span> y México en <span class="tag" style="--hl:${C.s2}">${esc(REG[H['México']])}</span>.</h1>
    <p class="lede">Lectura propia con datos de FRED, Banxico y el FMI: cada indicador con su historia, por qué está donde está y hacia dónde apuntan los modelos a 12 meses.</p>
    <div class="chips">${[['Mundo', H['Mundo'], null], ['EE.UU.', REG[H['EE.UU.']], REG_TONE[H['EE.UU.']]], ['México', REG[H['México']], REG_TONE[H['México']]]].map(([k, v, t]) =>
      `<div class="regime-card"><div class="k">${k}</div><div class="v">${esc(v)}</div>${t ? status(t) : ''}</div>`).join('')}</div></div>
    <figure class="quad rise" style="--i:2" aria-labelledby="qt"><h2 id="qt">Mapa de régimen</h2>
    <p>Crecimiento contra su tendencia de 10 años (horizontal) y cambio de la inflación en seis meses (vertical).</p>
    <svg id="quad" viewBox="0 0 420 300" role="img" aria-label="Mapa de régimen de EE.UU. y México">${quadSvg()}</svg></figure></header>
    <div class="legend-card rise" style="--i:3">${LEGEND}</div>`;
};
const changesList = () => D.changes.length
  ? `<ul class="changes">${D.changes.map(c => `<li><b>${esc(c.area)} · ${esc(c.label)}</b> ${esc(c.value)} ${chg(c.d1, c.unit)}` +
    `<span class="z">${Math.abs(c.z).toFixed(1)}σ</span></li>`).join('')}</ul>`
  : '<p class="note">Ningún indicador se movió más de una desviación estándar de lo usual.</p>';

AREAS.push({id: 'hoy', name: 'Hoy', views: [
  {id: 'resumen', name: 'Resumen', render: () => hero() +
    `<div class="block">${viewHeader({question: '¿Qué es lo más importante hoy?', sources: 'FRED, Banxico SIE, FMI WEO, Yahoo Finance'})}` +
    kpiStrip(D.summary) + flagList(['Mundo', 'EE.UU.', 'México'].flatMap(k => D.flags[k].map(f => `${k}: ${f}`))) +
    subH('Qué cambió desde ayer') + changesList() +
    subH('La respuesta de cada área') + `<ul class="changes">${D.answer_list.map(a => `<li><b>${esc(a.name)}</b> ${emph(a.text)} ${crossLink('ver', '#' + a.href)}</li>`).join('')}</ul></div>`},
  {id: 'alertas', name: 'Alertas', render: () => viewHeader({question: '¿Qué conviene vigilar?', sources: 'lecturas propias sobre FRED, Banxico SIE, FMI WEO'}) +
    ['Mundo', 'EE.UU.', 'México'].map(k => subH(k) + (D.flags[k].length ? flagList(D.flags[k]) : '<p class="note">Sin alertas.</p>')).join('')},
  {id: 'calendario', name: 'Calendario', render: () => viewHeader({question: '¿Qué viene en los próximos 30 días?', sources: 'calendarios oficiales de la Fed y Banxico'}) +
    (D.calendar.length ? denseTable({columns: [{key: 'date', label: 'Fecha'}, {key: 'event', label: 'Evento'}, {key: 'where', label: 'Institución'}],
      rows: D.calendar, keyColumn: 'date', note: 'INEGI, BLS y reportes de empresas se agregan en una fase posterior.'}) : '<p class="note">Sin eventos en los próximos 30 días.</p>')},
]});
