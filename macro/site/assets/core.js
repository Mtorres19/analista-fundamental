const D = JSON.parse(document.getElementById('data').textContent);
const css = n => getComputedStyle(document.documentElement).getPropertyValue(n).trim();
const C = {ink: css('--ink'), ink2: css('--ink-2'), muted: css('--muted'), grid: css('--grid'), axis: css('--axis'), card: css('--card'),
  s1: css('--s1'), s2: css('--s2'), s3: css('--s3'), s4: css('--s4'), s5: css('--s5'), s6: css('--s6')};
// Every chart maps the same role to the same color, so the legend at the top holds for all of them.
const ROLE = {
  hist:   {color: C.s1, width: 2, dash: []},
  extra1: {color: C.s2, width: 1.5, dash: []},
  extra2: {color: C.s6, width: 1.5, dash: []},
  band:   {color: C.s1, width: 0, dash: []},
  ar:     {color: C.s3, width: 2, dash: [5, 4]},
  drift:  {color: C.s4, width: 2, dash: [2, 3]},
  ens:    {color: C.ink, width: 2, dash: [9, 4]},
  imf:    {color: C.s5, width: 0, dash: []},
  anchor: {color: C.s6, width: 2, dash: [3, 3]},
  outside: {color: C.s5, width: 2, dash: [8, 3, 2, 3]},
};
const REG = {goldilocks: 'goldilocks', reflation: 'reflación', stagflation: 'estanflación', slowdown: 'desaceleración'};
const REG_TONE = {goldilocks: 'good', reflation: 'warn', stagflation: 'bad', slowdown: 'warn'};
const ICON = {good: '✓', bad: '✕', warn: '!'};
const TONE_LABEL = {good: 'favorable', bad: 'en contra', warn: 'vigilar'};
const reduce = matchMedia('(prefers-reduced-motion: reduce)').matches;
const esc = s => String(s).replace(/[&<>"]/g, c => ({'&': '&amp;', '<': '&lt;', '>': '&gt;', '"': '&quot;'}[c]));
const pct = v => (v * 100).toFixed(2) + '%';
const num = (v, u) => v == null ? '—' : (u === '%' ? v.toFixed(2) + '%' : v >= 1000 ? v.toLocaleString('es-MX', {maximumFractionDigits: 0}) : v.toFixed(2));
const status = t => !t || t === 'neutral' ? '' : `<span class="status ${t}"><i aria-hidden="true">${ICON[t]}</i>${TONE_LABEL[t]}</span>`;
// Bold the figures (decimals or percentages), not plain counts like "12 meses" or "S&P 500".
const emph = s => esc(s).replace(/(^|[^\w.])([+-]?\d+(?:\.\d+%?|%))(?![\w])/g, '$1<b>$2</b>');

// "Último dato" under each chart: amber when older than the series' normal publication lag allows.
function stamp(ms, freq) {
  if (!ms) return '';
  const age = (Date.parse(D.as_of) - ms) / 864e5, stale = age > ({D: 6, MS: 100, QS: 220}[freq] || 100);  // monthly data normally lands 1-2 months after the month
  return `<div class="stamp${stale ? ' stale' : ''}">último dato: ${new Date(ms).toISOString().slice(0, 10)}${stale ? ' · atrasado' : ''}</div>`;
}
function chartStamp(key) {
  const c = D.charts[key];
  if (c) { const h = c.lines.find(l => l.role === 'hist').points; return stamp(h[h.length - 1][0], c.daily ? 'D' : c.freq); }
  const sp = D.specs[key];
  if (sp && sp.kind === 'time') return stamp(Math.max(...sp.series[0].points.map(p => p[0])), sp.daily ? 'D' : 'MS');
  return sp && sp.kind === 'tenor' ? stamp(Date.parse(D.as_of), 'D') : '';
}

const swatch = (role, scatter) => scatter
  ? `<svg width="12" height="12" aria-hidden="true"><circle cx="6" cy="6" r="4.5" fill="${ROLE[role].color}"/></svg>`
  : role === 'band' ? `<svg width="18" height="10" aria-hidden="true"><rect width="18" height="10" rx="3" fill="${ROLE.band.color}" opacity=".28"/></svg>`
  : `<svg width="22" height="6" aria-hidden="true"><line x1="1" y1="3" x2="21" y2="3" stroke="${ROLE[role].color}" stroke-width="2" stroke-linecap="round" stroke-dasharray="${ROLE[role].dash.join(' ')}"/></svg>`;
const SLOT = k => k === 'muted' ? 'rgba(195,194,183,.55)' : C[k];
const line = (k, dash = []) => `<svg width="22" height="6" aria-hidden="true"><line x1="1" y1="3" x2="21" y2="3" stroke="${SLOT(k)}" stroke-width="2" stroke-linecap="round" stroke-dasharray="${(dash || []).join(' ')}"/></svg>`;

// Count-up on tiles: animate the number, then put back the exact text.
function countUp(el) {
  const final = el.dataset.count, m = final.match(/-?[\d,]*\d(\.\d+)?/);
  if (!m || reduce) return;
  const grouped = m[0].includes(','), target = parseFloat(m[0].replace(/,/g, '')), dec = m[1] ? m[1].length - 1 : 0;
  const fmt = v => grouped ? Math.round(v).toLocaleString('es-MX') : v.toFixed(dec), t0 = performance.now(), dur = 1100;
  const step = t => {
    const k = Math.min(1, (t - t0) / dur), e = 1 - Math.pow(1 - k, 3);
    el.textContent = final.replace(m[0], fmt(target * e));
    if (k < 1) requestAnimationFrame(step); else el.textContent = final;
  };
  requestAnimationFrame(step);
}

// Tooltip shared by every chart
const tip = document.getElementById('tip');
function external({chart, tooltip}) {
  if (!tooltip.opacity || !tooltip.dataPoints?.length) { tip.style.opacity = 0; return; }
  const c = chart.$meta, pts = tooltip.dataPoints.filter(p => !p.dataset.label.startsWith('_'));
  const date = c.bar ? tooltip.title[0] : c.curve ? 'Plazo ' + (pts.find(p => p.raw.t)?.raw.t || +pts[0].parsed.x.toFixed(2) + ' años')
    : new Date(pts[0].parsed.x).toISOString().slice(0, c.daily ? 10 : 7);
  tip.innerHTML = `<div class="d">${esc(date)}</div>` + pts.map(p => `<div class="r"><span class="sw" style="background:${p.dataset.borderColor || p.dataset.backgroundColor}"></span>${esc(p.dataset.label === 'Histórico' ? c.title : p.dataset.label)}<b>${c.fmt ? c.fmt(p.parsed.y) : num(p.parsed.y, c.unit)}</b></div>`).join('');
  const r = chart.canvas.getBoundingClientRect(), w = tip.offsetWidth, h = tip.offsetHeight;
  let x = r.left + tooltip.caretX + 14, y = r.top + tooltip.caretY - h / 2;
  if (x + w > innerWidth - 8) x = r.left + tooltip.caretX - w - 14;
  tip.style.left = Math.max(8, x) + 'px'; tip.style.top = Math.min(innerHeight - h - 8, Math.max(8, y)) + 'px'; tip.style.opacity = 1;
}
addEventListener('scroll', () => { tip.style.opacity = 0; }, {passive: true});

// Crosshair: a hairline at the hovered x.
const crosshair = {id: 'crosshair', afterDatasetsDraw(chart) {
  const a = chart.tooltip?.getActiveElements?.();
  if (!a?.length || chart.$meta.bar) return;
  const x = a[0].element.x, {top, bottom} = chart.chartArea, g = chart.ctx;
  g.save(); g.strokeStyle = 'rgba(240,239,236,.28)'; g.lineWidth = 1; g.beginPath(); g.moveTo(x, top); g.lineTo(x, bottom); g.stroke(); g.restore();
}};

// Charts described by D.specs: curves by tenor (x in years), bars by category, or several series over time.
function specChart(key, el) {
  const sp = D.specs[key], mono = {color: C.muted, font: {family: css('--mono'), size: 10.5}};
  const fmt = v => sp.unit === '%' ? v.toFixed(2) + '%' : v.toFixed(2) + sp.unit;
  if (sp.kind === 'cat') {
    const o = base({bar: true, unit: ''});
    o.scales.y.ticks.callback = v => +v.toFixed(1) + sp.unit;
    o.scales.x.ticks = {...mono, autoSkip: true, maxRotation: 0, maxTicksLimit: 8};
    if (sp.stacked) {  // probability bars: segments add to 100%
      Object.assign(o.scales.x, {stacked: true}); Object.assign(o.scales.y, {stacked: true, min: 0, max: 100});
      o.interaction = {mode: 'index', intersect: false};
    }
    const ch = new Chart(el, {type: 'bar', plugins: [crosshair], options: o, data: {labels: sp.labels,
      datasets: sp.series.map(x => ({label: x.label, data: x.values, borderRadius: sp.stacked ? 0 : 4, borderSkipped: 'start',
        maxBarThickness: sp.stacked ? 44 : 28, borderColor: C.card, borderWidth: sp.stacked ? 1 : 0,
        backgroundColor: sp.stacked ? SLOT(x.color) : x.values.map(v => v < 0 ? C.s2 : C.s1)}))}});
    ch.$meta = {bar: true, unit: sp.unit, title: sp.series[0].label, fmt}; return;
  }
  const o = base({unit: sp.unit === '%' ? '%' : ''}), xs = sp.series.flatMap(x => x.points.map(p => p[0]));
  o.scales.y.ticks.callback = v => +v.toFixed(1) + (sp.unit === '%' ? '%' : '');
  if (sp.kind === 'tenor') o.scales.x = {type: 'linear', min: 0, max: 30, grid: {display: false}, border: {color: C.axis}, ticks: {...mono, stepSize: 5, callback: v => v + 'a'}};
  else Object.assign(o.scales.x, {min: Math.min(...xs), max: Math.max(...xs)});
  const ref = sp.ref == null ? [] : [{id: 'ref', afterDraw(c) { const y = c.scales.y.getPixelForValue(sp.ref), {left, right} = c.chartArea, g = c.ctx;
    g.save(); g.setLineDash([4, 4]); g.strokeStyle = C.axis; g.beginPath(); g.moveTo(left, y); g.lineTo(right, y); g.stroke(); g.restore(); }}];
  const ch = new Chart(el, {type: 'line', plugins: [crosshair, ...ref], options: o, data: {datasets: sp.series.map(x => ({
    label: x.label, borderColor: SLOT(x.color), backgroundColor: SLOT(x.color), borderWidth: 2, borderDash: x.dash || [], tension: x.dots ? 0 : 0.3,
    showLine: !x.dots, pointRadius: x.dots ? 3.5 : 0, pointHoverRadius: 5, pointBorderColor: C.card, pointBorderWidth: x.dots ? 1.5 : 0,
    pointHoverBorderColor: C.card, pointHoverBorderWidth: 2,
    data: x.points.map(([a, b], i) => ({x: a, y: b, t: x.tenors ? x.tenors[i] : null}))}))}});
  ch.$meta = {unit: sp.unit, title: sp.series[0].label, curve: sp.kind === 'tenor', fmt, daily: !!sp.daily};
  if (sp.kind === 'time') track(ch, xs, Math.max(...xs), !!sp.daily);
}

function makeChart(key, el = document.getElementById('c_' + key)) {
  if (D.specs[key]) return specChart(key, el);
  if (key === 'g20') {
    const labels = D.g20.labels, vals = D.g20.values;
    const ch = new Chart(el, {
      type: 'bar', plugins: [crosshair],
      data: {labels, datasets: [{label: 'Crecimiento real', data: vals, borderRadius: 4, borderSkipped: 'start', maxBarThickness: 18,
        backgroundColor: labels.map(l => l === 'USA' ? C.s1 : l === 'MEX' ? C.s2 : 'rgba(195,194,183,.28)')}]},
      options: base({bar: true, unit: '%'}),
    });
    ch.$meta = {bar: true, unit: '%', title: 'Crecimiento real'};
    return;
  }
  const c = D.charts[key];
  const datasets = c.lines.map(l => {
    const r = ROLE[l.role];
    return {label: l.label, data: l.points.map(([x, y]) => ({x, y})), borderColor: r.color,
      backgroundColor: l.fill ? r.color + '38' : r.color, borderWidth: r.width, borderDash: r.dash,
      borderCapStyle: 'round', borderJoinStyle: 'round', pointRadius: l.scatter ? 4.5 : 0, pointHoverRadius: l.scatter ? 6 : (r.width ? 4 : 0),
      pointBorderColor: C.card, pointBorderWidth: l.scatter ? 2 : 0, pointHoverBorderWidth: 2, pointHoverBorderColor: C.card, pointHoverBackgroundColor: r.color,
      showLine: !l.scatter, fill: l.fill ? '-1' : false, tension: 0, spanGaps: false};
  });
  const xs = c.lines.flatMap(l => l.points.map(p => p[0])), opts = base({unit: c.unit});
  Object.assign(opts.scales.x, {min: Math.min(...xs), max: Math.max(...xs)});
  const ch = new Chart(el, {type: 'line', data: {datasets}, plugins: [crosshair], options: opts});
  ch.$meta = {unit: c.unit, title: c.title, daily: c.daily};
  const hist = c.lines.find(l => l.role === 'hist').points;
  track(ch, xs, hist[hist.length - 1][0], c.daily, c.auto_from);
}

function base({bar, unit}) {
  const tick = {color: C.muted, font: {family: css('--mono'), size: 10.5}};
  return {
    maintainAspectRatio: false, animation: false, normalized: true,
    interaction: bar ? {mode: 'index', intersect: false} : {mode: 'nearest', axis: 'x', intersect: false},
    layout: {padding: {top: 4, right: 26}},
    scales: {
      x: bar ? {grid: {display: false}, border: {color: C.axis}, ticks: {...tick, autoSkip: false, maxRotation: 90, minRotation: 0}}
             : {type: 'linear', grid: {display: false}, border: {color: C.axis}, ticks: {...tick, maxTicksLimit: 6, callback(v) {
               const d = new Date(v), span = this.max - this.min;  // label by the window shown, not by the data
               return span < 120 * 864e5 ? d.toLocaleDateString('es-MX', {day: 'numeric', month: 'short', timeZone: 'UTC'})
                 : span < 800 * 864e5 ? d.toLocaleDateString('es-MX', {month: 'short', year: '2-digit', timeZone: 'UTC'}) : d.getUTCFullYear(); }}},
      y: {grid: {color: C.grid, drawTicks: false}, border: {display: false}, ticks: {...tick, padding: 8, maxTicksLimit: 5,
        callback: v => unit === '%' ? +v.toFixed(1) + '%' : v >= 1000 ? (v / 1000).toLocaleString('es-MX', {maximumFractionDigits: 1}) + 'k' : +v.toFixed(1)}},
    },
    plugins: {legend: {display: false}, tooltip: {enabled: false, external, filter: i => !i.dataset.label.startsWith('_')}},
  };
}

// Period selector: one window for every time chart. "Auto" = last year for daily charts, everything for monthly ones.
// The forecast stays visible but never takes more room than the history shown.
let range = 'auto';
const timed = [];
const MONTH = 30.44 * 864e5;
function windowFor(r, last, xmin, xmax, daily, autoFrom) {
  const k = r === 'auto' ? (daily ? '1y' : 'all') : r;
  if (k === 'all') return [r === 'auto' && autoFrom ? Math.max(xmin, autoFrom) : xmin, xmax];
  const lo = k === 'ytd' ? Date.UTC(new Date(last).getUTCFullYear(), 0, 1) : last - {'1m': 1, '3m': 3, '6m': 6, '1y': 12, '5y': 60}[k] * MONTH;
  // The forecast gets at most half as much room as the history shown.
  return [Math.max(lo, xmin), Math.min(xmax, last + Math.max((last - lo) / 2, MONTH))];
}
function applyRange(t) {
  const [lo, hi] = windowFor(range, t.last, t.xmin, t.xmax, t.daily, t.autoFrom), ys = [];
  t.chart.data.datasets.forEach(d => d.data.forEach(p => { if (p.x >= lo && p.x <= hi && p.y != null) ys.push(p.y); }));
  const ymin = Math.min(...ys), ymax = Math.max(...ys);
  // Round the y bounds to a 1-2-5 step so the end ticks read as round numbers.
  const raw = (ymax - ymin) / 4 || Math.abs(ymax) * 0.05 || 1, mag = 10 ** Math.floor(Math.log10(raw));
  const step = [1, 2, 2.5, 5, 10].map(f => f * mag).find(x => x >= raw);
  Object.assign(t.chart.options.scales.x, {min: lo, max: hi});
  Object.assign(t.chart.options.scales.y, {min: Math.floor(ymin / step) * step, max: Math.ceil(ymax / step) * step});
  t.chart.update('none');
}
function track(chart, xs, last, daily, autoFrom) {
  const t = {chart, last, daily, autoFrom, xmin: Math.min(...xs), xmax: Math.max(...xs)};
  timed.push(t); applyRange(t);
}
document.querySelectorAll('.ranges button').forEach(b => b.addEventListener('click', () => {
  range = b.dataset.r;
  document.querySelectorAll('.ranges button').forEach(x => x.classList.toggle('on', x === b));
  timed.forEach(applyRange);
}));

// Swap the chart drawn on a canvas for another series (the "comparar con" switch).
function remake(canvas, key) {
  const old = Chart.getChart(canvas);
  if (old) { for (let i = timed.length; i--;) if (timed[i].chart === old) timed.splice(i, 1); old.destroy(); }
  makeChart(key, canvas);
}
