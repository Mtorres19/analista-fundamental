# Estructura del sitio: especificación para construir

Diseño aprobado por Marco el 30-oct-2026 (doc: https://claude.ai/artifact/5G3w2zZeT9TwFaFTSEXsjG).
Este archivo es la guía técnica para quien escriba el código. Se construye en 4 fases, un PR por fase.

## Reglas que no cambian

- Interfaz en español. Estilo oscuro sobrio actual (variables `--ink`, `--s1`… de `macro/dashboard.py`); nada de neón.
- Sitio estático: `python -m macro dashboard --out site/index.html` sigue generando UNA página HTML con los datos
  incrustados en `<script id="data">`. GitHub Actions (`.github/workflows/dashboard.yml`) la publica en Pages. Sin
  servidor, sin bundler, sin framework JS. Chart.js sigue siendo la única librería.
- Fuentes permitidas: FRED, Banxico SIE, FMI, BIS, SEC EDGAR, CFTC, Damodaran (NYU), yfinance. Prohibido extraer de
  CME, MexDer, BMV, Valmer o Investing.com (sus términos lo prohíben; ver `reference` en la memoria del proyecto).
- El token de Banxico solo vive en el secreto `BANXICO_TOKEN`. Nunca en código, tests ni logs.
- Las sesiones en la nube no llegan a las fuentes de datos (proxy 403). Todo se prueba con `fake_fetch` y `fake_weo`
  de `tests/test_macro.py`; las corridas reales son en la Mac de Marco o en Actions.
- `pytest -q` en verde antes de cada push.

## Arquitectura objetivo

Hoy todo está en `macro/dashboard.py` (1,237 líneas: Python que arma el payload + un string `HTML` con CSS y JS).
Se parte así, sin cambiar el resultado (una sola página):

```
macro/site/
  __init__.py        build_dashboard(): arma el payload y ensambla la página (lo que hoy hace dashboard.py)
  payload.py         funciones _kpis, _specs, _chart, _rates_payload, etc., movidas tal cual
  reasons.py         reasons(), _country_reasons(), _rate_reasons() movidas tal cual
  assets/
    page.html        esqueleto: <nav>, <main id="app">, <footer>, marcadores __CSS__ __JS__ __DATA__ __ASOF__
    styles.css       el CSS actual
    core.js          helpers comunes (esc, pct, num, emph, stamp, charts, crosshair, rangos, countUp)
    components.js    las seis piezas de interfaz (abajo)
    router.js        navegación de dos niveles
    areas/hoy.js  macro.js  tasas.js  fx.js  mercados.js  sectores.js  empresas.js  reportes.js
```

`build_dashboard` lee los assets con `importlib.resources`, concatena los JS en orden (core, components, áreas,
router) y los incrusta. `macro/dashboard.py` queda como `from macro.site import build_dashboard` para no romper
`__main__.py` ni los tests. Agregar `macro/site/assets/**` a `package-data` en `pyproject.toml`.

Cada `areas/<area>.js` registra sus vistas:

```js
AREAS.push({id: 'tasas', name: 'Tasas', views: [
  {id: 'politica', name: 'Política monetaria', render: () => `...html...`},
  {id: 'curvas', name: 'Curvas', render: () => `...`},
]});
```

`render()` devuelve HTML; el router lo inserta la primera vez que se abre la vista y luego construye sus gráficas
(como hace hoy `show()` con `built`).

## Las 8 áreas y de dónde sale cada vista

| Área (`id`) | Vistas (`id`) | Fase | Contenido actual que se mueve ahí |
| --- | --- | --- | --- |
| Hoy (`hoy`) | `resumen`, `alertas`, `calendario` | 1 | sección `resumen` (héroe, mapa de régimen, "Lo más importante"), `D.flags` |
| Macro (`macro`) | `mundo`, `eeuu`, `mexico`, `comercio`, `pronosticos` | 1 | `SECTIONS` (mundo/eeuu/mexico), sección `comercio`, sección `pronosticos` |
| Tasas (`tasas`) | `politica`, `curvas`, `neutral`, `riesgo-pais` | 1 | sección `probabilidades`; sección `curvas` partida en curvas / tasa neutral; diferencial MX-EE.UU. y CRP a `riesgo-pais` |
| Tipo de cambio (`fx`) | `nivel`, `carry`, `valor-real`, `posicionamiento` | 1 parcial, 2 completo | gráfica `MX_fx`, carry y brecha real del resumen, volatilidad del peso (policy.py) |
| Mercados (`mercados`) | `indices`, `materias-primas`, `volatilidad` | 1 | sección `mercados`; brent/cobre/dólar/VIX de Mundo; VIX, MOVE y sesgo de SPY de probabilidades |
| Sectores (`sectores`) | `rotacion`, `valuacion`, `sensibilidad` | 2 | nuevo |
| Empresas (`empresas`) | `lista`, `ficha`, `supuestos` | 1 (`supuestos`), 3 el resto | sección `valuacion` va a `supuestos` |
| Reportes (`reportes`) | `notas`, `trimestrales`, `bitacora` | 4 | nuevo |

En la fase 1, un área sin contenido todavía no aparece en la navegación (no se muestran pantallas vacías).

## Navegación (`router.js`)

- URL `#<area>/<vista>`; `#<area>` abre su primera vista; sin hash abre `#hoy/resumen`.
- Redirecciones de los hashes viejos (hay enlaces guardados): `#resumen→#hoy/resumen`, `#mundo→#macro/mundo`,
  `#eeuu→#macro/eeuu`, `#mexico→#macro/mexico`, `#curvas→#tasas/curvas`, `#probabilidades→#tasas/politica`,
  `#mercados→#mercados/indices`, `#comercio→#macro/comercio`, `#pronosticos→#macro/pronosticos`,
  `#valuacion→#empresas/supuestos`.
- Escritorio: barra superior con las áreas; debajo, subpestañas de la vista. Accesible: `role="tablist"`,
  `aria-selected`, flechas izquierda/derecha entre pestañas.
- Celular (< 720 px): barra inferior fija con Hoy, Macro, Tasas, Tipo de cambio, Mercados; las demás en un botón
  "Más". Subpestañas con scroll horizontal.
- Búsqueda: tecla `/` abre un cuadro que filtra un índice de {título de tarjeta, indicador, vista} construido al
  cargar desde `D.kpis`, `D.charts`, `D.specs`; Enter navega a la vista y hace scroll a la tarjeta.
- El selector de periodo (`.ranges`) solo se muestra en vistas con gráficas de tiempo (la lógica ya existe).

## Las seis piezas comunes (`components.js`)

1. `viewHeader({question, answer, asOf, sources})`: pregunta de la vista, respuesta en una frase, fecha y fuentes.
2. `kpiStrip(list)`: 3 a 5 tarjetas; cada una `{label, value, unit, d1, d30, tone, link}`. `d1` y `d30` son el
   cambio contra el dato anterior y contra hace un mes; se calculan en Python (abajo).
3. `why(title, reasons)`: la lista "Por qué está así" que ya existe.
4. `chartCard(key, {title, note, compare})`: tarjeta de gráfica actual + un interruptor "comparar con" cuando
   `compare` trae opciones (p. ej. la misma serie del otro país o hace 12 meses).
5. `denseTable({columns, rows, keyColumn})`: columnas con `hideSm: true` se ocultan en celular (como `probTable`).
6. `crossLink(text, '#area/vista')`: enlace a donde se usa un dato.

Toda vista sigue el orden: `viewHeader`, `kpiStrip`, alertas de esa vista, `why` a la izquierda y gráficas a la
derecha (la clase `.split` actual), tablas al final.

## Cambios de datos en la fase 1 (Python)

- `d1`/`d30` en cada KPI: en `payload._kpis` guardar, además del valor, el valor de la observación anterior y el de
  hace ~30 días de la misma serie. Test: con `fake_fetch`, un KPI con serie creciente tiene `d1 > 0`.
- `D.changes`: lista "Qué cambió desde ayer" para Hoy: los KPIs cuyo `d1` supera 1 desviación estándar de sus
  cambios diarios (o mensuales en series mensuales), ordenados por tamaño. Máximo 8.
- `D.calendar`: próximos 30 días a partir de `policy.FOMC` y `policy.BANXICO`. INEGI, BLS y reportes de empresas
  se agregan en la fase 2 (fechas fijas en una lista, con el mismo comentario `shortcut:` que usa policy.py).
- `D.summary` de Hoy agrega una frase de "respuesta" por área (la primera razón de cada `reasons`).

## Fase 2: Tipo de cambio y Sectores

- `sources.py`: ETFs sectoriales del S&P (XLB, XLC, XLE, XLF, XLI, XLK, XLP, XLRE, XLU, XLV, XLY) por yfinance;
  reporte COT de la CFTC para el peso (contrato 095741, archivo público anual de "Legacy futures only");
  múltiplos por sector de Damodaran (`pedata.xls`, actualización anual).
- Sectores de México: índice propio igual-ponderado con emisoras del IPC por sector (lista fija en código con
  `shortcut:`), precios de yfinance. No usar índices sectoriales de BMV.
- `macro/fx.py`: carry ajustado por volatilidad (diferencial de tasas a 3m / volatilidad realizada 3m), tipo de
  cambio real (ya existe la brecha en snapshot), posición neta de especuladores, bandas de 1 y 2 desviaciones.
- `macro/sectors.py`: rendimiento 1m/3m/año por sector, múltiplo actual vs su mediana de 10 años, matriz
  sector × régimen (rendimiento histórico medio de cada sector en cada régimen de `snapshot`), beta a la tasa a 10
  años y al USD/MXN.

## Fase 3: Empresas

- Lista de seguimiento en `watchlist.toml` (ticker, mercado, sector). EE.UU.: estados financieros de SEC EDGAR
  con edgartools; México: yfinance (validar cobertura; no extraer de BMV).
- `macro/valuation.py` (o un paquete `equity/`): DCF de 2 etapas con `assumptions.cost_of_equity()` y crecimiento
  terminal de `assumptions`, comparables del mismo sector, margen de seguridad, veredicto
  (comprar / mantener / vender) con sus razones.
- Ficha: veredicto y precio objetivo, tesis en tres líneas, valuación (rango DCF y comparables), salud financiera,
  sensibilidad a tasas y peso (betas de fase 2), riesgos.

## Fase 4: Reportes

- Publicar en el sitio los reportes de `reportes/` (hoy ignorados por git): nota diaria generada en cada corrida,
  nota semanal los viernes.
- Bitácora: cada veredicto de la fase 3 se guarda con fecha y precio; la vista mide el rendimiento posterior contra
  el IPC o el S&P 500. Requiere persistir estado entre corridas (un JSON en una rama `datos` del repo).

## Criterios de aceptación de la fase 1

- Todo el contenido actual aparece en alguna vista; ningún número cambia (comparar `D` antes y después, salvo los
  campos nuevos).
- Los 10 hashes viejos redirigen.
- `pytest -q` pasa; `test_dashboard_page` cubre que la página tenga las 6 áreas con contenido en fase 1 (Hoy, Macro, Tasas, Tipo de cambio, Mercados, Empresas) y el payload
  `changes` y `calendar`.
- Render revisado con Playwright a 1280 px y 390 px (ver memoria `project-dashboard-review` para cómo cargar
  Chart.js sin red).
