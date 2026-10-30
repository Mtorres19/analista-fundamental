// The six pieces every view is made of, in the order a view uses them.

// 1. Question the view answers, the answer in one sentence, as-of date and sources.
const viewHeader = ({question, answer, asOf = D.as_of, sources}) =>
  `<header class="vh"><h2 class="sec">${esc(question)}</h2>${answer ? `<p class="ans">${emph(answer)}</p>` : ''}` +
  `<div class="meta">corte ${esc(asOf)} · ${esc(sources)}</div></header>`;

// 2. Three to five cards: {label, value, sub, tone, d1, d30, unit, link}. d1/d30 = change vs the previous reading and vs a month ago.
const chg = (v, u) => v == null ? '' : `<span class="${v >= 0 ? 'up' : 'down'}">${v >= 0 ? '▲' : '▼'} ${Math.abs(v).toFixed(2)}${u || ''}</span>`;
const kpiStrip = list => '<div class="tiles">' + list.map((k, i) => {
  const isNum = /\d/.test(k.value);
  return `<div class="tile rise" style="--i:${i}"><div class="l">${esc(k.label)}</div>` +
    `<div class="v${isNum ? '' : ' word'}"${isNum ? ` data-count="${esc(k.value)}"` : ''}>${esc(isNum ? k.value : (REG[k.value] || k.value))}</div>` +
    `<div class="s">${esc(k.sub)}</div>${k.d1 == null ? '' : `<div class="dl">1d ${chg(k.d1, k.unit)} · 30d ${chg(k.d30, k.unit)}</div>`}` +
    `${status(k.tone)}${k.link ? crossLink(k.link[0], k.link[1]) : ''}</div>`;
}).join('') + '</div>';

// 3. "Por qué está así".
const why = (title, list) => `<div class="why"><h3>${title}</h3><ol>${list.map(r => `<li>${emph(r)}</li>`).join('')}</ol></div>`;

// 4. A chart card. compare = [{label, key}] adds a switch that draws another series in the same card.
const chartCard = (key, {title, note, legend = true, compare} = {}) => {
  const sp = D.specs[key], c = D.charts[key];
  title = title || (c && c.title) || '';
  const extras = c ? c.lines.filter(l => l.role.startsWith('extra')) : [];
  const keys = compare ? [{label: title, key}, ...compare] : [];
  const lg = sp && legend && sp.series.length > 1
    ? sp.series.map(x => `<span>${sp.stacked ? `<svg width="12" height="12" aria-hidden="true"><rect width="12" height="12" rx="2" fill="${SLOT(x.color)}"/></svg>` : x.dots ? `<svg width="12" height="12" aria-hidden="true"><circle cx="6" cy="6" r="4" fill="${SLOT(x.color)}"/></svg>` : line(x.color, x.dash)}${esc(x.label)}</span>`).join('')
    : extras.length ? [{role: 'hist', label: title}].concat(extras).map(l => `<span>${swatch(l.role)}${esc(l.label)}</span>`).join('') : '';
  return `<div class="card"><h3>${esc(title)}</h3>${note ? `<p class="note">${note}</p>` : ''}` +
    (keys.length ? `<div class="cmp" role="group" aria-label="Comparar con">${keys.map((k, i) => `<button type="button" data-key="${esc(k.key)}"${i ? '' : ' class="on"'}>${esc(k.label)}</button>`).join('')}</div>` : '') +
    `<div class="chart"><canvas id="c_${key}" role="img" aria-label="${esc(title)}"></canvas></div>` +
    (lg ? `<div class="legend">${lg}</div>` : '') + chartStamp(key) + '</div>';
};

// 5. Dense table; columns with hideSm drop out on phones. keyColumn is the bold one.
const denseTable = ({columns, rows, keyColumn, note}) =>
  `<div class="card table-wrap"><table class="compact"><thead><tr>${columns.map(c => `<th${c.hideSm ? ' class="hide-sm"' : ''}>${c.label}</th>`).join('')}</tr></thead>` +
  `<tbody>${rows.map(r => `<tr${r.cls ? ` class="${r.cls}"` : ''}>${columns.map(c => `<td class="${c.hideSm ? 'hide-sm ' : ''}${c.key === keyColumn ? 'strong' : ''}">${c.render ? c.render(r) : esc(r[c.key])}</td>`).join('')}</tr>`).join('')}</tbody></table>` +
  `${note ? `<p class="note" style="margin-top:10px">${note}</p>` : ''}</div>`;

// 6. Link to where a figure is used.
const crossLink = (text, href) => `<a class="xlink" href="${href}">${esc(text)} →</a>`;

// Layout helpers shared by the areas.
const split = (whyHtml, cards) => `<div class="split">${whyHtml}<div class="charts">${cards}</div></div>`;
const flagList = flags => flags.length ? '<div class="flags">' + flags.map(f => `<span class="flag">${esc(f)}</span>`).join('') + '</div>' : '';
const subH = (t, first) => `<h3 class="sub-h"${first ? ' style="margin-top:0"' : ''}>${t}</h3>`;
const AREAS = [];
const tiles = kpiStrip;
const answer = id => (D.answers || {})[id];
const card = (key, title, note, legend = true) => chartCard(key, {title, note, legend});
