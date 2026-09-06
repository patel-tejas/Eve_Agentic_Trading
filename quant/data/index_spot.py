"""Multi-instrument index spot history (NIFTY / BANKNIFTY / SENSEX).

Phase 09: the repo has 31 trading days of NIFTY futures. Verified live
against the API: Upstox v3 historical-candle serves 1-minute INDEX SPOT
candles back to January 2022, UNAUTHENTICATED, for:

    NSE_INDEX|Nifty 50, NSE_INDEX|Nifty Bank, BSE_INDEX|SENSEX

That is ~1,150 trading days x 3 instruments instead of 23 x 1. Index
candles carry volume=0 (no traded volume on an index), so
volume-dependent strategies must stay on the futures data.

This module downloads and normalizes that history, one calendar month
per request (the v3 API's hard cap for 1-15 minute intervals). Contract
specs (lot_size, tick_size) are RESOLVED FROM THE LIVE INSTRUMENT MASTER,
never hardcoded -- the same mistake that produced the wrong lot_size=50
default is exactly what this guards against for BANKNIFTY/SENSEX.
"""

from __future__ import annotations

import json
import time as _time
from datetime import date, timedelta
from pathlib import Path
from typing import Any

import polars as pl

from quant.data.upstox import UpstoxClient

INDEX_KEYS: dict[str, str] = {
    "NIFTY": "NSE_INDEX|Nifty 50",
    "BANKNIFTY": "NSE_INDEX|Nifty Bank",
    "SENSEX": "BSE_INDEX|SENSEX",
}

# Which exchange's instrument master to query, and the underlying/segment
# filters used to resolve each symbol's derivative contract specs (lot
# size, tick size) -- these are never trusted as literals; see
# resolve_contract_specs().
_MASTER_LOOKUP: dict[str, dict[str, str]] = {
    "NIFTY": {"exchange": "NSE", "segment": "NSE_FO", "underlying": "NIFTY"},
    "BANKNIFTY": {"exchange": "NSE", "segment": "NSE_FO", "underlying": "BANKNIFTY"},
    "SENSEX": {"exchange": "BSE", "segment": "BSE_FO", "underlying": "SENSEX"},
}

REQUEST_PACING_SECONDS = 0.4


def resolve_contract_specs(symbol: str, *, client: UpstoxClient | None = None) -> dict[str, Any]:
    """Resolve (lot_size, tick_size) from the LIVE instrument master.

    Returns raw master units -- ``tick_size`` may be in paise, matching the
    convention already handled by ``quant.backtest.market.MarketContext``.
    Raises if no matching derivative contract is found; callers must not
    fall back to a guessed literal.
    """
    if symbol not in _MASTER_LOOKUP:
        raise ValueError(f"unknown index symbol {symbol!r}; known: {list(INDEX_KEYS)}")
    lookup = _MASTER_LOOKUP[symbol]
    upstox = client or UpstoxClient(require_auth=False)
    instruments = upstox.fetch_instrument_master(lookup["exchange"])
    master = pl.DataFrame(instruments)
    master = master.rename({str(c): str(c).lower() for c in master.columns})

    candidates = master
    if "segment" in candidates.columns:
        candidates = candidates.filter(pl.col("segment") == lookup["segment"])
    if "instrument_type" in candidates.columns:
        candidates = candidates.filter(
            pl.col("instrument_type").str.to_uppercase().is_in(["FUT", "FUTIDX"])
        )
    if "underlying_symbol" in candidates.columns:
        candidates = candidates.filter(
            pl.col("underlying_symbol").str.to_uppercase() == lookup["underlying"]
        )
    if candidates.is_empty():
        raise RuntimeError(
            f"no {lookup['segment']} futures contract found for {symbol!r} "
            f"in the {lookup['exchange']} instrument master; cannot resolve "
            "lot_size/tick_size without guessing"
        )
    row = candidates.head(1).to_dicts()[0]
    return {
        "lot_size": int(row["lot_size"]),
        "tick_size": float(row["tick_size"]),
        "source_trading_symbol": row.get("trading_symbol"),
    }


def _month_bounds(year: int, month: int) -> tuple[date, date]:
    start = date(year, month, 1)
    end = (date(year + 1, 1, 1) if month == 12 else date(year, month + 1, 1)) - timedelta(days=1)
    return start, end


def normalize_index_candles(
    candles: pl.DataFrame,
    *,
    symbol: str,
    lot_size: int,
    tick_size: float,
) -> pl.DataFrame:
    """Attach index-spot metadata columns to raw candles.

    ``volume`` and ``open_interest`` are forced to 0 (index spot has
    neither); ``price_source`` marks every row as a proxy, never
    tradeable, so nothing downstream can silently mistake it for a real
    fill.
    """
    return candles.with_columns(
        pl.lit(symbol, dtype=pl.Utf8).alias("instrument"),
        pl.lit("index_spot_proxy", dtype=pl.Utf8).alias("price_source"),
        pl.lit(0, dtype=pl.Int64).alias("volume"),
        pl.lit(0, dtype=pl.Int64).alias("open_interest"),
        pl.lit(lot_size, dtype=pl.Int64).alias("lot_size"),
        pl.lit(tick_size, dtype=pl.Float64).alias("tick_size"),
    ).select(
        "timestamp",
        "instrument",
        "price_source",
        "open",
        "high",
        "low",
        "close",
        "volume",
        "open_interest",
        "lot_size",
        "tick_size",
    )


def download_index_month(
    symbol: str,
    year: int,
    month: int,
    *,
    out_root: str | Path = "data/raw/index",
    client: UpstoxClient | None = None,
    contract_specs: dict[str, Any] | None = None,
    overwrite: bool = False,
) -> dict[str, object]:
    """Download and save one calendar month of index-spot 1m candles.

    Resumable by construction: skips (returns ``skipped: True``) when the
    parquet already exists AND its metadata records ``rows > 0`` AND
    ``overwrite`` is False -- this is the direct fix for the three 0-row
    placeholder files that a naive "file exists" check would have missed.

    Raises rather than writing an empty parquet if the API returns zero
    candles for a month that should have NSE/BSE trading days.
    """
    if symbol not in INDEX_KEYS:
        raise ValueError(f"unknown index symbol {symbol!r}; known: {list(INDEX_KEYS)}")

    out_root = Path(out_root)
    month_dir = out_root / symbol / f"{year:04d}-{month:02d}"
    parquet_path = month_dir / "candles_1m.parquet"
    metadata_path = month_dir / "download_metadata.json"

    if not overwrite and parquet_path.exists() and metadata_path.exists():
        try:
            existing = json.loads(metadata_path.read_text(encoding="utf-8"))
            if existing.get("rows", 0) > 0:
                return {"skipped": True, "parquet_path": parquet_path, "rows": existing["rows"]}
        except (json.JSONDecodeError, OSError):
            pass  # fall through and re-download

    upstox = client or UpstoxClient(require_auth=False)
    specs = contract_specs or resolve_contract_specs(symbol, client=upstox)

    start, end = _month_bounds(year, month)
    candles = upstox.get_historical_candles_v3(
        INDEX_KEYS[symbol], unit="minutes", interval=1, from_date=start, to_date=end
    )
    frame = normalize_index_candles(
        candles, symbol=symbol, lot_size=specs["lot_size"], tick_size=specs["tick_size"]
    ).sort("timestamp")

    if frame.height == 0:
        raise RuntimeError(
            f"Upstox returned 0 candles for {symbol} {year}-{month:02d}. "
            "Refusing to write an empty parquet -- this was exactly how the "
            "three 2026-{01,02,03} placeholder files happened."
        )

    month_dir.mkdir(parents=True, exist_ok=True)
    frame.write_parquet(parquet_path)
    metadata = {
        "symbol": symbol,
        "instrument_key": INDEX_KEYS[symbol],
        "year": year,
        "month": month,
        "rows": frame.height,
        "lot_size": specs["lot_size"],
        "tick_size": specs["tick_size"],
        "price_source": "index_spot_proxy",
        "endpoint": "v3 historical-candle (unauthenticated, index spot)",
    }
    metadata_path.write_text(json.dumps(metadata, indent=2), encoding="utf-8")

    return {
        "skipped": False,
        "parquet_path": parquet_path,
        "metadata_path": metadata_path,
        "rows": frame.height,
    }


def download_index_range(
    symbol: str,
    start: date,
    end: date,
    *,
    out_root: str | Path = "data/raw/index",
    client: UpstoxClient | None = None,
    overwrite: bool = False,
    pacing_seconds: float = REQUEST_PACING_SECONDS,
) -> list[dict[str, object]]:
    """Download every calendar month in ``[start, end]`` for one symbol.

    Resolves contract specs ONCE (not once per month) and reuses one
    client for the whole range. Paces requests so a multi-year backfill
    does not hammer the API.
    """
    upstox = client or UpstoxClient(require_auth=False)
    specs = resolve_contract_specs(symbol, client=upstox)

    results: list[dict[str, object]] = []
    year, month = start.year, start.month
    while (year, month) <= (end.year, end.month):
        result = download_index_month(
            symbol,
            year,
            month,
            out_root=out_root,
            client=upstox,
            contract_specs=specs,
            overwrite=overwrite,
        )
        result["year"] = year
        result["month"] = month
        results.append(result)
        if not result.get("skipped"):
            _time.sleep(pacing_seconds)
        month += 1
        if month > 12:
            month = 1
            year += 1
    return results
