"""Phase 09: batch-process every downloaded index-spot month.

Mirrors scripts/download_index_history.py's --symbols/--start/--end
interface but drives quant.processing.pipeline.process_index_month
across the whole range.

Usage:
    uv run python scripts/process_index_history.py \\
        --symbols NIFTY,BANKNIFTY,SENSEX --start 2022-01 --end 2026-09
"""

from __future__ import annotations

import argparse
import time
from datetime import date

from quant.data.index_spot import INDEX_KEYS
from quant.processing.pipeline import process_index_month


def _parse_month(value: str) -> date:
    year, month = value.split("-")
    return date(int(year), int(month), 1)


def _month_range(start: date, end: date) -> list[tuple[int, int]]:
    out = []
    year, month = start.year, start.month
    while (year, month) <= (end.year, end.month):
        out.append((year, month))
        month += 1
        if month > 12:
            month = 1
            year += 1
    return out


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--symbols", default="NIFTY,BANKNIFTY,SENSEX")
    parser.add_argument("--start", required=True, help="YYYY-MM")
    parser.add_argument("--end", required=True, help="YYYY-MM")
    parser.add_argument("--raw-root", default="data/raw/index")
    parser.add_argument("--processed-root", default="data/processed/index")
    parser.add_argument("--timeframes", default="1,5,15")
    args = parser.parse_args()

    symbols = [s.strip().upper() for s in args.symbols.split(",") if s.strip()]
    for s in symbols:
        if s not in INDEX_KEYS:
            raise SystemExit(f"unknown symbol {s!r}; known: {list(INDEX_KEYS)}")
    timeframes = tuple(int(x) for x in args.timeframes.split(","))
    months = _month_range(_parse_month(args.start), _parse_month(args.end))

    t0 = time.time()
    for symbol in symbols:
        ok, failed = 0, []
        for year, month in months:
            try:
                process_index_month(
                    symbol=symbol,
                    year=year,
                    month=month,
                    raw_root=args.raw_root,
                    processed_root=args.processed_root,
                    timeframes=timeframes,
                )
                ok += 1
            except FileNotFoundError:
                pass  # month not downloaded -- skip silently, not an error
            except Exception as exc:  # noqa: BLE001 -- report and keep going
                failed.append((year, month, str(exc)))
        print(f"[{symbol}] processed={ok} failed={len(failed)}")
        for year, month, msg in failed:
            print(f"  {symbol} {year:04d}-{month:02d}: {msg}")

    print(f"elapsed: {time.time() - t0:.1f}s")


if __name__ == "__main__":
    main()
