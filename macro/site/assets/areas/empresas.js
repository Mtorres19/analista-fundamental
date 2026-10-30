// Empresas (fase 1: los supuestos de valuación; lista y ficha llegan en la fase 3).
AREAS.push({id: 'empresas', name: 'Empresas', views: [
  {id: 'supuestos', name: 'Supuestos', render: () => viewHeader({question: '¿Qué supuestos de valuación salen de la macro?', answer: answer('supuestos'), sources: 'lecturas macro propias, Damodaran'}) +
  `  <div class="split">${why('Por qué estos supuestos', D.reasons['Supuestos'].concat(D.reasons['Riesgo']))}
  <div class="card table-wrap"><table><thead><tr><th>Mercado</th><th>Libre de riesgo</th><th>Prima</th><th>Riesgo país</th><th>Infl. esperada</th>
  <th>Crec. terminal</th><th>Costo de capital</th></tr></thead><tbody>` + D.assumptions.map(a => `<tr>
  <td>${esc(a.market)} <span style="color:var(--muted)">${esc(a.currency)}</span></td><td>${pct(a.rf)}</td><td>${pct(a.erp)}</td><td>${pct(a.crp)}</td>
  <td>${pct(a.infl)}</td><td>${pct(a.g)}</td><td class="strong">${pct(a.coe)}</td></tr>`).join('') + `</tbody></table>
  <p class="note" style="margin-top:10px">Costo de capital con beta 1, en moneda local. Libre de riesgo: bono a 10 años de EE.UU.</p></div></div>`},
]});
