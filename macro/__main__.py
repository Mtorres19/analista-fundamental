"""python -m macro report [--date YYYY-MM-DD] [--erp 0.042] [--out report.md]
python -m macro dashboard [--date YYYY-MM-DD] [--out dashboard.html]
python -m macro check     # fetch every declared series once and say which fail
"""

from __future__ import annotations

import argparse
import sys
from datetime import date
from pathlib import Path

from macro import sources
from macro.dashboard import build_dashboard
from macro.report import build_report, render


def main() -> None:
    parser = argparse.ArgumentParser(prog="macro", description="Análisis macro propio: EE.UU., México y el mundo.")
    commands = parser.add_subparsers(dest="command", required=True)
    rep = commands.add_parser("report", help="panorama macro y supuestos de valuación")
    rep.add_argument("--date", default=date.today().isoformat(), help="fecha de corte YYYY-MM-DD (default: hoy)")
    rep.add_argument("--erp", type=float, default=None, help="prima de riesgo de mercado, decimal (default: la implícita de Damodaran)")
    rep.add_argument("--out", help="escribe el reporte Markdown aquí y el JSON junto a él")
    dash = commands.add_parser("dashboard", help="página HTML con gráficas, razones y pronósticos")
    dash.add_argument("--date", default=date.today().isoformat(), help="fecha de corte YYYY-MM-DD (default: hoy)")
    dash.add_argument("--erp", type=float, default=None, help="prima de riesgo de mercado, decimal (default: la implícita de Damodaran)")
    dash.add_argument("--out", default="reportes/dashboard.html", help="dónde escribir la página")
    commands.add_parser("check", help="prueba cada serie declarada en sources.SERIES")
    args = parser.parse_args()

    if args.command == "check":
        sys.exit(_check())
    if args.command == "dashboard":
        try:
            page = build_dashboard(args.date, erp=args.erp)
        except sources.DataError as exc:
            print(f"error de datos: {exc}", file=sys.stderr)
            sys.exit(1)
        out = Path(args.out)
        out.parent.mkdir(parents=True, exist_ok=True)
        out.write_text(page)
        print(f"dashboard escrito en {out}")
        return
    try:
        report = build_report(args.date, erp=args.erp)
    except sources.DataError as exc:
        print(f"error de datos: {exc}", file=sys.stderr)
        sys.exit(1)
    text = render(report)
    if args.out:
        out = Path(args.out)
        out.write_text(text)
        out.with_suffix(".json").write_text(report.model_dump_json(indent=2))
    print(text)


def _check() -> int:
    failed = 0
    for region, series in sources.SERIES.items():
        for name, (source, sid, _) in series.items():
            try:
                s = sources.fetch(source, sid)
                print(f"ok    {region:9} {name:22} {source}:{sid}  último {s.index[-1].date()}")
            except Exception as exc:  # report every failure, not just the first
                failed += 1
                print(f"FALLA {region:9} {name:22} {source}:{sid}  {exc}")
    for ind in sources.IMF_INDICATORS:
        try:
            years = sources.imf_weo(ind).index
            print(f"ok    IMF    {ind:15} años {years.min()}-{years.max()}")
        except Exception as exc:
            failed += 1
            print(f"FALLA IMF    {ind:15} {exc}")
    return 1 if failed else 0


if __name__ == "__main__":
    main()
