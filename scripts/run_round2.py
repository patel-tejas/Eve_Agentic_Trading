"""Phase 09 -- Round 2: exit tuning for the EMA survivors (Stage 2 of its
staged search) + validation-split out-of-sample check for every family's
round-1 train-split winners.

Two stages, in order:

(2a) EMA EXIT TUNING (TRAIN split): take the top-K DISTINCT 15m entry
     configs per instrument from round 1 (5m dropped -- weak in round 1,
     consistent with Phase 1's cost finding), cross each with an LHS
     sample of STAGE2_EXIT_GRID, run on the TRAIN split, keep the best
     exit per entry by net_pnl. This is still in-sample selection --
     round 3 does local refinement; this step only widens what round 1
     fixed at one exit config.

(2b) VALIDATION-SPLIT SCORING: take round 2a's best (entry+exit) EMA
     configs AND round 1's top-N per (strategy, instrument, timeframe)
     cell for the 5 SMC families (whose exits are already structural and
     were already fully swept in round 1 -- nothing to widen), and score
     ALL of them ONCE on DISCOVERY_SPLITS["val"] (2025, untouched by
     round 1). This is the first genuinely out-of-sample check any
     candidate in this campaign has faced.

The TEST split (2026) is not touched by this script.

Invoke as a module (``python -m scripts.run_round2``), not as a bare
script path -- it imports ``scripts.run_round1`` as a package, which
only resolves when the repo root (not ``scripts/``) is on ``sys.path``.
"""

from __future__ import annotations

import argparse
import json
import time

import polars as pl

import quant.strategies.ema_9_15  # noqa: F401
import quant.strategies.ist_judas  # noqa: F401
import quant.strategies.orb_vwap  # noqa: F401
import quant.strategies.pdh_pdl_turtle_soup  # noqa: F401
import quant.strategies.smc_ob_choch  # noqa: F401
import quant.strategies.smc_sweep_fvg  # noqa: F401
from quant.data.index_spot import resolve_contract_specs
from quant.data.upstox import UpstoxClient
from quant.research.leaderboard import load_leaderboard
from quant.research.parameter_search import STAGE2_EXIT_GRID
from quant.research.protocol import DISCOVERY_SPLITS
from quant.research.sampling import canonical_params, sample_combinations
from quant.research.sweep import Trial, run_sweep
from scripts.run_round1 import INSTRUMENTS, candles_path

EMA_TIMEFRAME = "15m"  # 5m dropped -- weak across all instruments in round 1
TOP_K_ENTRIES = 6
EXIT_SAMPLE_N = 128
TOP_N_SMC_PER_CELL = 5


def _numify(frame: pl.DataFrame) -> pl.DataFrame:
    cols = ["net_pnl", "profit_factor", "max_drawdown_pct", "total_trades", "pct_closed_at_end"]
    return frame.with_columns([pl.col(c).cast(pl.Float64, strict=False) for c in cols])


def top_k_distinct_ema_entries(lb: pl.DataFrame, symbol: str, k: int) -> list[dict]:
    """Round 1's top params for one instrument, deduped on EFFECT (round 1
    showed crossover_and_angle == crossover_angle_and_trend everywhere --
    the trend filter never discriminates, matching the repo's own July
    2026 baseline finding -- so treat those as one entry, not two)."""
    cell = lb.filter(
        (pl.col("strategy_id") == "ema")
        & (pl.col("timeframe") == EMA_TIMEFRAME)
        & (pl.col("symbol") == symbol)
    ).sort("net_pnl", descending=True)

    seen: set[tuple] = set()
    out: list[dict] = []
    for row in cell.to_dicts():
        params = json.loads(row["params_json"])
        key = tuple(sorted(canonical_params("ema", params).items()))
        if key in seen:
            continue
        seen.add(key)
        out.append(params)
        if len(out) >= k:
            break
    return out


def run_stage2a(campaign_id: str, round_no: int, seed: int, workers: int, root: str) -> None:
    r1 = _numify(
        load_leaderboard(campaign_id, round_no=1, root=root).filter(pl.col("status") == "ok")
    )
    clean = r1.filter((pl.col("pct_closed_at_end") == 0) & (pl.col("total_trades") >= 100))

    client = UpstoxClient(require_auth=False)
    specs = {sym: resolve_contract_specs(sym, client=client) for sym in INSTRUMENTS}
    train_start, train_end = DISCOVERY_SPLITS["train"]

    trials: list[Trial] = []
    for symbol in INSTRUMENTS:
        entries = top_k_distinct_ema_entries(clean, symbol, TOP_K_ENTRIES)
        exit_combos = sample_combinations(
            STAGE2_EXIT_GRID, n=EXIT_SAMPLE_N, seed=seed, method="lhs"
        )
        market = specs[symbol]
        for entry_params in entries:
            for exit_params in exit_combos:
                trials.append(
                    Trial(
                        campaign_id=campaign_id,
                        round=round_no,
                        strategy_id="ema",
                        strategy_version="v1",
                        params=entry_params,
                        exits=exit_params,
                        symbol=symbol,
                        price_source="index_spot_proxy",
                        timeframe=EMA_TIMEFRAME,
                        split="train",
                        candles_path=candles_path(symbol, EMA_TIMEFRAME),
                        window_start=train_start.isoformat(),
                        window_end=train_end.isoformat(),
                        lot_size=market["lot_size"],
                        tick_size_rupees=market["tick_size"] / 100.0,
                        seed=seed,
                    )
                )

    print(f"[2a] {len(trials)} EMA exit-tuning trials (train split)")
    summary = run_sweep(
        trials, campaign_id=campaign_id, round_no=round_no, workers=workers, root=root
    )
    print(f"[2a] {summary}")


def best_ema_entry_exit_per_instrument(
    campaign_id: str, round_no: int, root: str
) -> list[dict]:
    lb = _numify(
        load_leaderboard(campaign_id, round_no=round_no, root=root).filter(
            (pl.col("status") == "ok") & (pl.col("strategy_id") == "ema")
        )
    )
    clean = lb.filter((pl.col("pct_closed_at_end") == 0) & (pl.col("total_trades") >= 100))
    out = []
    for symbol in INSTRUMENTS:
        cell = clean.filter(pl.col("symbol") == symbol).sort("net_pnl", descending=True)
        if cell.height == 0:
            continue
        best = cell.row(0, named=True)
        out.append(
            {
                "symbol": symbol,
                "params": json.loads(best["params_json"]),
                "exits": json.loads(best["exits_json"]),
                "train_net_pnl": best["net_pnl"],
            }
        )
    return out


def run_stage2b(
    campaign_id: str, round1_no: int, round2a_no: int, round2b_no: int, seed: int,
    workers: int, root: str,
) -> None:
    client = UpstoxClient(require_auth=False)
    specs = {sym: resolve_contract_specs(sym, client=client) for sym in INSTRUMENTS}
    val_start, val_end = DISCOVERY_SPLITS["val"]

    trials: list[Trial] = []

    # EMA: round 2a's best (entry, exit) per instrument.
    for winner in best_ema_entry_exit_per_instrument(campaign_id, round2a_no, root):
        symbol = winner["symbol"]
        market = specs[symbol]
        trials.append(
            Trial(
                campaign_id=campaign_id,
                round=round2b_no,
                strategy_id="ema",
                strategy_version="v1",
                params=winner["params"],
                exits=winner["exits"],
                symbol=symbol,
                price_source="index_spot_proxy",
                timeframe=EMA_TIMEFRAME,
                split="val",
                candles_path=candles_path(symbol, EMA_TIMEFRAME),
                window_start=val_start.isoformat(),
                window_end=val_end.isoformat(),
                lot_size=market["lot_size"],
                tick_size_rupees=market["tick_size"] / 100.0,
                seed=seed,
            )
        )
        print(
            f"[2b] EMA {symbol}: carrying train-net={winner['train_net_pnl']:.0f} "
            f"config into validation"
        )

    # The 5 SMC families: round 1's top-N per (strategy, symbol, timeframe)
    # cell, re-scored on validation. Their exits are already structural
    # (stop_mode="signal") and were fully swept in round 1 -- nothing to
    # widen, so no equivalent of stage 2a is needed for them.
    r1 = _numify(
        load_leaderboard(campaign_id, round_no=round1_no, root=root).filter(
            (pl.col("status") == "ok") & (pl.col("strategy_id") != "ema")
        )
    )
    clean = r1.filter((pl.col("pct_closed_at_end") == 0) & (pl.col("total_trades") >= 100))
    for (strategy_id, symbol, timeframe), group in clean.group_by(
        ["strategy_id", "symbol", "timeframe"]
    ):
        market = specs[symbol]
        top = group.sort("net_pnl", descending=True).head(TOP_N_SMC_PER_CELL)
        for row in top.to_dicts():
            trials.append(
                Trial(
                    campaign_id=campaign_id,
                    round=round2b_no,
                    strategy_id=strategy_id,
                    strategy_version="v1",
                    params=json.loads(row["params_json"]),
                    exits=json.loads(row["exits_json"]),
                    symbol=symbol,
                    price_source="index_spot_proxy",
                    timeframe=timeframe,
                    split="val",
                    candles_path=candles_path(symbol, timeframe),
                    window_start=val_start.isoformat(),
                    window_end=val_end.isoformat(),
                    lot_size=market["lot_size"],
                    tick_size_rupees=market["tick_size"] / 100.0,
                    seed=seed,
                )
            )

    print(f"[2b] {len(trials)} validation-split trials total")
    summary = run_sweep(
        trials, campaign_id=campaign_id, round_no=round2b_no, workers=workers, root=root
    )
    print(f"[2b] {summary}")


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--campaign", default="C2026-09-EMA-SMC")
    parser.add_argument("--workers", type=int, default=14)
    parser.add_argument("--seed", type=int, default=43)
    parser.add_argument("--root", default="data/results/leaderboard")
    parser.add_argument("--stage", choices=["2a", "2b", "both"], default="both")
    args = parser.parse_args()

    t0 = time.time()
    if args.stage in ("2a", "both"):
        run_stage2a(args.campaign, round_no=2, seed=args.seed, workers=args.workers, root=args.root)
    if args.stage in ("2b", "both"):
        run_stage2b(
            args.campaign, round1_no=1, round2a_no=2, round2b_no=3,
            seed=args.seed, workers=args.workers, root=args.root,
        )
    print(f"[round2] total wall={time.time() - t0:.1f}s")


if __name__ == "__main__":
    main()
