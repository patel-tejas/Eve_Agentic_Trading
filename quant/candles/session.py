"""NSE/BSE session helpers.

Phase 09: the two futures months on disk are on different session grids
(July closes 15:29, 375 bars/day; August closes 15:39, 385 bars/day, with
8 malformed 15m buckets per its own verification report). Every session
rule in this module resolves by **wall-clock time**, never bar index, so
it behaves the same regardless of which grid produced the frame.

NSE/BSE cash + F&O session: 09:15-15:30 IST, single continuous session
(no lunch break, no multiple sessions like forex/US-futures markets).
"""

from __future__ import annotations

from datetime import time

import polars as pl

SESSION_START = time(9, 15)
SESSION_END = time(15, 30)


def parse_time(value: str | time) -> time:
    """Parse an ``"HH:MM"`` string (or pass a ``time`` through unchanged)."""
    if isinstance(value, time):
        return value
    hh, mm = value.split(":")
    return time(int(hh), int(mm))


# Backward-compatible private alias.
_parse_time = parse_time


def filter_session(
    frame: pl.DataFrame,
    *,
    start: str | time = SESSION_START,
    end: str | time = SESSION_END,
    timestamp_col: str = "timestamp",
) -> pl.DataFrame:
    """Keep only bars whose wall-clock time falls in ``[start, end)``.

    Drops the out-of-session tail bars (e.g. August's 15:31-15:39) without
    relying on a fixed per-day bar count.
    """
    start_t = parse_time(start)
    end_t = parse_time(end)
    return frame.filter(
        pl.col(timestamp_col).dt.time().is_between(start_t, end_t, closed="left")
    )


def add_session_day(
    frame: pl.DataFrame,
    *,
    timestamp_col: str = "timestamp",
    name: str = "session_day",
) -> pl.DataFrame:
    """Attach the calendar date each bar belongs to (its trading session)."""
    return frame.with_columns(pl.col(timestamp_col).dt.date().alias(name))


def time_at_or_after(expr: pl.Expr, cutoff: str | time) -> pl.Expr:
    """Boolean expression: does this timestamp expr fall at/after ``cutoff``?"""
    return expr.dt.time() >= parse_time(cutoff)


def time_before(expr: pl.Expr, cutoff: str | time) -> pl.Expr:
    """Boolean expression: does this timestamp expr fall strictly before ``cutoff``?"""
    return expr.dt.time() < parse_time(cutoff)
