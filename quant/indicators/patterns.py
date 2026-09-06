"""Candle-shape primitives: body/wick ratios and the doji/hammer family.

Phase 09/11: measures a single candle's SHAPE, independent of where its
levels sit -- ``prefix=""`` runs against real OHLC, ``prefix="ha_"``
against Heikin Ashi columns (see ``quant.indicators.heikin_ashi``), with
identical logic either way. Every quantity here is defined from a single
bar's own ``open/high/low/close`` (or ``ha_*`` equivalents) plus,
optionally, a rolling ATR column for the "small range" test -- causal by
construction, since neither depends on any other bar.
"""

from __future__ import annotations

import polars as pl


def add_candle_shape(
    frame: pl.DataFrame,
    *,
    prefix: str = "",
    atr_column: str = "atr_14",
    doji_body_pct: float = 0.10,
    hammer_body_pct: float = 0.30,
    wick_ratio: float = 0.55,
    opp_wick_ratio: float = 0.20,
    small_range_atr: float = 0.0,
) -> pl.DataFrame:
    """Attach shape columns for the ``{prefix}open/high/low/close`` candle.

    New columns (all prefixed with ``prefix`` to keep a real-OHLC pass and
    an HA pass distinguishable when both are run on the same frame):
    ``{prefix}body``, ``{prefix}range``, ``{prefix}upper_wick``,
    ``{prefix}lower_wick``, ``{prefix}body_pct`` (``body / range``, null
    when ``range == 0``), and boolean flags ``{prefix}is_doji``,
    ``{prefix}is_hammer``, ``{prefix}is_inverted_hammer``,
    ``{prefix}is_small_range``.

    - ``is_doji``: ``body_pct <= doji_body_pct`` -- a candle with almost
      no net displacement over the bar, regardless of where the wicks are.
    - ``is_hammer``: a small body (``<= hammer_body_pct``) sitting near
      the TOP of its range, with a long lower wick (``>= wick_ratio`` of
      the range) and a short upper wick (``<= opp_wick_ratio``) --
      rejection of lower prices.
    - ``is_inverted_hammer``: the mirror -- long upper wick, short lower
      wick -- rejection of higher prices.
    - ``is_small_range``: ``range <= small_range_atr * ATR``
      (``small_range_atr = 0.0`` disables this check, i.e. always True) --
      a SEPARATE test from the body-ratio ones, for "small difference of
      high and low" independent of body position.
    """
    o, h, low, c = (pl.col(f"{prefix}{k}") for k in ("open", "high", "low", "close"))
    required = (f"{prefix}{k}" for k in ("open", "high", "low", "close"))
    missing = [col for col in required if col not in frame.columns]
    if missing:
        raise ValueError(f"add_candle_shape requires columns {missing}")

    body_col = f"{prefix}body"
    range_col = f"{prefix}range"
    upper_col = f"{prefix}upper_wick"
    lower_col = f"{prefix}lower_wick"
    body_pct_col = f"{prefix}body_pct"
    doji_col = f"{prefix}is_doji"
    hammer_col = f"{prefix}is_hammer"
    inv_hammer_col = f"{prefix}is_inverted_hammer"
    small_range_col = f"{prefix}is_small_range"

    body = (c - o).abs()
    rng = h - low
    upper_wick = h - pl.max_horizontal(o, c)
    lower_wick = pl.min_horizontal(o, c) - low
    body_pct = pl.when(rng > 0).then(body / rng).otherwise(None)

    out = frame.with_columns(
        body.alias(body_col),
        rng.alias(range_col),
        upper_wick.alias(upper_col),
        lower_wick.alias(lower_col),
        body_pct.alias(body_pct_col),
    )

    is_doji = pl.col(body_pct_col) <= doji_body_pct
    is_hammer = (
        (pl.col(body_pct_col) <= hammer_body_pct)
        & (pl.col(lower_col) >= wick_ratio * pl.col(range_col))
        & (pl.col(upper_col) <= opp_wick_ratio * pl.col(range_col))
    )
    is_inverted_hammer = (
        (pl.col(body_pct_col) <= hammer_body_pct)
        & (pl.col(upper_col) >= wick_ratio * pl.col(range_col))
        & (pl.col(lower_col) <= opp_wick_ratio * pl.col(range_col))
    )

    if small_range_atr > 0.0:
        if atr_column not in frame.columns:
            raise ValueError(
                f"add_candle_shape(small_range_atr={small_range_atr!r}) requires "
                f"an {atr_column!r} column (see quant.indicators.atr.add_atr)"
            )
        is_small_range = pl.col(range_col) <= small_range_atr * pl.col(atr_column)
    else:
        is_small_range = pl.lit(True)

    return out.with_columns(
        is_doji.fill_null(False).alias(doji_col),
        is_hammer.fill_null(False).alias(hammer_col),
        is_inverted_hammer.fill_null(False).alias(inv_hammer_col),
        is_small_range.alias(small_range_col),
    )
