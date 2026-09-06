"""Phase 0 (HA-pattern variant) -- measure the base rate BEFORE building
anything else.

"Crossover AND small-body HA candle" is a conjunction of two uncommon
events. The pre-registered minima (``quant.research.protocol.MIN_TRADES``)
require >= 100 train trades and >= 30 validation trades. If the
conjunction fires on only a few percent of crossovers, this variant is
UNTESTABLE on 15m/5m data regardless of how good it looks in a chart --
that must be known before spending the engine-surgery effort, not after.

Read-only: no leaderboard writes, no engine run. Just counts crossovers,
counts how many have a qualifying HA pattern within a small window, and
projects the count onto the (much longer) validation split.
"""

from __future__ import annotations

import argparse
import itertools

import polars as pl

from quant.indicators.atr import add_atr
from quant.indicators.ema import add_ema
from quant.indicators.heikin_ashi import add_heikin_ashi
from quant.indicators.patterns import add_candle_shape
from quant.research.protocol import DISCOVERY_SPLITS
from scripts.run_round1 import INSTRUMENTS, candles_path

TIMEFRAMES = ("5m", "15m")
DOJI_BODY_PCTS = (0.10, 0.20, 0.30)
SMALL_RANGE_ATRS = (0.0, 0.8, 1.2)
WINDOWS = (0, 1, 2, 3)

TRAIN_START, TRAIN_END = DISCOVERY_SPLITS["train"]
VAL_START, VAL_END = DISCOVERY_SPLITS["val"]
TRAIN_DAYS = (TRAIN_END - TRAIN_START).days
VAL_DAYS = (VAL_END - VAL_START).days

MIN_TRAIN_TRADES = 100
MIN_VAL_TRADES_PROJECTED = 30


def _crossovers_and_pattern_hits(
    frame: pl.DataFrame, *, doji_body_pct: float, small_range_atr: float, window: int
) -> tuple[int, int]:
    """Return (n_crossovers, n_with_qualifying_pattern_in_window)."""
    work = add_ema(frame, 9)
    work = add_ema(work, 15)
    work = add_atr(work, 14, name="atr_14")
    work = add_heikin_ashi(work)
    ha_for_atr = work.select(
        "timestamp", pl.col("ha_high").alias("high"), pl.col("ha_low").alias("low"),
        pl.col("ha_close").alias("close"),
    )
    ha_atr = add_atr(ha_for_atr, 14, name="ha_atr_14").select("timestamp", "ha_atr_14")
    work = work.join(ha_atr, on="timestamp", how="left")
    work = add_candle_shape(
        work,
        prefix="ha_",
        atr_column="ha_atr_14",
        doji_body_pct=doji_body_pct,
        hammer_body_pct=0.30,
        wick_ratio=0.55,
        opp_wick_ratio=0.20,
        small_range_atr=small_range_atr,
    )

    fast, slow = pl.col("ema_9"), pl.col("ema_15")
    prev_fast, prev_slow = fast.shift(1), slow.shift(1)
    crossover_up = (fast > slow) & (prev_fast <= prev_slow)
    crossover_down = (fast < slow) & (prev_fast >= prev_slow)
    crossover = crossover_up | crossover_down

    qualifies = (
        (pl.col("ha_is_doji") | pl.col("ha_is_hammer") | pl.col("ha_is_inverted_hammer"))
        & pl.col("ha_is_small_range")
    )
    # A crossover at bar t qualifies if `qualifies` is True at any bar in
    # [t-window, t] -- a rolling "was true in the last (window+1) bars"
    # check, evaluated causally (only uses bars <= t).
    qualifies_in_window = (
        qualifies.cast(pl.Int8).rolling_sum(window_size=window + 1, min_samples=1) > 0
    )

    result = work.with_columns(
        crossover.fill_null(False).alias("_crossover"),
        qualifies_in_window.alias("_qualifies_in_window"),
    )
    n_crossovers = int(result["_crossover"].sum())
    n_hits = int(
        result.filter(pl.col("_crossover") & pl.col("_qualifies_in_window")).height
    )
    return n_crossovers, n_hits


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--root", default="data/processed/index")
    args = parser.parse_args()

    print(
        f"[phase0] train span: {TRAIN_START} -> {TRAIN_END} ({TRAIN_DAYS} days); "
        f"val span: {VAL_START} -> {VAL_END} ({VAL_DAYS} days); "
        f"projection factor = val/train = {VAL_DAYS / TRAIN_DAYS:.3f}"
    )
    print(
        f"[phase0] gate: >= {MIN_TRAIN_TRADES} train hits AND "
        f">= {MIN_VAL_TRADES_PROJECTED} projected val hits\n"
    )

    header = (
        f"{'symbol':10} {'tf':4} {'window':6} {'doji%':6} {'range_atr':9} "
        f"{'crossovers':10} {'hits':6} {'hit_rate':9} {'proj_val':9} {'gate'}"
    )
    print(header)
    print("-" * len(header))

    any_pass = False
    best_rows: list[dict] = []
    for symbol in INSTRUMENTS:
        for tf in TIMEFRAMES:
            path = candles_path(symbol, tf, root=args.root)
            frame = pl.read_parquet(path).filter(
                (pl.col("timestamp").dt.date() >= TRAIN_START)
                & (pl.col("timestamp").dt.date() <= TRAIN_END)
            )
            for doji_pct, small_range, window in itertools.product(
                DOJI_BODY_PCTS, SMALL_RANGE_ATRS, WINDOWS
            ):
                n_cross, n_hits = _crossovers_and_pattern_hits(
                    frame, doji_body_pct=doji_pct, small_range_atr=small_range, window=window
                )
                hit_rate = n_hits / n_cross if n_cross else 0.0
                proj_val = n_hits * (VAL_DAYS / TRAIN_DAYS)
                passes = n_hits >= MIN_TRAIN_TRADES and proj_val >= MIN_VAL_TRADES_PROJECTED
                any_pass = any_pass or passes
                row = {
                    "symbol": symbol, "tf": tf, "window": window, "doji_pct": doji_pct,
                    "small_range_atr": small_range, "n_crossovers": n_cross, "n_hits": n_hits,
                    "hit_rate": hit_rate, "proj_val": proj_val, "passes": passes,
                }
                best_rows.append(row)
                marker = "PASS" if passes else ""
                print(
                    f"{symbol:10} {tf:4} {window:6d} {doji_pct:<6.2f} {small_range:<9.2f} "
                    f"{n_cross:10d} {n_hits:6d} {hit_rate:9.2%} {proj_val:9.1f} {marker}"
                )

    print()
    n_passing = sum(1 for r in best_rows if r["passes"])
    print(f"[phase0] {n_passing} of {len(best_rows)} (symbol, tf, threshold) cells pass the gate.")
    if not any_pass:
        print(
            "\n[phase0] GATE FAILED: no cell projects enough validation trades. "
            "This variant is untestable at these thresholds/timeframes -- widen "
            "`window`, loosen the body thresholds, or pool instruments before "
            "building the engine changes."
        )
    else:
        print(
            "\n[phase0] GATE PASSED for at least one cell -- proceeding to Phase 1/2/3 "
            "(Heikin Ashi primitives already built; strategy + scale-out exits next)."
        )


if __name__ == "__main__":
    main()
