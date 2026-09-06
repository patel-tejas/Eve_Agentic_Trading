"""Heikin Ashi candle transform.

Heikin Ashi ("average bar") smooths price action into synthetic OHLC
values so trend/indecision reads more cleanly than on raw candles. Used
here purely as an ENTRY FILTER (a small-bodied HA candle at a crossover
signals the last two bars disagreed, i.e. a genuine loss of directional
momentum) -- stops and fills always use REAL OHLC, never HA prices; see
``quant.strategies.ema_ha_pattern``.

Definition:
    ha_close[t] = (open[t] + high[t] + low[t] + close[t]) / 4
    ha_open[t]  = (ha_open[t-1] + ha_close[t-1]) / 2,  seeded by
                  ha_open[0] = (open[0] + close[0]) / 2
    ha_high[t]  = max(high[t], ha_open[t], ha_close[t])
    ha_low[t]   = min(low[t],  ha_open[t], ha_close[t])

``ha_open`` is the only recursive piece. It is NOT computed with a
Python loop: let ``x[t] = ha_close[t-1]`` for ``t >= 1`` and
``x[0] = (open[0] + close[0]) / 2`` (the seed). Then
``ha_open[t] = 0.5 * ha_open[t-1] + 0.5 * x[t]`` is exactly an
EWM-mean recursion with ``alpha=0.5`` and NO adjustment (``adjust=False``)
seeded at ``x[0]`` -- which is precisely what ``Expr.ewm_mean(alpha=0.5,
adjust=False)`` computes over the series ``x``. This is algebraically
identical to the textbook recursion including its seed (verified against
a hand-computed 5-bar fixture in ``tests/test_phase11_heikin_ashi.py``),
and it is causal by construction: ``x[t]`` only ever depends on bar
``t-1`` or earlier, and ``ewm_mean`` only ever looks backward.
"""

from __future__ import annotations

import polars as pl


def add_heikin_ashi(frame: pl.DataFrame, *, prefix: str = "ha_") -> pl.DataFrame:
    """Return ``frame`` with ``{prefix}open/high/low/close`` columns attached.

    Requires ``open``, ``high``, ``low``, ``close``. Causal: bar ``t``'s
    HA values depend only on bars ``<= t``.
    """
    missing = [c for c in ("open", "high", "low", "close") if c not in frame.columns]
    if missing:
        raise ValueError(f"add_heikin_ashi requires columns {missing}")

    ha_close_col = f"{prefix}close"
    ha_open_col = f"{prefix}open"
    ha_high_col = f"{prefix}high"
    ha_low_col = f"{prefix}low"

    with_close = frame.with_columns(
        ((pl.col("open") + pl.col("high") + pl.col("low") + pl.col("close")) / 4.0).alias(
            ha_close_col
        )
    )

    # x[t] = ha_close[t-1] for t >= 1, x[0] = (open[0] + close[0]) / 2 (the
    # textbook seed) -- built by shifting ha_close forward one bar and
    # filling the now-null first row with the seed value.
    seed = (pl.col("open") + pl.col("close")).first() / 2.0
    x = pl.col(ha_close_col).shift(1).fill_null(seed)

    with_open = with_close.with_columns(
        x.ewm_mean(alpha=0.5, adjust=False).alias(ha_open_col)
    )

    return with_open.with_columns(
        pl.max_horizontal("high", ha_open_col, ha_close_col).alias(ha_high_col),
        pl.min_horizontal("low", ha_open_col, ha_close_col).alias(ha_low_col),
    )
