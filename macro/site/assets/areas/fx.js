// Tipo de cambio (fase 1: nivel y carry; valor real y posicionamiento llegan en la fase 2).
AREAS.push({id: 'fx', name: 'Tipo de cambio', views: [
  {id: 'nivel', name: 'Nivel', render: () => viewHeader({question: '¿Dónde está el peso y qué tan caro o barato?', answer: answer('nivel'), sources: 'Banxico SIE, BIS'}) +
    kpiStrip(D.kpis['México'].filter(k => k.label === 'Peso por dólar')) + split(why('Por qué está así', D.reasons['México']), card('MX_fx'))},
  {id: 'carry', name: 'Carry', render: () => viewHeader({question: '¿Paga el carry del peso?', answer: answer('carry'), sources: 'Banxico SIE, FRED'}) +
    kpiStrip(D.kpis['México'].filter(k => ['Carry vs EE.UU.', 'Tasa de política', 'Tasa neutral'].includes(k.label)).map(k => ({...k, link: ['ver Banxico', '#macro/mexico']})))},
]});
