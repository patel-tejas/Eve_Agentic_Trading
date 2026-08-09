"""Transaction cost and slippage models for Indian futures.

Phase 05: brokerage, exchange charges, GST, SEBI, stamp duty, STT and
slippage. All costs are computed against turnover (price x quantity)
for each order side. GST applies on (brokerage + exchange charges).
"""

from __future__ import annotations

from dataclasses import dataclass

STT_SELL_RATE = 0.000125  # 0.0125%
EXCHANGE_RATE = 0.0000345  # 0.00345%
SEBI_RATE = 0.000001  # 0.0001%
STAMP_RATE = 0.00003  # 0.003% (varies by state)
GST_RATE = 0.18  # 18% on brokerage + exchange charges


@dataclass(frozen=True)
class CostConfig:
    """Indian futures cost model parameters (map to Dhan/Zerodha style fees)."""

    brokerage_flat: float = 20.0  # per order (per side), INR
    stt_rate: float = STT_SELL_RATE  # sell side only
    exchange_rate: float = EXCHANGE_RATE
    sebi_rate: float = SEBI_RATE
    stamp_rate: float = STAMP_RATE
    stamp_side: str = "buy"  # "buy" | "sell" | "both" | "none"
    gst_rate: float = GST_RATE


@dataclass(frozen=True)
class SlippageConfig:
    """Slippage applied on top of the nominal execution price."""

    mode: str = "ideal"  # "ideal" | "normal" | "stress" | "ticks"
    entry_ticks: int = 0
    exit_ticks: int = 0
    tick_size: float = 0.05  # NIFTY futures tick


def slippage_ticks(config: SlippageConfig, side: str) -> int:
    """Ticks of adverse slippage for an order side ("buy"/"sell")."""
    base = config.entry_ticks if side == "buy" else config.exit_ticks
    if config.mode == "ideal" and base == 0:
        return 0
    if config.mode == "normal" and base == 0:
        # NIFTY futures: ~1 tick typical
        return 1
    if config.mode == "stress":
        return max(base, 3)
    return base  # "ticks" or explicit


def cost_of_order(
    price: float,
    quantity: int,
    side: str,
    config: CostConfig,
) -> float:
    """Total cost for one order leg in INR (excluding slippage)."""
    turnover = price * quantity
    costs = 0.0

    # Brokerage: flat per order
    costs += config.brokerage_flat

    # STT: sell side only
    if side == "sell":
        costs += turnover * config.stt_rate

    # Exchange transaction charge
    costs += turnover * config.exchange_rate

    # SEBI turnover fee
    costs += turnover * config.sebi_rate

    # Stamp duty (buy side by default; state-dependent)
    if config.stamp_side in ("both", side):
        costs += turnover * config.stamp_rate

    # GST on brokerage + exchange charges
    costs += (config.brokerage_flat + turnover * config.exchange_rate) * config.gst_rate

    return costs


def round_trip_costs(
    entry_price: float,
    exit_price: float,
    quantity: int,
    direction: str,  # "LONG" | "SHORT"
    config: CostConfig,
) -> float:
    """Total costs for an entry+exit round trip (both legs).

    LONG:  entry leg is a buy, exit leg is a sell (STT applies on exit).
    SHORT: entry leg is a sell, exit leg is a buy (STT applies on entry).
    """
    entry_side = "buy" if direction == "LONG" else "sell"
    exit_side = "sell" if direction == "LONG" else "buy"
    return cost_of_order(entry_price, quantity, entry_side, config) + cost_of_order(
        exit_price, quantity, exit_side, config
    )
