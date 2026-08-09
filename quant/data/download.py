"""Phase 01: end-to-end download of NIFTY futures 1m candles to Parquet.

Pipeline (DhanHQ): authenticate -> instrument master -> resolve July contract ->
download 1m candles -> normalize -> save Parquet + contract metadata.

Pipeline (Upstox, expired contracts): expired future contract API ->
expired historical candles -> normalize -> save Parquet + contract metadata.
"""

from __future__ import annotations

import json
from datetime import date, timedelta
from pathlib import Path

import polars as pl

from quant.data.dhan import DhanClient, InstrumentType, Interval
from quant.data.instruments import FuturesContract, pick_contract, save_contract_metadata
from quant.data.upstox import UpstoxClient

CANONICAL_SCHEMA = {
    "timestamp": pl.Datetime("ms"),
    "instrument": pl.Utf8,
    "security_id": pl.Utf8,
    "exchange": pl.Utf8,
    "instrument_type": pl.Utf8,
    "expiry": pl.Date,
    "open": pl.Float64,
    "high": pl.Float64,
    "low": pl.Float64,
    "close": pl.Float64,
    "volume": pl.Int64,
    "open_interest": pl.Int64,
    "lot_size": pl.Int64,
    "tick_size": pl.Float64,
}


def normalize_candles(
    candles: pl.DataFrame,
    contract: FuturesContract,
) -> pl.DataFrame:
    """Add contract metadata columns to raw candles for the canonical dataset."""
    return candles.with_columns(
        pl.lit("NIFTY_FUT", dtype=pl.Utf8).alias("instrument"),
        pl.lit(contract.security_id, dtype=pl.Utf8).alias("security_id"),
        pl.lit(contract.exchange_segment, dtype=pl.Utf8).alias("exchange"),
        pl.lit(contract.instrument_type, dtype=pl.Utf8).alias("instrument_type"),
        pl.lit(contract.expiry.isoformat(), dtype=pl.Utf8).str.to_date().alias("expiry"),
        pl.lit(contract.lot_size, dtype=pl.Int64).alias("lot_size"),
        pl.lit(contract.tick_size, dtype=pl.Float64).alias("tick_size"),
    ).select(
        "timestamp",
        "instrument",
        "security_id",
        "exchange",
        "instrument_type",
        "expiry",
        "open",
        "high",
        "low",
        "close",
        "volume",
        "open_interest",
        "lot_size",
        "tick_size",
    )


def download_nifty_futures(
    *,
    year: int,
    month: int,
    out_dir: str | Path = "data/raw/futures/NIFTY",
    client: DhanClient | None = None,
) -> dict[str, object]:
    """Download one month of NIFTY futures 1m candles and save Parquet."""
    out_dir = Path(out_dir)
    month_dir = out_dir / f"{year:04d}-{month:02d}"
    month_dir.mkdir(parents=True, exist_ok=True)

    master = (client or DhanClient()).fetch_instrument_master("NSE_FNO")
    contract = pick_contract(master, date(year, month, 1))
    if contract is None:
        raise RuntimeError(f"No NIFTY futures contract found for {year}-{month:02d}")

    candles = (client or DhanClient()).get_intraday_candles(
        contract.security_id,
        exchange_segment="NSE_FNO",
        instrument_type=InstrumentType.FUTIDX,
        interval=Interval.ONE_MINUTE,
        from_date=date(year, month, 1),
        to_date=date(year, month, 28 if month == 2 else 31),
        open_interest=True,
    )
    frame = normalize_candles(candles, contract).sort("timestamp")

    parquet_path = month_dir / "candles_1m.parquet"
    frame.write_parquet(parquet_path)
    metadata_path = month_dir / "contract_metadata.json"
    save_contract_metadata(contract, metadata_path)

    return {
        "contract": contract,
        "candles": len(frame),
        "timeframe": "1m",
        "parquet_path": parquet_path,
        "metadata_path": metadata_path,
    }


def upstox_contract_to_futures(contract: dict) -> FuturesContract:
    """Map an Upstox expired-futures record onto our FuturesContract dataclass."""
    return FuturesContract(
        security_id=str(contract["instrument_key"]),
        trading_symbol=str(contract["trading_symbol"]),
        underlying_symbol=str(contract["underlying_symbol"]),
        expiry=date.fromisoformat(str(contract["expiry"])),
        lot_size=int(contract["lot_size"]),
        tick_size=float(contract["tick_size"]),
        exchange_segment=str(contract.get("segment", "NSE_FO")),
        instrument_type=str(contract.get("instrument_type", "FUT")),
    )


def download_nifty_futures_upstox(
    *,
    year: int,
    month: int,
    out_dir: str | Path = "data/raw/futures/NIFTY",
    client: UpstoxClient | None = None,
) -> dict[str, object]:
    """Download one month of NIFTY futures 1m candles from Upstox (active contract).

    The BOD master only lists currently-active contracts, so the month is
    harvested from the contract with the earliest expiry on/after the last
    day of the harvest month (the contract that traded through that month).
    E.g. July 2026 data comes from the Aug 2026 contract (listed ~Jul 1).

    Requires the 1-minute history window to remain reachable: V3 serves
    1-minute candles for the ~1 month leading up to ``to_date``, so passing
    ``to_date = month end`` keeps the whole harvest month inside the window.
    """
    out_dir = Path(out_dir)
    month_dir = out_dir / f"{year:04d}-{month:02d}"
    month_dir.mkdir(parents=True, exist_ok=True)

    upstox = client or UpstoxClient()
    record = upstox.find_active_nifty_future(year, month)
    if record is None:
        raise RuntimeError(
            f"No active NIFTY futures contract covers {year}-{month:02d} in the master"
        )
    contract = upstox_contract_to_futures(record)

    if month == 12:
        month_end = date(year + 1, 1, 1) - timedelta(days=1)
    else:
        month_end = date(year, month + 1, 1) - timedelta(days=1)
    candles = upstox.get_historical_candles_v3(
        record["instrument_key"],
        unit="minutes",
        interval=1,
        from_date=date(year, month, 1),
        to_date=month_end,
    )
    frame = normalize_candles(candles, contract).sort("timestamp")

    parquet_path = month_dir / "candles_1m.parquet"
    frame.write_parquet(parquet_path)
    metadata_path = month_dir / "contract_metadata.json"
    research = {
        "harvest_year": year,
        "harvest_month": month,
        "provider": "upstox",
        "endpoint": "v3 historical-candle (active contract)",
        "note": "harvested from the contract trading through the month: early "
        "listing period of the pseudo-near contract maps to the prior month",
    }
    metadata_path.write_text(
        json.dumps({**contract.to_dict(), "research": research}, indent=2),
        encoding="utf-8",
    )

    return {
        "contract": contract,
        "candles": len(frame),
        "timeframe": "1m",
        "parquet_path": parquet_path,
        "metadata_path": metadata_path,
    }
