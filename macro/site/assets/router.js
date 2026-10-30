// Two-level navigation on the hash: #<area>/<view>. Views render the first time they are opened.
const OLD_HASH = {resumen: 'hoy/resumen', mundo: 'macro/mundo', eeuu: 'macro/eeuu', mexico: 'macro/mexico', curvas: 'tasas/curvas',
  probabilidades: 'tasas/politica', mercados: 'mercados/indices', comercio: 'macro/comercio', pronosticos: 'macro/pronosticos', valuacion: 'empresas/supuestos'};
const NAV = AREAS.filter(a => a.views.length);
const find = h => {
  h = OLD_HASH[h] || h;
  const [aid, vid] = h.split('/'), area = NAV.find(a => a.id === aid) || NAV[0];
  return [area, area.views.find(v => v.id === vid) || area.views[0]];
};
const SHORT = 5;  // phones: the first five areas in the bottom bar, the rest under "Más"
const $ = id => document.getElementById(id);
const areaLink = (a, cls = '') => `<a href="#${a.id}" role="tab" data-a="${a.id}"${cls ? ` class="${cls}"` : ''}>${esc(a.name)}</a>`;
$('areas').innerHTML = NAV.map(a => areaLink(a)).join('');
$('bottom').innerHTML = NAV.slice(0, SHORT).map(a => areaLink(a)).join('') + (NAV.length > SHORT
  ? `<button type="button" id="more" aria-haspopup="true" aria-expanded="false">Más</button><div id="morelist" hidden>${NAV.slice(SHORT).map(a => areaLink(a)).join('')}</div>` : '');
const sections = new Map(), built = new Set();
if (window.Chart?.defaults) { Chart.defaults.font.family = css('--body'); Chart.defaults.color = C.muted; }

function show(hash) {
  const [area, view] = find(hash), key = area.id + '/' + view.id;
  document.querySelectorAll('#areas a, #bottom a, #morelist a').forEach(a => {
    const on = a.dataset.a === area.id; a.classList.toggle('on', on); a.setAttribute('aria-selected', on); a.tabIndex = on ? 0 : -1;
  });
  $('more')?.classList.toggle('on', NAV.slice(SHORT).includes(area));
  $('views').innerHTML = area.views.map(v => `<a href="#${area.id}/${v.id}" role="tab" data-v="${v.id}" aria-selected="${v === view}" tabindex="${v === view ? 0 : -1}"${v === view ? ' class="on"' : ''}>${esc(v.name)}</a>`).join('');
  if (!sections.has(key)) {
    const el = document.createElement('section'); el.className = 'tab'; el.hidden = true; el.innerHTML = view.html || (view.html = view.render());
    $('app').appendChild(el); sections.set(key, el);
  }
  sections.forEach((el, k) => { el.hidden = k !== key; });
  // The period selector only acts on time charts: hide it on views that have none.
  document.querySelector('.ranges').hidden = !sections.get(key).querySelector('.chart');
  document.title = `${view.name} · ${area.name} · Panorama macro`;
  if (built.has(key)) return; built.add(key);
  const tab = sections.get(key);
  setTimeout(() => {  // after the view is laid out; a timer, not rAF, so a background tab still builds
    tab.querySelectorAll('.chart').forEach(el => { if (window.Chart) { el.classList.add('draw'); makeChart(el.querySelector('canvas').id.slice(2)); } });
    tab.querySelectorAll('[data-count]').forEach(countUp);
    tab.querySelectorAll('.range').forEach(el => el.classList.add('grow'));
  }, 0);
}
// Links inside the page and the bars are plain hashes; route them without a reload. Old hashes are rewritten.
addEventListener('hashchange', () => { const h = location.hash.slice(1), [a, v] = find(h); if (OLD_HASH[h]) history.replaceState(null, '', '#' + a.id + '/' + v.id); show(h); });
document.addEventListener('click', ev => {
  const a = ev.target.closest('a[href^="#"]'); if (!a) return;
  if ($('morelist')) { $('morelist').hidden = true; $('more').setAttribute('aria-expanded', 'false'); }
  setTimeout(() => scrollTo({top: 0}), 0);
});
$('more')?.addEventListener('click', () => { const l = $('morelist'); l.hidden = !l.hidden; $('more').setAttribute('aria-expanded', !l.hidden); });

// Arrow keys move between tabs of the same row.
document.addEventListener('keydown', ev => {
  if (ev.target.closest('#search')) return;
  const row = ev.target.closest('#areas, #views, #bottom');
  if ((ev.key === 'ArrowRight' || ev.key === 'ArrowLeft') && row) {
    const tabs = [...row.querySelectorAll('a')], i = tabs.indexOf(ev.target) + (ev.key === 'ArrowRight' ? 1 : -1);
    if (tabs[(i + tabs.length) % tabs.length]) { ev.preventDefault(); tabs[(i + tabs.length) % tabs.length].focus(); tabs[(i + tabs.length) % tabs.length].click(); }
  } else if (ev.key === '/' && !/INPUT|TEXTAREA|SELECT/.test(ev.target.tagName)) { ev.preventDefault(); openSearch(); }
  else if (ev.key === 'Escape') closeSearch();
});

// "Comparar con" switch on chart cards.
document.addEventListener('click', ev => {
  const b = ev.target.closest('.cmp button'); if (!b) return;
  b.parentNode.querySelectorAll('button').forEach(x => x.classList.toggle('on', x === b));
  remake(b.closest('.card').querySelector('canvas'), b.dataset.key);
});

// Search: an index of card titles and indicator names, built from every view's rendered text the first time it is needed.
let index = null;
function buildIndex() {
  index = [];
  for (const a of NAV) for (const v of a.views) {
    const html = v.html || (v.html = v.render()), tpl = document.createElement('template'); tpl.innerHTML = html;
    index.push({text: v.name, area: a.name, href: `${a.id}/${v.id}`, kind: 'vista'});
    tpl.content.querySelectorAll('.card > h3, .tile > .l, .ix .n').forEach(el =>
      index.push({text: el.textContent.trim(), area: a.name + ' · ' + v.name, href: `${a.id}/${v.id}`, kind: el.matches('.tile > .l') ? 'indicador' : 'tarjeta'}));
  }
}
function openSearch() {
  if (!index) buildIndex();
  const box = $('search'); box.hidden = false; const q = box.querySelector('input'); q.value = ''; q.focus(); results('');
}
function closeSearch() { $('search').hidden = true; }
function results(q) {
  q = q.trim().toLowerCase();
  const hits = (q ? index.filter(e => e.text.toLowerCase().includes(q)) : index.filter(e => e.kind === 'vista')).slice(0, 12);
  $('hits').innerHTML = hits.map((e, i) => `<li><a href="#${e.href}" data-t="${esc(e.text)}"><b>${esc(e.text)}</b><span>${esc(e.kind)} · ${esc(e.area)}</span></a></li>`).join('') || '<li class="none">Sin resultados</li>';
}
$('search').querySelector('input').addEventListener('input', ev => results(ev.target.value));
$('search').querySelector('input').addEventListener('keydown', ev => { if (ev.key === 'Enter') $('hits').querySelector('a')?.click(); });
$('hits').addEventListener('click', ev => {
  const a = ev.target.closest('a'); if (!a) return;
  closeSearch(); const t = a.dataset.t;
  setTimeout(() => { const el = [...document.querySelectorAll('.card > h3, .tile > .l, .ix .n')].find(x => x.textContent.trim() === t && !x.closest('[hidden]')); el?.scrollIntoView({block: 'center', behavior: reduce ? 'auto' : 'smooth'}); }, 60);
});
$('search').addEventListener('click', ev => { if (ev.target === $('search')) closeSearch(); });
$('searchbtn').addEventListener('click', openSearch);

$('foot').textContent = `Generado ${D.generated} con python -m macro dashboard · FRED, Banxico SIE, FMI WEO`;
show(location.hash.slice(1));
if (OLD_HASH[location.hash.slice(1)]) { const [a, v] = find(location.hash.slice(1)); history.replaceState(null, '', '#' + a.id + '/' + v.id); }
