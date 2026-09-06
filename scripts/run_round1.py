"""Phase 09 -- Round 1: EMA family (re-normalized entry, fixed exit) +
the 5 SMC/ICT families, on the DISCOVERY TRAIN split only.

Scope, deliberately bounded for round 1 (per the implementation plan,
Phase 7's round protocol): search ENTRY logic broadly, hold exits at one
reasonable fixed configuration. Exit tuning (Stage 2/3 of the EMA
search) is round 2+ work, once round 1 says which entry logic and which
strategy families are worth spending that budget on.

Instruments x timeframes: {NIFTY, BANKNIFTY, SENSEX} x {5m, 15m} (1m
dropped -- Phase 1 found break-even needs 0.86 ATR of net edge per
trade on 1m, which no EMA crossover produces at any setting).

Split: DISCOVERY_SPLITS["train"] = 2022-01-01 -> 2024-12-31, index-spot
data. The validation and test splits are untouched by this script.
"""

from __future__ import annotations

import argparse
import time

import quant.strategies.ema_9_15  # noqa: F401
import quant.strategies.ist_judas  # noqa: F401
import quant.strategies.orb_vwap  # noqa: F401
import quant.strategies.pdh_pdl_turtle_soup  # noqa: F401
import quant.strategies.smc_ob_choch  # noqa: F401
import quant.strategies.smc_sweep_fvg  # noqa: F401
from quant.data.index_spot import resolve_contract_specs
from quant.data.upstox import UpstoxClient
from quant.research.leaderboard import load_leaderboard
from quant.research.protocol import DISCOVERY_SPLITS, seal_protocol
from quant.research.sampling import dedupe_by_effect, full_combinations
from quant.research.sweep import Trial, run_sweep
from quant.strategies.base import STRATEGY_REGISTRY

INSTRUMENTS = ("NIFTY", "BANKNIFTY", "SENSEX")
TIMEFRAMES = ("5m", "15m")

# Round 1's fixed exit -- one reasonable bracket, not yet swept.
FIXED_EXIT = {
    "stop_mode": "atr",
    "stop_atr_mult": 1.5,
    "target_mode": "r_multiple",
    "target_r_multiple": 2.0,
    "trail_mode": "none",
    "eod_squareoff": "15:15",  # 15:15, not 15:20 -- see exits.py docstring
}
# SMC strategies carry their own structural stop/target (stop_mode="signal").
SIGNAL_EXIT = {"stop_mode": "signal", "target_mode": "signal", "eod_squareoff": "15:15"}


def candles_path(symbol: str, timeframe: str, root: str = "data/processed/index") -> str:
    # quant.data.store.load_candles concatenates months; for round 1 we
    # sweep each (symbol, timeframe) as one continuous frame built once
    # up front and cached by the worker (see quant.research.sweep._load_candles).
    return f"{root}/{symbol}/__continuous_{timeframe}.parquet"


def build_continuous_frames(root: str = "data/processed/index") -> None:
    """Materialize one concatenated parquet per (symbol, timeframe) so
    sweep workers can each load it via a plain file path (Trial.candles_path
    must be a path, never a passed-in DataFrame)."""
    from quant.data.store import load_candles

    for symbol in INSTRUMENTS:
        for tf in TIMEFRAMES:
            frame = load_candles(symbol, tf, asset_class="index")
            out = candles_path(symbol, tf, root=root)
            frame.write_parquet(out)
            print(f"[prep] {symbol} {tf}: {frame.height} bars -> {out}")


def build_trials(campaign_id: str, round_no: int, seed: int) -> list[Trial]:
    client = UpstoxClient(require_auth=False)
    specs = {sym: resolve_contract_specs(sym, client=client) for sym in INSTRUMENTS}

    train_start, train_end = DISCOVERY_SPLITS["train"]
    window_start = train_start.isoformat()
    window_end = train_end.isoformat()

    trials: list[Trial] = []
    for strategy_id, spec in STRATEGY_REGISTRY.items():
        constraints = []
        if strategy_id == "ema":
            constraints.append(lambda c: c["fast_ema"] < c["slow_ema"])
            exits = FIXED_EXIT
        else:
            exits = SIGNAL_EXIT

        combos = full_combinations(spec.param_space, constraints=constraints)
        combos = dedupe_by_effect(strategy_id, combos)

        for symbol in INSTRUMENTS:
            market = specs[symbol]
            for timeframe in TIMEFRAMES:
                for params in combos:
                    trials.append(
                        Trial(
                            campaign_id=campaign_id,
                            round=round_no,
                            strategy_id=strategy_id,
                            strategy_version="v1",
                            params=params,
                            exits=exits,
                            symbol=symbol,
                            price_source="index_spot_proxy",
                            timeframe=timeframe,
                            split="train",
                            candles_path=candles_path(symbol, timeframe),
                            window_start=window_start,
                            window_end=window_end,
                            lot_size=market["lot_size"],
                            tick_size_rupees=market["tick_size"] / 100.0,
                            seed=seed,
                        )
                    )
    return trials


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--campaign", default="C2026-09-EMA-SMC")
    parser.add_argument("--round", type=int, default=1)
    parser.add_argument("--workers", type=int, default=14)
    parser.add_argument("--seed", type=int, default=42)
    parser.add_argument("--root", default="data/results/leaderboard")
    parser.add_argument(
        "--skip-prep", action="store_true", help="reuse existing continuous parquets"
    )
    args = parser.parse_args()

    now = time.strftime("%Y-%m-%dT%H:%M:%S")
    seal = seal_protocol(args.campaign, root="data/results/search", now=now)
    print(f"[protocol] campaign={args.campaign} protocol_hash={seal.protocol_hash}")

    if not args.skip_prep:
        build_continuous_frames()

    trials = build_trials(args.campaign, args.round, args.seed)
    print(f"[build] {len(trials)} trials across {len(STRATEGY_REGISTRY)} strategies, "
          f"{len(INSTRUMENTS)} instruments, {len(TIMEFRAMES)} timeframes")

    t0 = time.time()
    summary = run_sweep(
        trials, campaign_id=args.campaign, round_no=args.round, workers=args.workers, root=args.root
    )
    print(f"[sweep] {summary}  wall={time.time() - t0:.1f}s")

    lb = load_leaderboard(args.campaign, round_no=args.round, root=args.root)
    print(f"[leaderboard] {lb.height} rows, statuses: {lb['status'].value_counts().to_dicts()}")


if __name__ == "__main__":
    main()
