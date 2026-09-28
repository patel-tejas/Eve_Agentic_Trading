"""Date-aware Indian index-futures friction (NIFTY), as used by C2026-09-REALDATA.

``costs.CostConfig`` holds one set of rates. Over 2016-2026 the rates
changed four times, and the last change -- STT on futures sales from
0.02% to 0.05% on 2026-04-01 -- roughly doubled a round trip, so a
backtest spanning those dates needs the schedule, not a constant.

Sources (verified 2026-09-28) are listed in
``plans/2026-09-28-realdata-preregistration.md`` section 9.
"""

from __future__ import annotations

from datetime import date

from quant.backtest.costs import CostConfig

# (effective_from, rate) -- each rate applies from its date until the next.
STT_SELL_SCHEDULE: tuple[tuple[date, float], ...] = (
    (date(2000, 1, 1), 0.000100),  # 0.01%
    (date(2023, 4, 1), 0.000125),  # 0.0125%, Finance Act 2023
    (date(2024, 10, 1), 0.000200),  # 0.02%, Budget 2024
    (date(2026, 4, 1), 0.000500),  # 0.05%, Budget 2026
)
EXCHANGE_SCHEDULE: tuple[tuple[date, float], ...] = (
    (date(2000, 1, 1), 0.0000190),  # conservative; 0.00183% just before the change
    (date(2024, 10, 1), 0.0000173),
)
STAMP_BUY = 0.00002  # 0.002%, uniform since 2020-07-01
SEBI = 0.000001  # Rs 10 / crore
GST = 0.18
BROKERAGE_PER_ORDER = 20.0
NOTIONAL_PER_ORDER = 1_500_000.0  # ~1 NIFTY lot; only scales the flat brokerage
TICK_RUPEES = 0.10


def _rate(schedule: tuple[tuple[date, float], ...], on: date) -> float:
    current = schedule[0][1]
    for start, rate in schedule:
        if on >= start:
            current = rate
    return current


def stt_sell_rate(on: date) -> float:
    return _rate(STT_SELL_SCHEDULE, on)


def exchange_rate(on: date) -> float:
    return _rate(EXCHANGE_SCHEDULE, on)


def leg_bps(side: str, on: date, *, price: float = 24_000.0, slippage_ticks: float = 1.0) -> float:
    """Friction of one leg in bps of traded notional."""
    exch = exchange_rate(on)
    brokerage = BROKERAGE_PER_ORDER / NOTIONAL_PER_ORDER
    total = exch + SEBI + brokerage + GST * (brokerage + exch + SEBI)
    total += stt_sell_rate(on) if side == "sell" else STAMP_BUY
    total += slippage_ticks * TICK_RUPEES / price
    return total * 1e4


def round_trip_bps(on: date, *, price: float = 24_000.0) -> float:
    return leg_bps("buy", on, price=price) + leg_bps("sell", on, price=price)


def cost_config_for(on: date) -> CostConfig:
    """A ``CostConfig`` carrying the rates in force on ``on``.

    For engine runs confined to one regime (e.g. the 2026 futures window,
    entirely after 2026-04-01). ``CostConfig`` charges GST on brokerage +
    exchange only; the SEBI-fee GST it omits is ~0.0002 bps.
    """
    return CostConfig(
        stt_rate=stt_sell_rate(on),
        exchange_rate=exchange_rate(on),
        sebi_rate=SEBI,
        stamp_rate=STAMP_BUY,
        stamp_side="buy",
        gst_rate=GST,
        brokerage_flat=BROKERAGE_PER_ORDER,
    )
