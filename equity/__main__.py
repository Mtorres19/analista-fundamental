"""python -m equity valuar GOOGL [--date YYYY-MM-DD] [--growth 0.12] [--margin 0.30] [--out reportes/empresas]
python -m equity lista            # values every company in watchlist.toml
"""

from __future__ import annotations

import argparse
import sys
import tomllib
from datetime import date
from pathlib import Path

from equity import data
from equity.dcf import value
from equity.report import render
from macro.report import build_report
from macro.sources import DataError

WATCHLIST = Path(__file__).resolve().parent.parent / "watchlist.toml"
BENCHMARK = {"US": "^GSPC", "MX": "^MXX"}


def main() -> None:
    p = argparse.ArgumentParser(prog="equity", description="Valuación de empresas con los supuestos macro.")
    cmd = p.add_subparsers(dest="command", required=True)
    one = cmd.add_parser("valuar", help="DCF, comparables y reporte de una emisora")
    one.add_argument("ticker")
    for c in (one, cmd.add_parser("lista", help="valúa toda la lista de seguimiento")):
        c.add_argument("--date", default=date.today().isoformat())
        c.add_argument("--out", default="reportes/empresas", help="carpeta para el .md y el .json")
    one.add_argument("--growth", type=float, help="crecimiento de ingresos años 1-5, decimal")
    one.add_argument("--margin", type=float, help="margen operativo, decimal")
    args = p.parse_args()

    watch = tomllib.loads(WATCHLIST.read_text())
    tickers = [args.ticker.upper()] if args.command == "valuar" else list(watch)
    overrides = {k: v for k in ("growth", "margin") if (v := getattr(args, k, None)) is not None}
    try:
        macro = build_report(args.date)
    except DataError as exc:
        sys.exit(f"error de datos macro: {exc}")
    failed = 0
    for t in tickers:
        try:
            _one(t, watch.get(t, {}), macro, args.date, Path(args.out), overrides)
        except (DataError, ValueError) as exc:
            failed += 1
            print(f"{t}: {exc}", file=sys.stderr)
    sys.exit(1 if failed else 0)


def _one(ticker: str, cfg: dict, macro, as_of: str, out: Path, overrides: dict) -> None:
    market = cfg.get("mercado", "MX" if ticker.endswith(".MX") else "US")
    if cfg.get("financiera"):
        raise ValueError("banco o aseguradora: el DCF de flujo libre no aplica (usar descuento de dividendos)")
    fin = data.sec_financials(ticker) if market == "US" else data.yahoo_financials(ticker)
    mkt = data.market_data(ticker, BENCHMARK[market])
    a = macro.assumptions[0 if market == "US" else 1]
    v = value(fin, mkt, a, as_of, peers=data.peers_multiples(cfg.get("comparables", [])),
              consensus=data.consensus(ticker), **{**cfg.get("supuestos", {}), **overrides})
    out.mkdir(parents=True, exist_ok=True)
    stem = out / f"{ticker.replace('.', '_')}-{as_of}"
    stem.with_suffix(".md").write_text(render(v, a))
    stem.with_suffix(".json").write_text(v.model_dump_json(indent=2))
    print(f"{ticker}: {v.verdict} · valor {v.value_per_share:,.2f} vs precio {v.inputs.price:,.2f} ({v.upside:+.1%}) → {stem}.md")


if __name__ == "__main__":
    main()
