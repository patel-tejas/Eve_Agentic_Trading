"""Contract-aware market context: lot size and tick size, unit-safe.

Phase 09: ``BacktestConfig.lot_size`` (50) and ``SlippageConfig.tick_size``
(0.05) are wrong for NIFTY futures -- the real contract metadata on disk
says ``lot_size: 65`` and ``tick_size: 10.0``.

That ``10.0`` is PAISE (Rs 0.10), not rupees. This module is the single
conversion boundary: paise from the instrument master/contract metadata
comes in, rupees go out, and a guard makes the un-converted mistake
impossible to ship silently -- an un-caught paise value here would inflate
slippage ~200x (Rs 10/tick x 65 = Rs 650/leg instead of Rs 6.50) and read
as "the strategy is terrible" rather than "the units are wrong".

``lot_size`` is a COUNT and is never scaled by anything in this module.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Literal

import polars as pl

PriceSource = Literal["futures", "index_spot_proxy"]

# Plausible range for an INR tick size on Indian index/futures contracts.
# Anything outside this is far more likely to be a raw paise value that
# was never divided by 100.
_MIN_TICK_RUPEES = 0.01
_MAX_TICK_RUPEES = 1.0


@dataclass(frozen=True)
class MarketContext:
    """Resolved, unit-safe contract facts for one instrument."""

    symbol: str
    price_source: PriceSource
    lot_size: int  # a COUNT -- never scaled
    tick_size_rupees: float  # INR -- already converted from paise if needed

    def __post_init__(self) -> None:
        if not _MIN_TICK_RUPEES <= self.tick_size_rupees <= _MAX_TICK_RUPEES:
            raise ValueError(
                f"tick_size_rupees={self.tick_size_rupees!r} is outside the plausible "
                f"range [{_MIN_TICK_RUPEES}, {_MAX_TICK_RUPEES}] INR. "
                "Did you pass a raw paise value (e.g. 10.0) straight from the "
                "instrument master or contract_metadata.json without dividing by 100?"
            )
        if self.lot_size <= 0:
            raise ValueError(f"lot_size must be a positive count, got {self.lot_size!r}")


def market_context_from_candles(
    frame: pl.DataFrame,
    *,
    symbol: str,
    price_source: PriceSource = "futures",
    tick_size_col: str = "tick_size",
    lot_size_col: str = "lot_size",
) -> MarketContext:
    """Resolve a ``MarketContext`` from a processed candle frame's own columns.

    The processed parquets already carry ``lot_size`` and ``tick_size``
    columns (populated from ``contract_metadata.json`` at download time);
    this reads them rather than trusting a hardcoded default. The stored
    ``tick_size`` is in paise (matching Upstox's contract metadata
    convention) and is divided by 100 here -- the one conversion boundary.
    """
    if lot_size_col not in frame.columns or tick_size_col not in frame.columns:
        raise ValueError(
            f"frame is missing {lot_size_col!r}/{tick_size_col!r}; "
            "cannot resolve a MarketContext from it"
        )
    lot_values = frame[lot_size_col].unique().drop_nulls().to_list()
    tick_values = frame[tick_size_col].unique().drop_nulls().to_list()
    if len(lot_values) != 1 or len(tick_values) != 1:
        raise ValueError(
            f"frame carries multiple distinct lot_size/tick_size values "
            f"({lot_values!r} / {tick_values!r}); cannot resolve one MarketContext"
        )
    return MarketContext(
        symbol=symbol,
        price_source=price_source,
        lot_size=int(lot_values[0]),
        tick_size_rupees=float(tick_values[0]) / 100.0,
    )
