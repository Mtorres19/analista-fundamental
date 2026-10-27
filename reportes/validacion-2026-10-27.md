# Validación de nuestros cálculos contra el mercado, 27 de octubre de 2026

Comparé cada número que calcula el modelo (pronósticos, tasa neutral, curvas, riesgo y supuestos de valuación) con la mejor referencia de mercado o de consenso que se puede obtener gratis hoy. Los valores propios salen del dashboard generado el 27-oct-2026 a las 10:12 desde la rama `mercados-diarios`.

**Resultado:** 44 comparaciones. 26 están en rango, 10 en el límite y 8 fuera de rango. No encontré errores de código. Lo que sale de rango son decisiones de método, y la mayoría tiene una explicación concreta (abajo).

**Tolerancias:** inflación, tasas de política, PIB, desempleo, r* y crecimiento terminal ±0.5 pp; rendimientos y spreads ±0.25 pp (pendientes y breakevens ±0.10 pp); ajuste de curva ±15 pb; probabilidad de recesión ±5 pp; prima de mercado, costo de capital y riesgo país ±1 pp; tipo de cambio ±3%; materias primas ±10%. "En el límite" significa entre una y dos veces la tolerancia.

| Métrica | Horizonte | Nuestro | Referencia | Fuente y fecha | Diferencia | Tolerancia | Veredicto |
|---|---|---|---|---|---|---|---|
| Inflación EE.UU. (CPI a/a), promedio de modelos | sep-2027 | 3.88 | 2.98 — Fed de Cleveland, inflación esperada a 1 año (EXPINF1YR) | FRED, oct-2026 | +0.90 pp | ±0.5 pp | **en el límite** |
| Inflación EE.UU. (CPI a/a), promedio de modelos | sep-2027 | 3.88 | 2.47 — Breakeven 5 años (T5YIE) | FRED, 26-oct-2026 | +1.41 pp | ±0.5 pp | **fuera de rango** |
| Inflación EE.UU., promedio de modelos | 2027 | 3.88 | 2.30 — Mediana SEP, PCE 2027 (el PCE suele correr 0.3–0.4 pp abajo del CPI) | Fed SEP (FRED FEDTARMD/PCECTPIMD/UNRATEMD/GDPC1MD), 17-sep-2026 | +1.58 pp | ±0.5 pp | **fuera de rango** |
| Tasa Fed, promedio de modelos | oct-2027 | 3.96 | 4.62 — Tasa implícita en futuros (100 − precio) | Futuros de Fed funds CME ZQX27 (Yahoo), 26-oct-2026 | -0.66 pp | ±0.5 pp | **en el límite** |
| Tasa Fed, promedio de modelos | fin de 2027 | 3.96 | 4.10 — Mediana SEP fin de 2027 | Fed SEP (FRED FEDTARMD/PCECTPIMD/UNRATEMD/GDPC1MD), 17-sep-2026 | -0.14 pp | ±0.5 pp | **en rango** |
| Tasa Fed, convergencia a neutral (ancla) | oct-2027 | 3.62 | 4.62 — Tasa implícita en futuros | Futuros de Fed funds CME ZQX27 (Yahoo), 26-oct-2026 | -1.00 pp | ±0.5 pp | **en el límite** |
| Desempleo EE.UU., promedio de modelos | sep-2027 | 4.32 | 4.10 — Mediana SEP 2027 | Fed SEP (FRED FEDTARMD/PCECTPIMD/UNRATEMD/GDPC1MD), 17-sep-2026 | +0.22 pp | ±0.5 pp | **en rango** |
| PIB EE.UU. a/a, promedio de modelos | 2T-2027 | 2.29 | 2.40 — Mediana SEP 2027 | Fed SEP (FRED FEDTARMD/PCECTPIMD/UNRATEMD/GDPC1MD), 17-sep-2026 | -0.11 pp | ±0.5 pp | **en rango** |
| PIB EE.UU. a/a, promedio de modelos | 2T-2027 | 2.29 | 2.10 — FMI WEO 2027 | FMI WEO, oct-2026 | +0.19 pp | ±0.5 pp | **en rango** |
| Inflación México (INPC a/a), promedio de modelos | sep-2027 | 3.72 | 4.16 — Mediana, inflación próximos 12 meses | Banxico, Encuesta de expectativas del sector privado (SIE SR14xxx), sep-2026 | -0.44 pp | ±0.5 pp | **en rango** |
| Inflación México, promedio de modelos | fin de 2027 | 3.72 | 3.82 — Mediana, inflación al cierre de 2027 | Banxico, Encuesta de expectativas del sector privado (SIE SR14xxx), sep-2026 | -0.10 pp | ±0.5 pp | **en rango** |
| Tasa Banxico, promedio de modelos | oct-2027 | 6.48 | 6.50 — Mediana, Cete 28 días al cierre de 2027 | Banxico, Encuesta de expectativas del sector privado (SIE SR14xxx), sep-2026 | -0.02 pp | ±0.5 pp | **en rango** |
| Tasa Banxico, convergencia a neutral (ancla) | oct-2027 | 5.73 | 6.50 — Mediana, Cete 28 días al cierre de 2027 | Banxico, Encuesta de expectativas del sector privado (SIE SR14xxx), sep-2026 | -0.77 pp | ±0.5 pp | **en el límite** |
| Tasa Banxico, promedio de modelos | oct-2027 | 6.48 | 8.13 — Forward 1 año dentro de 1 año de la curva de Cetes (364 días 7.08% y 2 años 7.91%) | Banxico vector de precios, 26-oct-2026 | -1.65 pp | ±0.5 pp | **fuera de rango** |
| PIB México a/a, promedio de modelos | 2T-2027 | 1.92 | 1.80 — Mediana, PIB 2027 | Banxico, Encuesta de expectativas del sector privado (SIE SR14xxx), sep-2026 | +0.12 pp | ±0.5 pp | **en rango** |
| PIB México a/a, promedio de modelos | 2T-2027 | 1.92 | 2.20 — FMI WEO 2027 | FMI WEO, oct-2026 | -0.28 pp | ±0.5 pp | **en rango** |
| Pesos por dólar, promedio de modelos | oct-2027 | 18.87 | 18.04 — Mediana, tipo de cambio al cierre de 2027 | Banxico, Encuesta de expectativas del sector privado (SIE SR14xxx), sep-2026 | +4.6% | ±3% | **en el límite** |
| Pesos por dólar, promedio de modelos | oct-2027 | 18.87 | 19.13 — Forward a 1 año por diferencial de tasas (18.66 × 1.0708 / 1.0444) | Banxico Cetes 364d y FRED DGS1, 26-oct-2026 | -1.4% | ±3% | **en rango** |
| Brent, promedio de modelos | oct-2027 | 108.43 | 88.16 — Futuro Brent nov-2027 (BZX27) | ICE vía Yahoo, 26-oct-2026 | +23.0% | ±10% | **fuera de rango** |
| Brent, reversión a la media (AR) | oct-2027 | 86.19 | 88.16 — Futuro Brent nov-2027 (BZX27) | ICE vía Yahoo, 26-oct-2026 | -2.2% | ±10% | **en rango** |
| Cobre COMEX, promedio de modelos | oct-2027 | 6.76 | 6.91 — Futuro cobre nov-2027 (HGX27) | COMEX vía Yahoo, 26-oct-2026 | -2.2% | ±10% | **en rango** |
| r* EE.UU. (nuestro) | largo plazo | 1.36 | 1.01 — Holston-Laubach-Williams 2T-2026 | NY Fed, publicado 2026 | +0.35 pp | ±0.5 pp | **en rango** |
| Tasa neutral nominal EE.UU. (r* + 2%) | largo plazo | 3.36 | 3.20 — Mediana SEP de largo plazo (FEDTARMDLR) | Fed SEP (FRED FEDTARMD/PCECTPIMD/UNRATEMD/GDPC1MD), 17-sep-2026 | +0.16 pp | ±0.5 pp | **en rango** |
| r* México (nuestro) | largo plazo | 1.95 | 2.60 — Punto medio del rango de Banxico 1.8–3.4% (Informe Trimestral abr–jun 2019) | Banxico, 2019 | -0.65 pp | ±0.5 pp | **en el límite** |
| Probabilidad de recesión EE.UU. | 12 meses | 15.00 | 12.80 — Modelo de curva de la Fed de NY (spread de sep-2026 → sep-2027) | NY Fed allmonth.xls, oct-2026 | +2.20 pp | ±5 pp | **en rango** |
| Pendiente 10a − 2a EE.UU. | hoy | 0.31 | 0.32 — T10Y2Y | FRED, 26-oct-2026 | -0.01 pp | ±0.1 pp | **en rango** |
| Pendiente 10a − 3m EE.UU. | hoy | 0.78 | 0.78 — T10Y3M | FRED, 26-oct-2026 | +0.00 pp | ±0.1 pp | **en rango** |
| Inflación implícita 10a EE.UU. (10a − TIPS) | 10 años | 2.34 | 2.34 — T10YIE | FRED, 26-oct-2026 | +0.00 pp | ±0.1 pp | **en rango** |
| Bono M ~10 años (TIR calculada del vector) | 9.3 años | 9.36 | 9.35 — OCDE, bono 10 años México, promedio sep-2026 (IRLTLT01MXM156N) | FRED/OCDE, sep-2026 | +0.01 pp | ±0.25 pp | **en rango** |
| Bono M ~10 años (TIR calculada del vector) | 9.3 años | 9.36 | 9.25 — Última subasta Bono M 10 años (SF44071) | Banxico, 22-oct-2026 | +0.11 pp | ±0.25 pp | **en rango** |
| Udibono ~10 años (TIR real calculada del vector) | 10.5 años | 4.86 | 5.00 — Última subasta Udibono 10 años (SF43924) | Banxico, 1-oct-2026 | -0.14 pp | ±0.25 pp | **en rango** |
| Ajuste NSS curva EE.UU., error máximo vs nodos | todos | 0.03 | 0.00 — Nodos observados | FRED, 26-oct-2026 | +0.03 pp | ±0.15 pp | **en rango** |
| Ajuste NSS curva México, error máximo vs nodos | todos | 0.14 | 0.00 — Nodos observados | Banxico vector, 26-oct-2026 | +0.14 pp | ±0.15 pp | **en rango** |
| Diferencial MX − EE.UU. 10 años | 10 años | 4.36 | 4.35 — OCDE México 10a (9.35%) − Treasury 10a (5.00%) | FRED, sep/oct-2026 | +0.01 pp | ±0.25 pp | **en rango** |
| Carry MX − EE.UU. (tasas de política) | hoy | 2.62 | 2.64 — Cetes 364d − Treasury 1 año | Banxico/FRED, 26-oct-2026 | -0.02 pp | ±0.25 pp | **en rango** |
| Inflación implícita México 10a (Bono M − Udibono) | 10 años | 4.50 | 3.70 — Mediana, inflación esperada a 5–8 años | Banxico, Encuesta de expectativas del sector privado (SIE SR14xxx), sep-2026 | +0.80 pp | ±0.5 pp | **en el límite** |
| Peso real vs su promedio de 10 años (+ = más fuerte) | hoy | 10.48 | 21.16 — Tipo de cambio real efectivo amplio BIS (RBMXBIS) vs su promedio de 10 años | BIS vía FRED, jul-2026 | -10.68 pp | ±5 pp | **fuera de rango** |
| Prima de riesgo de mercado EE.UU. (ERP) | largo plazo | 5.00 | 4.20 — ERP implícita del S&P 500 (T12m) | Damodaran, ctryprem.xlsx (ene-2026) y ERPbymonth.xlsx (1-oct-2026) | +0.80 pp | ±1 pp | **en rango** |
| Costo de capital EE.UU. (beta 1, USD) | largo plazo | 10.00 | 8.99 — Rendimiento esperado implícito del S&P 500 | Damodaran, ctryprem.xlsx (ene-2026) y ERPbymonth.xlsx (1-oct-2026) | +1.01 pp | ±1 pp | **en el límite** |
| Riesgo país México (CRP) | largo plazo | 5.25 | 2.47 — CRP de Damodaran para México (Baa2, CDS 10a 1.66% × volatilidad relativa) | Damodaran, ctryprem.xlsx (ene-2026) y ERPbymonth.xlsx (1-oct-2026) | +2.78 pp | ±1 pp | **fuera de rango** |
| Costo de capital México (beta 1, MXN) | largo plazo | 16.15 | 13.26 — Equivalente con insumos de mercado: (1 + 5.0% + 4.2% + 2.47%) × (1 + 3.80%) / (1 + 2.34%) − 1 | Damodaran, ctryprem.xlsx (ene-2026) y ERPbymonth.xlsx (1-oct-2026); Banxico, Encuesta de expectativas del sector privado (SIE SR14xxx), sep-2026 | +2.89 pp | ±1 pp | **fuera de rango** |
| Inflación esperada México usada en la valuación | 5 años | 3.14 | 3.80 — Mediana, inflación esperada a 1–4 años | Banxico, Encuesta de expectativas del sector privado (SIE SR14xxx), sep-2026 | -0.66 pp | ±0.5 pp | **en el límite** |
| Crecimiento terminal EE.UU. (nominal) | largo plazo | 4.84 | 4.00 — SEP de largo plazo: PIB 2.0% + PCE 2.0% | Fed SEP (FRED FEDTARMD/PCECTPIMD/UNRATEMD/GDPC1MD), 17-sep-2026 | +0.84 pp | ±0.5 pp | **en el límite** |
| Crecimiento terminal México (nominal) | largo plazo | 4.32 | 5.50 — Encuesta: PIB 10 años 1.8% + inflación 5–8 años 3.7% | Banxico, Encuesta de expectativas del sector privado (SIE SR14xxx), sep-2026 | -1.18 pp | ±0.5 pp | **fuera de rango** |

## Lo que sale de rango y por qué

1. **Inflación de EE.UU. a 12 meses (3.88% contra 2.3–3.0%).** Nuestros modelos extrapolan la inflación actual, que viene empujada por el choque del petróleo (Brent +76% anual). El mercado (breakeven a 5 años de 2.47%), la Fed de Cleveland (2.98%) y la Fed (PCE de 2.3% en 2027) esperan que baje. No es un error, pero el pronóstico no es consistente con el mercado. *Sugerencia:* agregar la inflación esperada de mercado como ancla, igual que la tasa neutral en las tasas.
2. **Tasa de Banxico contra el forward de Cetes (6.48% contra 8.13%).** El forward a un año que sale de los Cetes de 364 días y de 2 años incluye prima por plazo; el Cete a 2 años además tiene poca liquidez. La encuesta de Banxico (6.50% al cierre de 2027) coincide con nosotros. Diferencia defendible: el forward no es una expectativa pura.
3. **Brent con el promedio de modelos (108 USD contra 88 USD del futuro).** La línea de tendencia proyecta parte del choque. Los futuros tienen fuerte backwardation (114 USD en dic-2026, 88 USD en nov-2027), y nuestra reversión a la media (86 USD) sí está en rango. *Sugerencia:* en materias primas, usar la curva de futuros como ancla en lugar de la tendencia.
4. **Peso real contra su promedio de 10 años (10.5% contra 21.2% más fuerte).** Medimos el tipo de cambio real bilateral contra el dólar con INPC/CPI; el BIS usa una canasta amplia de socios comerciales. Las dos medidas dicen lo mismo, que el peso está caro, pero con magnitud distinta. Diferencia defendible.
5. **Riesgo país de México (5.25 pp contra 2.47 pp de Damodaran).** Es el hallazgo más importante. Calculamos el riesgo país como 1.5 veces el diferencial real de los bonos a 10 años, y ese diferencial incluye prima cambiaria y de liquidez además del riesgo de impago. Como después convertimos el costo de capital a pesos con el diferencial de inflación, parte de la prima cambiaria se cuenta dos veces. Damodaran usa el spread de impago (CDS a 10 años de 1.66%) por la volatilidad relativa acciones/bonos. *Sugerencia:* basar el riesgo país en un spread de impago (CDS o spread corporativo EM de 1.72 pp) por la volatilidad relativa.
6. **Costo de capital de México (16.15% contra 13.26%).** Es consecuencia directa del punto 5, más la prima de mercado de 5% contra 4.2% implícita.
7. **Crecimiento terminal de México (4.32% contra 5.50%).** Combina un crecimiento de tendencia de 1.18% (CAGR de 10 años que incluye la caída de 2020; la encuesta espera 1.8%) y una inflación esperada de 3.14% (promedio del FMI; la encuesta espera 3.7–3.8%). Las dos piezas quedan bajas. *Sugerencia:* usar la encuesta de Banxico para la inflación esperada y un crecimiento de tendencia que excluya 2020.

## En el límite

- **Tasa de la Fed (3.96% contra 4.62% en futuros).** Contra la mediana de la Fed (4.10%) estamos en rango. El mercado descuenta alzas por la inflación alta. La línea de convergencia a la neutral (3.62%) queda más baja porque no considera la brecha de inflación (como haría una regla de Taylor).
- **Tasa de Banxico con convergencia a neutral (5.73% contra 6.50%).** Misma razón: la neutral nominal de 4.95% jala hacia abajo.
- **r\* de México (1.95%).** Está dentro del rango publicado por Banxico (1.8–3.4%), solo lejos de su punto medio.
- **Inflación implícita de México a 10 años (4.50% contra 3.70% de la encuesta).** La diferencia es la prima por riesgo inflacionario que pide el mercado. El número es correcto, pero no es una expectativa pura.
- **Prima de mercado y costo de capital de EE.UU. (5.0% y 10.0% contra 4.2% y 9.0%).** Damodaran estima la prima implícita en 4.2% hoy; 5% es un supuesto conservador.
- **Inflación esperada de México en la valuación (3.14% contra 3.80%)** y **crecimiento terminal de EE.UU. (4.84% contra 4.0%)**, que usa una tendencia de 10 años (2.5%) por arriba del largo plazo de la Fed (2.0%).

## Lo que está bien calibrado

Las pendientes de la curva de EE.UU. y la inflación implícita a 10 años coinciden al centésimo con FRED. El Bono M a 10 años calculado del vector (9.36%) coincide con la OCDE (9.35%) y con la subasta (9.25%). El ajuste Nelson-Siegel-Svensson tiene un error máximo de 3 pb en EE.UU. y 14 pb en México. La probabilidad de recesión (15%) es cercana a la de la Fed de NY (12.8%). La r\* de EE.UU. (1.36%) y la neutral nominal (3.36%) quedan cerca de HLW (1.01%) y de la Fed (3.2%). PIB, desempleo, inflación de México, tasa de Banxico, peso y cobre están en rango contra la encuesta, la Fed o los futuros.

*Nada de esto es recomendación de inversión.*
