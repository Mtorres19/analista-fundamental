# Correcciones a los métodos, 27 de octubre de 2026

Seguimiento de [validacion-2026-10-27.md](validacion-2026-10-27.md). Corregí el método detrás de cada número que salía fuera de rango o en el límite. Nuestros modelos propios siguen a la vista en el dashboard; el número que se usa después (pronóstico, costo de capital) es el que tiene sustento de mercado. Los valores de "Después" salen del dashboard regenerado el 27-oct-2026 a las 11:08 con datos en vivo.

**Resultado:** en las 23 comparaciones afectadas, antes había 7 en rango, 8 en el límite y 8 fuera de rango; ahora hay 18 en rango, 3 en el límite y 2 fuera de rango. Las dos que quedan fuera tienen explicación (abajo).

## Qué cambió en cada método

| # | Número | Método antes | Método después | Archivo |
|---|---|---|---|---|
| 1 | Riesgo país de México | 1.5 × diferencial real de los bonos a 10 años (incluía la prima cambiaria, que luego se volvía a cobrar al pasar a pesos) | Método de Damodaran: spread de impago × volatilidad relativa de acciones contra bonos. Como spread de impago uso el spread de bonos corporativos emergentes ICE BofA (FRED BAMLEMCBPIOAS, 1.74 pp; no hay CDS soberano gratuito). La volatilidad relativa la calculo yo: desviación del IPC contra la del Bono M a 10 años (cambios de tasa × duración 6.5), 5 años de datos mensuales, ambos en pesos: 1.66 (Damodaran usa 1.77 para México). La conversión a pesos se hace una sola vez, con el diferencial de inflación | `assumptions.py`, `report.py` |
| 2 | Prima de riesgo de mercado | 5% fijo | Prima implícita del S&P 500 que publica Damodaran cada mes (versión con pago sostenible): 4.20% en octubre. `--erp` sigue permitiendo fijarla a mano | `sources.py` (`damodaran`), `report.py` |
| 3 | Inflación de EE.UU. y México a 12 meses | Promedio de tendencia y reversión: extrapolaba el choque del petróleo | Promedio de nuestra reversión a la media y la vista externa: inflación esperada a 1 año de la Fed de Cleveland en EE.UU., mediana de la encuesta de Banxico a 12 meses en México. La tendencia y la reversión siguen dibujadas como "modelo puro" | `dashboard.py` |
| 4 | Brent y cobre | Promedio de tendencia y reversión | Promedio de la reversión y la curva de futuros (contratos BZ y HG de los próximos 15 meses vía Yahoo) | `sources.py` (`yahoo_curve`), `dashboard.py` |
| 5 | Tasas de la Fed y de Banxico | Promedio de modelos. Ancla: convergencia a la neutral nominal | Pronóstico: promedio de la reversión y la vista externa (futuros de Fed funds; Cete 28 al cierre de año de la encuesta de Banxico, no el forward de la curva, que trae prima por plazo). Ancla propia: regla de Taylor = neutral nominal + 0.5 × (inflación − meta) + 0.5 × brecha de producto (Okun: −2 × (desempleo − su nivel de largo plazo; Fed para EE.UU., promedio de 10 años para México)); la distancia se reduce a la mitad cada año | `neutral.py`, `dashboard.py` |
| 6 | Inflación esperada de México en la valuación | Promedio del FMI a 5 años (3.14%) | Encuesta de Banxico: mediana a 1–4 años (3.80%) para convertir el costo de capital y a 5–8 años (3.70%) para el crecimiento terminal | `assumptions.py`, `report.py` |
| 7 | Crecimiento terminal | Crecimiento de tendencia (10 años, con la caída de 2020) + inflación esperada | Crecimiento real de largo plazo del consenso (Fed: 2.0%; encuesta Banxico a 10 años: 1.8%) + inflación esperada de largo plazo, con el mismo tope en la tasa a 10 años. Nuestra tendencia, ahora calculada sin 2020-2021, queda a la vista: 2.61% en EE.UU. y 1.73% en México | `snapshot.py`, `assumptions.py` |
| 8 | Peso real contra su promedio de 10 años | Tipo de cambio real bilateral contra el dólar | Medida principal: tipo de cambio real efectivo amplio del BIS (FRED RBMXBIS). La bilateral se conserva como secundaria | `snapshot.py`, `sources.py` |

## Antes y después

| Métrica | Horizonte | Antes | Después | Referencia | Fuente | Dif. antes | Dif. después | Tol. | Veredicto antes → después |
|---|---|---|---|---|---|---|---|---|---|
| Inflación EE.UU. 12m, pronóstico usado | sep-2027 | 3.88 | 3.39 | 2.98 — Fed de Cleveland, 1 año | FRED, oct-2026 | +0.90 pp | +0.41 pp | ±0.5 pp | en el límite → **en rango** |
| Inflación EE.UU. 12m, pronóstico usado | sep-2027 | 3.88 | 3.39 | 2.47 — Breakeven 5 años (T5YIE) | FRED, 26-oct-2026 | +1.41 pp | +0.92 pp | ±0.5 pp | fuera de rango → **en el límite** |
| Inflación EE.UU. 12m, pronóstico usado | 2027 | 3.88 | 3.39 | 2.30 — Mediana SEP, PCE 2027 | Fed SEP, 17-sep-2026 | +1.58 pp | +1.09 pp | ±0.5 pp | fuera de rango → **fuera de rango** |
| Tasa Fed, pronóstico usado | oct-2027 | 3.96 | 4.33 | 4.62 — Futuros (100 − precio) | Futuros Fed funds ZQX27, 26-oct-2026 | -0.66 pp | -0.29 pp | ±0.5 pp | en el límite → **en rango** |
| Tasa Fed, pronóstico usado | fin de 2027 | 3.96 | 4.33 | 4.10 — Mediana SEP | Fed SEP, 17-sep-2026 | -0.14 pp | +0.23 pp | ±0.5 pp | en rango → **en rango** |
| Tasa Fed, ancla propia (antes neutral, ahora Taylor) | oct-2027 | 3.62 | 4.05 | 4.62 — Futuros | Futuros Fed funds ZQX27, 26-oct-2026 | -1.00 pp | -0.57 pp | ±0.5 pp | en el límite → **en el límite** |
| Tasa Fed, ancla propia (antes neutral, ahora Taylor) | fin de 2027 | 3.62 | 4.05 | 4.10 — Mediana SEP | Fed SEP, 17-sep-2026 | -0.48 pp | -0.05 pp | ±0.5 pp | en rango → **en rango** |
| Inflación México 12m, pronóstico usado | sep-2027 | 3.72 | 4.12 | 4.16 — Mediana 12 meses | Encuesta Banxico, sep-2026 | -0.44 pp | -0.04 pp | ±0.5 pp | en rango → **en rango** |
| Tasa Banxico, pronóstico usado | oct-2027 | 6.48 | 6.64 | 6.50 — Mediana Cete 28 al cierre de 2027 | Encuesta Banxico, sep-2026 | -0.02 pp | +0.14 pp | ±0.5 pp | en rango → **en rango** |
| Tasa Banxico, ancla propia (antes neutral, ahora Taylor) | oct-2027 | 5.73 | 6.13 | 6.50 — Mediana Cete 28 al cierre de 2027 | Encuesta Banxico, sep-2026 | -0.77 pp | -0.37 pp | ±0.5 pp | en el límite → **en rango** |
| Tasa Banxico, pronóstico usado | oct-2027 | 6.48 | 6.64 | 8.13 — Forward 1a1a de Cetes (ya no se usa: trae prima por plazo) | Banxico vector, 26-oct-2026 | -1.65 pp | -1.49 pp | ±0.5 pp | fuera de rango → **fuera de rango** |
| Pesos por dólar, pronóstico usado | oct-2027 | 18.87 | 18.87 | 18.04 — Mediana cierre 2027 (encuesta de septiembre, con spot de 17.2) | Encuesta Banxico, sep-2026 | +4.6% | +4.6% | ±3% | en el límite → **en el límite** |
| Pesos por dólar, pronóstico usado | oct-2027 | 18.87 | 18.87 | 19.13 — Forward por diferencial de tasas | Banxico/FRED, 26-oct-2026 | -1.4% | -1.4% | ±3% | en rango → **en rango** |
| Brent, pronóstico usado | oct-2027 | 108.43 | 87.79 | 89.39 — Futuro Brent oct-2027 | ICE vía Yahoo, 27-oct-2026 | +21.3% | -1.8% | ±10% | fuera de rango → **en rango** |
| Cobre, pronóstico usado | oct-2027 | 6.76 | 6.72 | 6.88 — Futuro cobre oct-2027 | COMEX vía Yahoo, 27-oct-2026 | -1.7% | -2.3% | ±10% | en rango → **en rango** |
| Peso real vs su promedio de 10 años (+ = más fuerte) | hoy | 10.48 | 21.16 | 21.16 — BIS REER (RBMXBIS) | BIS vía FRED, jul-2026 | -10.68 pp | +0.00 pp | ±5 pp | fuera de rango → **en rango** |
| Prima de riesgo de mercado (ERP) | largo plazo | 5.00 | 4.20 | 4.20 — ERP implícita S&P 500 (pago sostenible) | Damodaran (ene-2026 / 1-oct-2026) | +0.80 pp | +0.00 pp | ±1 pp | en rango → **en rango** |
| Costo de capital EE.UU. (USD) | largo plazo | 10.00 | 9.20 | 8.99 — Rendimiento esperado implícito S&P 500 | Damodaran (ene-2026 / 1-oct-2026) | +1.01 pp | +0.21 pp | ±1 pp | en el límite → **en rango** |
| Riesgo país México (CRP) | largo plazo | 5.25 | 2.88 | 2.47 — CRP Damodaran México | Damodaran (ene-2026 / 1-oct-2026) | +2.78 pp | +0.41 pp | ±1 pp | fuera de rango → **en rango** |
| Costo de capital México (MXN) | largo plazo | 16.15 | 13.68 | 13.26 — Equivalente con insumos de Damodaran y la encuesta | Damodaran (ene-2026 / 1-oct-2026); Encuesta Banxico, sep-2026 | +2.89 pp | +0.42 pp | ±1 pp | fuera de rango → **en rango** |
| Inflación esperada México en valuación | 1–4 años | 3.14 | 3.80 | 3.80 — Mediana 1–4 años | Encuesta Banxico, sep-2026 | -0.66 pp | +0.00 pp | ±0.5 pp | en el límite → **en rango** |
| Crecimiento terminal EE.UU. (nominal) | largo plazo | 4.84 | 4.34 | 4.00 — SEP LR: PIB 2.0% + PCE 2.0% | Fed SEP, 17-sep-2026 | +0.84 pp | +0.34 pp | ±0.5 pp | en el límite → **en rango** |
| Crecimiento terminal México (nominal) | largo plazo | 4.32 | 5.50 | 5.50 — Encuesta: PIB 10a 1.8% + inflación 5–8a 3.7% | Encuesta Banxico, sep-2026 | -1.18 pp | +0.00 pp | ±0.5 pp | fuera de rango → **en rango** |

## Lo que sigue fuera de rango o en el límite

- **Inflación de EE.UU. contra la proyección de la Fed (3.39% contra 2.30%, fuera de rango).** La Fed proyecta PCE y nosotros CPI; el CPI suele correr 0.3–0.4 pp arriba, así que la diferencia comparable es de unos 0.7 pp (en el límite). Contra la Fed de Cleveland, que es la que usamos de ancla, estamos en rango (+0.41 pp). El resto es nuestra reversión a la media (3.80%), que todavía ve la inflación actual como persistente.
- **Banxico contra el forward de los Cetes (6.64% contra 8.13%, fuera de rango).** Ya no lo usamos como referencia: el forward a un año de la curva de Cetes trae prima por plazo y el Cete a 2 años tiene poca liquidez. Contra la encuesta, que sí es una expectativa de la tasa, estamos en rango.
- **Ancla de Taylor de la Fed contra futuros (4.05% contra 4.62%, en el límite).** Contra la mediana de la Fed (4.10%) está en rango. El mercado descuenta más alzas que las que pide la regla con desempleo en su nivel de largo plazo.
- **Peso a 12 meses contra la encuesta (18.87 contra 18.04, en el límite).** La encuesta es de septiembre, cuando el peso cotizaba en 17.2–17.5; hoy está en 18.66. Contra el forward por diferencial de tasas (19.13) estamos en rango.
- **Tipo de cambio real y crecimiento terminal de México** ahora coinciden con su referencia porque usan esa misma fuente (BIS y la encuesta de Banxico). La medida propia queda a la vista para comparar: tipo de cambio real bilateral 10.5% más fuerte y tendencia de 1.73%.

*Nada de esto es recomendación de inversión.*
