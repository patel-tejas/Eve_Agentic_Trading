"""Multi-month candle loading (Phase 09).

Nothing in the repo can build one continuous multi-year frame today --
every existing entry point (``mcp.quant_server.server.get_historical_candles``,
``quant.research.parameter_search``, etc.) works one processed month at a
time. Research over 2022-2026 needs one continuous frame per
(symbol, timeframe); this module globs the monthly parquets, concatenates,
sorts, and de-dupes on timestamp.
"""

from __future__ import annotations

from datetime import date
from pathlib import Path

import polars as pl

AssetClass = str  # "futures" | "index"


def available_months(
    symbol: str,
    *,
    asset_class: AssetClass = "index",
    root: str | Path = "data/processed",
) -> list[str]:
    """List the ``YYYY-MM`` months with a processed dataset for this symbol."""
    base = Path(root) / asset_class / symbol
    if not base.exists():
        return []
    return sorted(p.name for p in base.iterdir() if p.is_dir())


def load_candles(
    symbol: str,
    timeframe: str,
    *,
    asset_class: AssetClass = "index",
    start: date | None = None,
    end: date | None = None,
    root: str | Path = "data/processed",
) -> pl.DataFrame:
    """Load and concatenate every processed month for one (symbol, timeframe).

    ``timeframe`` is the directory name used by ``process_month``/
    ``process_index_month`` (``"1m"``, ``"5m"``, ``"15m"``). Optionally
    filters to ``[start, end]`` (inclusive) by calendar date. Rows are
    sorted by timestamp and de-duplicated (keeping the first occurrence)
    so an overlapping re-download can never silently double-count a bar.

    Raises if no month has a parquet for this symbol/timeframe -- an
    empty frame is never returned silently, matching the rest of the
    Phase 09 data path's "fail loudly on nothing found" convention.
    """
    base = Path(root) / asset_class / symbol
    months = available_months(symbol, asset_class=asset_class, root=root)
    paths = [base / m / timeframe / "candles.parquet" for m in months]
    existing = [p for p in paths if p.exists()]
    if not existing:
        raise FileNotFoundError(
            f"no processed {timeframe} data found for {asset_class}/{symbol} under {base}"
        )

    frame = pl.concat([pl.read_parquet(p) for p in existing], how="vertical_relaxed")
    frame = frame.sort("timestamp").unique(subset=["timestamp"], keep="first").sort("timestamp")

    if start is not None:
        frame = frame.filter(pl.col("timestamp").dt.date() >= start)
    if end is not None:
        frame = frame.filter(pl.col("timestamp").dt.date() <= end)
    return frame
