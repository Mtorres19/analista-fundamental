# Análisis fundamental

Agente que recomienda acciones con análisis fundamental, de arriba hacia abajo: primero lee la economía y de ahí salen los supuestos con los que se valúa cada empresa.

## Capa 1: panorama macro (`macro/`)

El análisis es propio. Los datos se bajan de fuentes públicas y los cálculos se hacen aquí; los pronósticos externos sirven solo para comparar.

| Bloque | Qué calcula | Fuente |
|---|---|---|
| Estados Unidos | Crecimiento vs tendencia, inflación y su dirección, tasa real, curva, regla de Sahm, spread de crédito, régimen | FRED |
| México | Lo mismo, más carry vs EE.UU., tipo de cambio real vs su promedio de 10 años | Banxico SIE, FRED |
| Mundo | Amplitud del ciclo en el G20, mediana de crecimiento, VIX, dólar, Brent, cobre | FMI, FRED |
| Comparación | Lo observado contra el pronóstico del FMI del mismo año | FMI WEO |
| Supuestos | Libre de riesgo, prima de mercado, riesgo país, inflación esperada, crecimiento terminal, costo de capital en USD y MXN | Todo lo anterior |

Cada serie se corta a la fecha de análisis menos su rezago de publicación, para que una fecha pasada solo vea datos que ya eran públicos.

## Uso

```bash
pip install -e ".[dev]"
export BANXICO_TOKEN=...   # gratis: https://www.banxico.org.mx/SieAPIRest/service/v1/token
python -m macro check                       # prueba que cada serie responda
python -m macro report                      # panorama de hoy
python -m macro dashboard                   # página con gráficas, razones y pronósticos (reportes/dashboard.html)
python -m macro report --date 2025-12-31 --erp 0.055 --out reportes/2025-12.md
pytest
```

Las series y sus IDs están en `macro/sources.py` (`SERIES`). Si `check` marca una como FALLA, ahí se cambia.
