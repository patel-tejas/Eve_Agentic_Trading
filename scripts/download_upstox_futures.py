"""Download 1-minute and daily candles for every LIVE NIFTY futures contract.

Upstox v3 serves an active contract from its listing date (expired ones
need the paid Upstox Plus endpoint), so this captures everything that is
still obtainable for free: on 2026-09-28 that is the Sep, Oct and Nov 2026
contracts, the Sep contract reaching back to 2026-07-01.

1-minute requests are chunked by calendar month (the v3 span cap for 1-15
minute intervals is ~1 month). Bars after 15:29 are post-close session
prints and are dropped at feature-build time, not here, so the raw file
stays a faithful copy of what the API returned.
"""

from __future__ import annotations

import re
import time
from datetime import date, timedelta
from pathlib import Path

import polars as pl

from quant.data.upstox import UpstoxClient

OUT = Path("data/raw/futures/NIFTY/upstox_v3")
FIRST = date(2026, 6, 1)
LAST = date(2026, 9, 28)


def _month_chunks(lo: date, hi: date) -> list[tuple[date, date]]:
    out, d = [], date(lo.year, lo.month, 1)
    while d <= hi:
        nxt = date(d.year + (d.month == 12), d.month % 12 + 1, 1)
        out.append((max(d, lo), min(nxt - timedelta(days=1), hi)))
        d = nxt
    return out


def main() -> int:
    c = UpstoxClient(require_auth=False)
    master = c._master_to_frame(c.fetch_instrument_master("NSE"))
    live = master.filter(
        (pl.col("segment") == "NSE_FO")
        & (pl.col("instrument_type") == "FUT")
        & (pl.col("underlying_symbol") == "NIFTY")
    ).sort("expiry")
    for row in live.to_dicts():
        key, sym = row["instrument_key"], row["trading_symbol"]
        dest = OUT / re.sub(r"[^A-Za-z0-9]+", "_", sym).strip("_")
        dest.mkdir(parents=True, exist_ok=True)
        daily = c.get_historical_candles_v3(
            key, unit="days", interval=1, from_date=FIRST, to_date=LAST
        )
        frames = []
        for lo, hi in _month_chunks(FIRST, LAST):
            df = c.get_historical_candles_v3(
                key, unit="minutes", interval=1, from_date=lo, to_date=hi
            )
            if len(df):
                frames.append(df)
            time.sleep(0.4)
        minute = (
            pl.concat(frames).unique(subset=["timestamp"]).sort("timestamp")
            if frames
            else pl.DataFrame()
        )
        meta = pl.DataFrame(
            [
                {
                    **{
                        k: row.get(k)
                        for k in ("instrument_key", "trading_symbol", "expiry", "lot_size")
                    },
                    "tick_size_paise": row.get("tick_size"),
                }
            ]
        )
        daily.write_parquet(dest / "daily.parquet")
        if len(minute):
            minute.write_parquet(dest / "candles_1m.parquet")
        meta.write_parquet(dest / "contract.parquet")
        rng = (
            f"{minute['timestamp'].min()} .. {minute['timestamp'].max()}" if len(minute) else "none"
        )
        print(f"{sym}: daily {len(daily)}, 1m {len(minute)} ({rng})", flush=True)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
