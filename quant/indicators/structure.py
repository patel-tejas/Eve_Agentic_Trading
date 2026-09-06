"""Causal Smart-Money-Concepts (SMC/ICT) primitives.

Phase 09: the reference implementation for these concepts,
``smartmoneyconcepts`` (joshyattridge/smart-money-concepts on PyPI), is
NOT used here. Two disqualifying reasons, verified before writing this
module:

1. Its ``swing_highs_lows`` is CENTERED -- documented as "the highest
   high out of the swing_length candles before AND AFTER" -- so reading
   it at bar ``i`` peeks ``swing_length`` bars into the future.
   ``MitigatedIndex`` (from ``fvg``) and ``BrokenIndex`` (from
   ``bos_choch``) are likewise backward-annotated columns describing
   what happened LATER. This is the single most common way an SMC
   backtest manufactures fake edge.
2. It is pandas-based; this repo is deliberately Polars-only.

Every function below is causal by construction: its value at bar ``i``
uses only bars ``<= i``. This is mechanically enforced by
``tests/test_phase09_causality.py``, which asserts that computing a
primitive on ``frame.head(i+1)`` gives the same value at row ``i`` as
computing it on the full frame -- for EVERY function here. That test is
the actual guarantee; read it alongside this module.

Swing/pivot confirmation delay: a pivot high/low at index ``p`` needs
``right`` bars to close after it before we can say "nothing since has
exceeded it" -- so it is EMITTED (becomes visible) at index ``p+right``,
never at ``p`` itself. This delay is the causal cost of using swing
points at all, and it is an explicit, swept parameter (``right``), not
hidden.
"""

from __future__ import annotations

from datetime import time

import polars as pl

from quant.candles.session import parse_time

# ---------------------------------------------------------------------------
# Swing highs/lows (confirmed pivots)
# ---------------------------------------------------------------------------


def add_swings(frame: pl.DataFrame, *, left: int = 3, right: int = 3) -> pl.DataFrame:
    """Confirmed swing highs/lows.

    A bar at index ``p`` is a swing high if ``high[p]`` is strictly
    greater than every high in ``[p-left, p-1]`` AND every high in
    ``[p+1, p+right]``. Because the second half of that condition needs
    ``right`` future bars, the fact "bar p was a swing high" is only
    knowable, and therefore only EMITTED, at bar ``p+right`` -- encoded
    below by shifting the raw pivot boolean/level forward by ``right``.
    Swing low is the mirror condition on ``low``.

    New columns: ``swing_high_confirmed`` (bool), ``swing_high_level``
    (float, null unless confirmed this bar), and the low equivalents.
    """
    if left < 1 or right < 1:
        raise ValueError("left and right must both be >= 1")

    def _backward_max(col: str, window: int) -> pl.Expr:
        return pl.col(col).shift(1).rolling_max(window_size=window, min_samples=window)

    def _backward_min(col: str, window: int) -> pl.Expr:
        return pl.col(col).shift(1).rolling_min(window_size=window, min_samples=window)

    def _forward_max(col: str, window: int) -> pl.Expr:
        # Reverse, take a BACKWARD rolling max (which after reversing is a
        # forward-looking max of the next `window` bars), reverse back.
        return (
            pl.col(col)
            .reverse()
            .shift(1)
            .rolling_max(window_size=window, min_samples=window)
            .reverse()
        )

    def _forward_min(col: str, window: int) -> pl.Expr:
        return (
            pl.col(col)
            .reverse()
            .shift(1)
            .rolling_min(window_size=window, min_samples=window)
            .reverse()
        )

    raw = frame.with_columns(
        (
            (pl.col("high") > _backward_max("high", left))
            & (pl.col("high") > _forward_max("high", right))
        ).alias("_pivot_high"),
        (
            (pl.col("low") < _backward_min("low", left))
            & (pl.col("low") < _forward_min("low", right))
        ).alias("_pivot_low"),
    )

    out = raw.with_columns(
        pl.col("_pivot_high").shift(right).fill_null(False).alias("swing_high_confirmed"),
        pl.when(pl.col("_pivot_high").shift(right).fill_null(False))
        .then(pl.col("high").shift(right))
        .otherwise(None)
        .alias("swing_high_level"),
        pl.col("_pivot_low").shift(right).fill_null(False).alias("swing_low_confirmed"),
        pl.when(pl.col("_pivot_low").shift(right).fill_null(False))
        .then(pl.col("low").shift(right))
        .otherwise(None)
        .alias("swing_low_level"),
    )
    return out.drop("_pivot_high", "_pivot_low")


# ---------------------------------------------------------------------------
# Fair value gaps (3-bar imbalance)
# ---------------------------------------------------------------------------


def add_fvg(frame: pl.DataFrame) -> pl.DataFrame:
    """3-bar fair value gaps, known at the close of the third bar.

    Bullish FVG at bar ``t``: ``low[t] > high[t-2]`` (a gap between
    candle ``t-2``'s high and candle ``t``'s low, with candle ``t-1`` the
    displacement candle in between). Bearish is the mirror on
    ``high[t] < low[t-2]``. Purely backward-looking -- no confirmation
    delay needed, unlike swings.

    Mitigation (``fvg_mitigated``, ``fvg_mitigated_bars_after``) is
    tracked forward with a single pass over the bars in order: a gap is
    mitigated the first bar whose range trades back into the gap zone.
    This is inherently a running/stateful computation (an open gap
    remains open until an as-yet-unknown future bar closes it), so it is
    computed with an explicit per-bar loop rather than a vectorised
    expression -- the loop only ever reads bars up to the current one,
    which is what keeps it causal, and at a few thousand bars per
    instrument/timeframe/month it costs microseconds.
    """
    n = frame.height
    highs = frame["high"].to_list()
    lows = frame["low"].to_list()

    bullish = [False] * n
    bearish = [False] * n
    top = [None] * n
    bottom = [None] * n
    mitigated = [False] * n  # mitigated AS OF this bar (was open, now closed)

    open_bull: list[tuple[int, float, float]] = []  # (formed_idx, top, bottom)
    open_bear: list[tuple[int, float, float]] = []

    for t in range(n):
        if t >= 2:
            if lows[t] > highs[t - 2]:
                bullish[t] = True
                top[t] = lows[t]
                bottom[t] = highs[t - 2]
                open_bull.append((t, lows[t], highs[t - 2]))
            elif highs[t] < lows[t - 2]:
                bearish[t] = True
                top[t] = lows[t - 2]
                bottom[t] = highs[t]
                open_bear.append((t, lows[t - 2], highs[t]))

        # Check whether THIS bar's range mitigates any still-open gap
        # formed strictly before it.
        still_open_bull = []
        for formed_idx, gtop, gbottom in open_bull:
            if formed_idx < t and lows[t] <= gtop:
                mitigated[t] = True
            else:
                still_open_bull.append((formed_idx, gtop, gbottom))
        open_bull = still_open_bull

        still_open_bear = []
        for formed_idx, gtop, gbottom in open_bear:
            if formed_idx < t and highs[t] >= gbottom:
                mitigated[t] = True
            else:
                still_open_bear.append((formed_idx, gtop, gbottom))
        open_bear = still_open_bear

    return frame.with_columns(
        pl.Series("fvg_bullish", bullish, dtype=pl.Boolean),
        pl.Series("fvg_bearish", bearish, dtype=pl.Boolean),
        pl.Series("fvg_top", top, dtype=pl.Float64),
        pl.Series("fvg_bottom", bottom, dtype=pl.Float64),
        pl.Series("fvg_mitigated_this_bar", mitigated, dtype=pl.Boolean),
    )


# ---------------------------------------------------------------------------
# Break of structure / Change of character
# ---------------------------------------------------------------------------


def add_bos_choch(
    frame: pl.DataFrame,
    *,
    swings: pl.DataFrame | None = None,
    left: int = 3,
    right: int = 3,
    close_break: bool = True,
) -> pl.DataFrame:
    """Break of Structure / Change of Character against CONFIRMED swings.

    A bullish BOS/CHoCH at bar ``t`` fires when ``close[t]`` (or
    ``high[t]`` if ``close_break=False``) trades beyond the most
    recently CONFIRMED swing high known as of bar ``t`` -- i.e. the
    forward-filled ``swing_high_level`` from :func:`add_swings`, which is
    itself already causal. BOS = break in the direction of the prevailing
    trend (last break was also bullish, or no prior break yet); CHoCH =
    break against it. Only one break is flagged per level (the level is
    "used up" once broken, matching the ICT convention that a CHoCH marks
    a new structure).
    """
    if swings is not None:
        base = frame.join(
            swings.select(
                "timestamp",
                "swing_high_confirmed",
                "swing_high_level",
                "swing_low_confirmed",
                "swing_low_level",
            ),
            on="timestamp",
            how="left",
        )
    else:
        base = add_swings(frame, left=left, right=right)

    last_high = pl.col("swing_high_level").forward_fill()
    last_low = pl.col("swing_low_level").forward_fill()

    working = base.with_columns(
        last_high.alias("_last_swing_high"), last_low.alias("_last_swing_low")
    )

    n = working.height
    ref_up = (working["close"] if close_break else working["high"]).to_list()
    ref_down = (working["close"] if close_break else working["low"]).to_list()
    last_high_vals = working["_last_swing_high"].to_list()
    last_low_vals = working["_last_swing_low"].to_list()

    bos = [False] * n
    choch = [False] * n
    level = [None] * n
    broken_direction = [None] * n

    used_high: set[float] = set()
    used_low: set[float] = set()
    trend: str | None = None  # "up" | "down" | None

    for t in range(n):
        lh = last_high_vals[t]
        ll = last_low_vals[t]
        if lh is not None and ref_up[t] > lh and lh not in used_high:
            used_high.add(lh)
            level[t] = lh
            broken_direction[t] = "up"
            if trend == "down":
                choch[t] = True
            else:
                bos[t] = True
            trend = "up"
        elif ll is not None and ref_down[t] < ll and ll not in used_low:
            used_low.add(ll)
            level[t] = ll
            broken_direction[t] = "down"
            if trend == "up":
                choch[t] = True
            else:
                bos[t] = True
            trend = "down"

    return frame.with_columns(
        pl.Series("bos", bos, dtype=pl.Boolean),
        pl.Series("choch", choch, dtype=pl.Boolean),
        pl.Series("structure_break_level", level, dtype=pl.Float64),
        pl.Series("structure_break_direction", broken_direction, dtype=pl.Utf8),
    )


# ---------------------------------------------------------------------------
# Order blocks
# ---------------------------------------------------------------------------


def add_order_blocks(
    frame: pl.DataFrame,
    *,
    swings: pl.DataFrame | None = None,
    left: int = 3,
    right: int = 3,
    displacement_atr_mult: float = 1.0,
    atr_column: str = "atr",
) -> pl.DataFrame:
    """Order blocks: the last opposite-colour candle before a displacement
    leg that produced a CONFIRMED break of structure.

    Requires ``atr_column`` on ``frame`` (see ``quant.indicators.atr``) --
    "displacement" is defined relative to volatility, not an absolute
    point move. Published ONLY when the BOS/CHoCH that it precedes has
    itself been confirmed (i.e. at the same bar ``add_bos_choch`` flags
    ``bos``/``choch`` True) -- an order block is never surfaced ahead of
    the structure break that identifies it.
    """
    if atr_column not in frame.columns:
        raise ValueError(f"add_order_blocks requires an '{atr_column}' column (see add_atr)")

    structure = add_bos_choch(frame, swings=swings, left=left, right=right)
    n = frame.height
    opens = frame["open"].to_list()
    closes = frame["close"].to_list()
    atrs = frame[atr_column].to_list()
    bos_list = structure["bos"].to_list()
    choch_list = structure["choch"].to_list()
    direction_list = structure["structure_break_direction"].to_list()

    ob_top = [None] * n
    ob_bottom = [None] * n
    ob_bullish = [False] * n
    ob_bearish = [False] * n

    for t in range(n):
        if not (bos_list[t] or choch_list[t]):
            continue
        direction = direction_list[t]
        atr_t = atrs[t]
        if atr_t is None:
            continue
        displacement_needed = displacement_atr_mult * atr_t
        # Walk backward from t-1 for the last OPPOSITE-colour candle before
        # a candle whose body >= the displacement threshold. Only looks
        # at bars < t -- causal by construction.
        for j in range(t - 1, max(t - 20, -1), -1):
            body = closes[j] - opens[j]
            if direction == "up" and body >= displacement_needed:
                # look further back for the last bearish candle before j
                for k in range(j, max(j - 10, -1), -1):
                    if closes[k] < opens[k]:
                        ob_top[t] = max(opens[k], closes[k])
                        ob_bottom[t] = min(opens[k], closes[k])
                        ob_bullish[t] = True
                        break
                break
            if direction == "down" and -body >= displacement_needed:
                for k in range(j, max(j - 10, -1), -1):
                    if closes[k] > opens[k]:
                        ob_top[t] = max(opens[k], closes[k])
                        ob_bottom[t] = min(opens[k], closes[k])
                        ob_bearish[t] = True
                        break
                break

    return frame.with_columns(
        pl.Series("ob_bullish", ob_bullish, dtype=pl.Boolean),
        pl.Series("ob_bearish", ob_bearish, dtype=pl.Boolean),
        pl.Series("ob_top", ob_top, dtype=pl.Float64),
        pl.Series("ob_bottom", ob_bottom, dtype=pl.Float64),
    )


# ---------------------------------------------------------------------------
# Previous-day / session levels
# ---------------------------------------------------------------------------


def add_prev_day_levels(frame: pl.DataFrame, *, timestamp_col: str = "timestamp") -> pl.DataFrame:
    """Previous COMPLETED session's high/low/close, forward-filled through
    the current session. Never uses the current (still in progress)
    session's own bars."""
    daily = (
        frame.select(pl.col(timestamp_col).dt.date().alias("_day"), "high", "low", "close")
        .group_by("_day")
        .agg(
            pl.col("high").max().alias("_day_high"),
            pl.col("low").min().alias("_day_low"),
            pl.col("close").last().alias("_day_close"),
        )
        .sort("_day")
        .with_columns(
            pl.col("_day_high").shift(1).alias("pdh"),
            pl.col("_day_low").shift(1).alias("pdl"),
            pl.col("_day_close").shift(1).alias("pdc"),
        )
        .select("_day", "pdh", "pdl", "pdc")
    )
    return (
        frame.with_columns(pl.col(timestamp_col).dt.date().alias("_day"))
        .join(daily, on="_day", how="left")
        .drop("_day")
    )


def add_session_levels(
    frame: pl.DataFrame,
    *,
    start: str | time = "09:15",
    end: str | time = "09:45",
    prefix: str = "or",
    timestamp_col: str = "timestamp",
) -> pl.DataFrame:
    """Opening-range (or any intraday window) high/low, published only
    once the window has CLOSED, forward-filled for the rest of the
    session. Null before the window closes on any given day -- the range
    is not knowable mid-formation."""
    start_t, end_t = parse_time(start), parse_time(end)
    with_day = frame.with_columns(pl.col(timestamp_col).dt.date().alias("_day"))
    in_window = with_day.filter(
        pl.col(timestamp_col).dt.time().is_between(start_t, end_t, closed="left")
    )
    window_levels = in_window.group_by("_day").agg(
        pl.col("high").max().alias(f"{prefix}_high"),
        pl.col("low").min().alias(f"{prefix}_low"),
    )
    joined = with_day.join(window_levels, on="_day", how="left")
    # Null out the level for bars that fall BEFORE the window has closed
    # this session (it is not yet known), even though the join filled it
    # for the whole day.
    not_yet_known = pl.col(timestamp_col).dt.time() < end_t
    return joined.with_columns(
        pl.when(not_yet_known).then(None).otherwise(pl.col(f"{prefix}_high")).alias(f"{prefix}_high"),
        pl.when(not_yet_known).then(None).otherwise(pl.col(f"{prefix}_low")).alias(f"{prefix}_low"),
    ).drop("_day")


# ---------------------------------------------------------------------------
# VWAP
# ---------------------------------------------------------------------------


def add_vwap(
    frame: pl.DataFrame,
    *,
    anchor: str = "session",
    volume_col: str = "volume",
    fallback: str = "typical_price",
    timestamp_col: str = "timestamp",
) -> pl.DataFrame:
    """Session-anchored VWAP, a cumulative (expanding) quantity -- causal
    by construction, since it only ever divides a running sum by a
    running count/volume up to the current bar.

    Falls back to an unweighted cumulative mean of the typical price
    when ``volume_col`` is all-zero (index spot has no traded volume) --
    the resulting column is NOT a real VWAP and callers must flag it as
    such (``price_source == "index_spot_proxy"``); this function does
    not know or care where its input came from.
    """
    if anchor != "session":
        raise ValueError(f"only anchor='session' is implemented, got {anchor!r}")

    typical = (pl.col("high") + pl.col("low") + pl.col("close")) / 3.0
    day = pl.col(timestamp_col).dt.date()

    has_volume = frame[volume_col].sum() > 0 if volume_col in frame.columns else False

    if has_volume:
        cum_pv = (typical * pl.col(volume_col)).cum_sum().over(day)
        cum_v = pl.col(volume_col).cum_sum().over(day)
        vwap = pl.when(cum_v > 0).then(cum_pv / cum_v).otherwise(typical)
        is_proxy = False
    else:
        cum_p = typical.cum_sum().over(day)
        cum_n = pl.int_range(1, pl.len() + 1).over(day)
        vwap = cum_p / cum_n
        is_proxy = True

    return frame.with_columns(
        vwap.alias("vwap"), pl.lit(is_proxy).alias("vwap_is_proxy")
    )
