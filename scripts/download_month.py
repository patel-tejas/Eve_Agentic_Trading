"""Phase 01: download a research month of NIFTY futures 1m candles (Upstox)."""

from __future__ import annotations

import argparse
import time

from quant.data.download import download_nifty_futures_upstox


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--year", type=int, required=True)
    parser.add_argument("--month", type=int, required=True)
    parser.add_argument("--out-dir", default="data/raw/futures/NIFTY")
    args = parser.parse_args()

    t0 = time.time()
    result = download_nifty_futures_upstox(year=args.year, month=args.month, out_dir=args.out_dir)
    print(f"candles: {result['candles']}")
    print(f"contract: {result['contract'].trading_symbol} ({result['contract'].expiry})")
    print(f"parquet: {result['parquet_path']}")
    print(f"metadata: {result['metadata_path']}")
    print(f"elapsed: {time.time() - t0:.1f}s")


if __name__ == "__main__":
    main()
