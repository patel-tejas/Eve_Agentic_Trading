"""Download deep DAILY index-spot history (Upstox v3, unauthenticated).

The 1-minute archive on disk only reaches 2022-01, which is too short to
warm up a 200/252-day trend filter and leaves no bear market in the
training window. Daily candles reach back to 2005, which covers 2008,
2011, 2015-16, 2018 and 2020 -- the drawdowns a trend/vol overlay exists
to avoid.

The v3 endpoint rejects ranges longer than ~6 years ("UDAPI1148 Invalid
date range"), so requests are chunked and concatenated.
"""

from __future__ import annotations

import sys
from datetime import date
from pathlib import Path

import polars as pl

from quant.data.index_spot import INDEX_KEYS as _SPOT_KEYS
from quant.data.upstox import UpstoxClient

# India VIX is served by the same unauthenticated endpoint (daily from
# 2009-03-02); the empty pre-2009 chunks are skipped below.
INDEX_KEYS = {**_SPOT_KEYS, "INDIAVIX": "NSE_INDEX|India VIX"}
OUT_ROOT = Path("data/processed/index_daily")
START = date(2005, 1, 1)
END = date(2026, 9, 25)
CHUNK_YEARS = 5


def _chunks(start: date, end: date, years: int) -> list[tuple[date, date]]:
    out, lo = [], start
    while lo <= end:
        hi = min(date(lo.year + years, lo.month, lo.day), end)
        out.append((lo, hi))
        if hi >= end:
            break
        lo = date(hi.year, hi.month, hi.day)
    return out


def download(symbol: str, client: UpstoxClient) -> pl.DataFrame:
    frames = []
    for lo, hi in _chunks(START, END, CHUNK_YEARS):
        df = client.get_historical_candles_v3(
            INDEX_KEYS[symbol], unit="days", interval=1, from_date=lo, to_date=hi
        )
        if len(df):
            frames.append(df)
        print(f"  {symbol} {lo}..{hi}: {len(df):5d} rows", flush=True)
    if not frames:
        raise RuntimeError(f"no daily data returned for {symbol}")
    out = (
        pl.concat(frames)
        .unique(subset=["timestamp"])
        .sort("timestamp")
        .with_columns(pl.col("timestamp").dt.date().alias("d"))
    )
    return out


def update_recent(days_back: int = 40, end: date | None = None) -> None:
    """Merge the last ``days_back`` calendar days into each daily.parquet.

    Used by the forward paper-trading log: existing rows are kept unless
    the fresh pull returns the same date (then the fresh value wins).
    """
    from datetime import timedelta

    end = end or date.today()
    lo = end - timedelta(days=days_back)
    client = UpstoxClient(require_auth=False)
    for symbol, key in INDEX_KEYS.items():
        fresh = client.get_historical_candles_v3(
            key, unit="days", interval=1, from_date=lo, to_date=end
        )
        if not len(fresh):
            continue
        fresh = fresh.with_columns(pl.col("timestamp").dt.date().alias("d"))
        dest = OUT_ROOT / symbol / "daily.parquet"
        old = pl.read_parquet(dest)
        merged = pl.concat(
            [old.filter(~pl.col("d").is_in(fresh["d"].implode())), fresh.select(old.columns)]
        ).sort("d")
        merged.write_parquet(dest)
        print(f"  {symbol}: {len(merged)} sessions through {merged['d'].max()}", flush=True)


def main() -> int:
    if "--recent" in sys.argv:
        update_recent()
        return 0
    client = UpstoxClient(require_auth=False)
    for symbol in INDEX_KEYS:
        print(f"=== {symbol} ===", flush=True)
        df = download(symbol, client)
        dest = OUT_ROOT / symbol
        dest.mkdir(parents=True, exist_ok=True)
        df.write_parquet(dest / "daily.parquet")
        print(f"  -> {len(df)} sessions {df['d'].min()} .. {df['d'].max()}\n", flush=True)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
