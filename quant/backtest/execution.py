"""Execution model.

Phase 05: next-candle-open execution, position sizing via lots, slippage
applied to execution prices. Pure price math; no market state here.
"""

from __future__ import annotations

from dataclasses import dataclass, field

from quant.backtest.costs import SlippageConfig, slippage_ticks


@dataclass(frozen=True)
class ExecutionConfig:
    """How trades are sized and filled."""

    initial_capital: float = 1_000_000.0
    position_size: int = 1  # lots
    lot_size: int = 50  # NIFTY futures
    slippage: SlippageConfig = field(default_factory=SlippageConfig)

    @property
    def quantity(self) -> int:
        return self.position_size * self.lot_size


def adjusted_price(
    price: float,
    side: str,  # "buy" | "sell"
    slippage: SlippageConfig,
    tick_size: float | None = None,
) -> float:
    """Execution price after adverse slippage.

    Buys slip up, sells slip down by ticks x tick_size.
    """
    ticks = slippage_ticks(slippage, side)
    if ticks == 0:
        return price
    step = tick_size or slippage.tick_size
    direction = 1.0 if side == "buy" else -1.0
    return price + direction * ticks * step
