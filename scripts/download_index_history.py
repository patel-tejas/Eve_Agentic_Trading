"""Phase 09: backfill index-spot 1m history for NIFTY/BANKNIFTY/SENSEX.

Resumable, idempotent, unauthenticated (verified live against the Upstox
v3 historical-candle endpoint). One request per calendar month (the
API's hard cap for 1-15 minute intervals).

Usage:
    uv run python scripts/download_index_history.py \\
        --symbols NIFTY,BANKNIFTY,SENSEX --start 2022-01 --end 2026-09

    uv run python scripts/download_index_history.py \\
        --symbols NIFTY --start 2022-01 --end 2022-03 --dry-run
"""

from __future__ import annotations

import argparse
import time
from datetime import date

from quant.data.index_spot import INDEX_KEYS, download_index_range, resolve_contract_specs
from quant.data.upstox import UpstoxClient


def _parse_month(value: str) -> date:
    year, month = value.split("-")
    return date(int(year), int(month), 1)


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--symbols", default="NIFTY,BANKNIFTY,SENSEX")
    parser.add_argument("--start", required=True, help="YYYY-MM")
    parser.add_argument("--end", required=True, help="YYYY-MM")
    parser.add_argument("--out-root", default="data/raw/index")
    parser.add_argument("--overwrite", action="store_true")
    parser.add_argument(
        "--dry-run",
        action="store_true",
        help="Resolve contract specs and print the month plan; download nothing.",
    )
    args = parser.parse_args()

    symbols = [s.strip().upper() for s in args.symbols.split(",") if s.strip()]
    for s in symbols:
        if s not in INDEX_KEYS:
            raise SystemExit(f"unknown symbol {s!r}; known: {list(INDEX_KEYS)}")

    start = _parse_month(args.start)
    end = _parse_month(args.end)

    client = UpstoxClient(require_auth=False)
    t0 = time.time()

    for symbol in symbols:
        specs = resolve_contract_specs(symbol, client=client)
        print(f"[{symbol}] resolved contract specs: {specs}")
        if args.dry_run:
            continue
        results = download_index_range(
            symbol, start, end, out_root=args.out_root, client=client, overwrite=args.overwrite
        )
        n_downloaded = sum(1 for r in results if not r.get("skipped"))
        n_skipped = sum(1 for r in results if r.get("skipped"))
        total_rows = sum(r.get("rows", 0) for r in results)
        print(
            f"[{symbol}] months={len(results)} downloaded={n_downloaded} "
            f"skipped={n_skipped} total_rows={total_rows}"
        )

    print(f"elapsed: {time.time() - t0:.1f}s")


if __name__ == "__main__":
    main()
