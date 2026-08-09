"""Instrument discovery and futures contract resolution.

Phase 01: resolve NIFTY Futures contracts for a given month,
tracking expiry / lot size / tick size metadata.
"""

from __future__ import annotations

import json
from dataclasses import asdict, dataclass
from datetime import date
from pathlib import Path
from typing import Any

import polars as pl


@dataclass(frozen=True)
class FuturesContract:
    """A single futures contract resolved from the instrument master."""

    security_id: str
    trading_symbol: str
    underlying_symbol: str
    expiry: date
    lot_size: int
    tick_size: float
    exchange_segment: str = "NSE_FNO"
    instrument_type: str = "FUTIDX"

    def __post_init__(self) -> None:
        if isinstance(self.expiry, str):
            object.__setattr__(self, "expiry", date.fromisoformat(self.expiry))

    def to_dict(self) -> dict[str, Any]:
        data = asdict(self)
        data["expiry"] = self.expiry.isoformat()
        return data


def normalize_master(master: pl.DataFrame) -> pl.DataFrame:
    """Lowercase column names and parse the expiry column."""
    df = master.rename({str(c): str(c).lower() for c in master.columns})
    if "sm_expiry_date" in df.columns:
        df = df.with_columns(
            pl.col("sm_expiry_date")
            .str.strip_chars()
            .str.to_date("%Y-%m-%d", strict=False)
            .alias("expiry")
        )
    return df


def filter_nifty_futures(master: pl.DataFrame) -> pl.DataFrame:
    """Keep only NIFTY index futures rows from a (normalized) master."""
    df = master
    for col in ("underlying_symbol", "instrument_type"):
        if col in df.columns:
            df = df.filter(pl.col(col).str.to_uppercase().is_in(("NIFTY", "FUTIDX")))
        else:
            df = df.filter(pl.lit(True))
    return df


def pick_contract(
    master: pl.DataFrame,
    expiry: str | date,
    *,
    exchange_segment: str = "NSE_FNO",
) -> FuturesContract | None:
    """Pick the NIFTY futures contract expiring in the given month.

    Returns None if no contract matches.
    """
    if isinstance(expiry, str):
        expiry = date.fromisoformat(expiry)

    df = normalize_master(master)
    if "expiry" not in df.columns:
        raise ValueError("Instrument master is missing expiry info; cannot resolve contract")
    if "instrument_type" in df.columns:
        df = df.filter(pl.col("instrument_type").str.to_uppercase().is_in(["FUTIDX", "FUT"]))
    else:
        df = df.filter(pl.lit(True))
    if "underlying_symbol" in df.columns:
        df = df.filter(pl.col("underlying_symbol").str.to_uppercase().eq("NIFTY"))
    else:
        df = df.filter(pl.lit(True))

    df = df.filter(
        pl.col("expiry").dt.year() == expiry.year,
        pl.col("expiry").dt.month() == expiry.month,
    )
    if df.is_empty():
        return None

    row = df.sort("expiry").head(1)
    return FuturesContract(
        security_id=str(row["security_id"][0]),
        trading_symbol=str(row["trading_symbol"][0]),
        underlying_symbol=str(row["underlying_symbol"][0]),
        expiry=row["expiry"][0],
        lot_size=int(row["lot_size"][0]),
        tick_size=float(row["tick_size"][0]),
        exchange_segment=exchange_segment,
    )


def save_contract_metadata(contract: FuturesContract, path: Path | str) -> None:
    """Persist contract metadata as JSON."""
    Path(path).write_text(json.dumps(contract.to_dict(), indent=2), encoding="utf-8")
