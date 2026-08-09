"""Regime analysis (Phase 08).

Classify each trading day by realized volatility derived from the candle
data itself (no India VIX feed needed): range / day-close ratio. A day is
"high" volatility above 1.5%, "low" below 0.8%, else "mid". Trade results
are then attributed to regimes via the entry timestamp's date.
"""

from __future__ import annotations

from dataclasses import dataclass

import polars as pl

HIGH_RANGE_PCT = 0.015
LOW_RANGE_PCT = 0.008

REGIME_ORDER = ("high", "mid", "low")


def day_regime_labels(
    candles: pl.DataFrame,
    *,
    high_pct: float = HIGH_RANGE_PCT,
    low_pct: float = LOW_RANGE_PCT,
) -> pl.DataFrame:
    """Per-day (day_of, range_pct, regime) labels from candle ranges."""
    daily = (
        candles.select(
            pl.col("timestamp").dt.date().alias("day_of"),
            pl.col("high"),
            pl.col("low"),
            pl.col("close"),
        )
        .group_by("day_of")
        .agg(
            pl.col("high").max().alias("day_high"),
            pl.col("low").min().alias("day_low"),
            pl.col("close").last().alias("day_close"),
        )
        .with_columns(
            ((pl.col("day_high") - pl.col("day_low")) / pl.col("day_close")).alias(
                "range_pct"
            )
        )
        .with_columns(
            pl.when(pl.col("range_pct") > high_pct)
            .then(pl.lit("high"))
            .when(pl.col("range_pct") < low_pct)
            .then(pl.lit("low"))
            .otherwise(pl.lit("mid"))
            .alias("regime")
        )
    )
    return daily


@dataclass(frozen=True)
class RegimeSummary:
    """Per-regime aggregation of trade metrics."""

    regime: str
    days: int
    trades: int
    net_pnl: float
    profit_factor: float
    win_rate: float

    def to_dict(self) -> dict[str, object]:
        return {
            "regime": self.regime,
            "days": self.days,
            "trades": self.trades,
            "net_pnl": self.net_pnl,
            "profit_factor": self.profit_factor,
            "win_rate": self.win_rate,
        }


def analyse_regimes(
    candles: pl.DataFrame,
    trades: pl.DataFrame,
) -> list[RegimeSummary]:
    """Attribute closed trades to their regime day; summarize per regime.

    Trades are matched on their ``entry_time`` date; trades on days absent
    from the candle frame are dropped. Empty trade frames produce zeroed
    summaries in fixed regime order (high, mid, low).
    """
    regimes = day_regime_labels(candles)
    if trades.height == 0:
        return [
            RegimeSummary(regime, 0, 0, 0.0, 0.0, 0.0)
            for regime in REGIME_ORDER
        ]

    with_regime = trades.with_columns(
        pl.col("entry_time").dt.date().alias("day_of")
    ).join(regimes.select("day_of", "regime"), on="day_of", how="inner")

    summaries: list[RegimeSummary] = []
    for regime in REGIME_ORDER:
        sub = with_regime.filter(pl.col("regime") == regime)
        count = sub.height
        net = float(sub["net_pnl"].sum()) if count else 0.0
        if count:
            wins = int(sub.filter(pl.col("net_pnl") > 0).height)
            win_rate = wins / count
            gross_wins = float(sub.filter(pl.col("net_pnl") > 0)["gross_pnl"].sum())
            gross_losses = abs(
                float(sub.filter(pl.col("net_pnl") <= 0)["gross_pnl"].sum())
            )
            pf = gross_wins / gross_losses if gross_losses else 0.0
        else:
            win_rate, pf = 0.0, 0.0
        days = int(regimes.filter(pl.col("regime") == regime).height)
        summaries.append(
            RegimeSummary(
                regime=regime,
                days=days,
                trades=count,
                net_pnl=net,
                profit_factor=pf,
                win_rate=win_rate,
            )
        )
    return summaries
