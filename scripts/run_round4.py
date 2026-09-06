"""Phase 11 -- Round 5 (script name kept as "round4" for the HA-pattern
variant's own internal stage numbering; round_04 in the leaderboard is
already taken by the round-3 final report -- see plans/
2026-09-06-ema-tuning-and-smc-strategies.md and the plan file for this
variant): the HA-pattern-gated EMA entry (``ema_ha``) + scale-out ladder,
staged search, same pre-registered campaign (``C2026-09-EMA-SMC``) and
protocol as every other family -- adding a new family only RAISES the
deflated-Sharpe bar (more cumulative trials searched), never lowers it.

Three stages, same discipline as round 2's:

Stage 1 (train): full cartesian over ema_ha's entry-logic param_space
(fast/slow EMA, pattern_window_bars, pattern_set, doji_body_pct,
wick_ratio, small_range_atr, slope_threshold_atr), fixed at a reasonable
ladder (1R/50%, 2R/25%, trail the runner at the previous candle's low
once 2 legs have filled) and position_size=4 lots (so 50/25/25 lands on
exact 2/1/1 lots). Selects the top-K distinct entries per (symbol, tf)
cell by train net_pnl.

Stage 2 (train): for each Stage-1 survivor, LHS-sample the ladder +
structural-stop grid (leg sizes/thresholds, breakeven-after-leg-1, trail
gating, stop anchor/reference/buffer) -- this is the "fine-tune the
quantity numbers by backtesting" part of the ask.

Stage 3 (train): +/-1 grid step around each Stage-2 winner's numeric
axes.

Then: each (symbol, timeframe) cell's single best Stage-3 config is
scored ONCE on the untouched 2025 VALIDATION split, gated via the same
statistical machinery as round 3, and reported side by side against the
incumbent ``ema`` family's own round-3 validation numbers (pulled from
round_04 of this same leaderboard) so it is directly visible whether the
HA gate beat the plain crossover.

The TEST split (2026) is not touched by this script.

Invoke as a module (``python -m scripts.run_round4``), not as a bare
script path -- same reason as run_round2.py/run_round3.py.
"""

from __future__ import annotations

import argparse
import json
import time

import polars as pl

import quant.strategies.ema_ha_pattern  # noqa: F401
from quant.data.index_spot import resolve_contract_specs
from quant.data.upstox import UpstoxClient
from quant.research.leaderboard import cumulative_trial_count, load_leaderboard
from quant.research.protocol import DISCOVERY_SPLITS
from quant.research.sampling import (
    canonical_exits,
    canonical_params,
    dedupe_by_effect,
    full_combinations,
    local_refinement,
    sample_combinations,
)
from quant.research.sweep import Trial, run_sweep
from quant.strategies.base import STRATEGY_REGISTRY
from scripts.promote_candidate import gate_one_candidate
from scripts.run_round1 import INSTRUMENTS, TIMEFRAMES, candles_path

STRATEGY_ID = "ema_ha"
POSITION_SIZE = 4  # lots -- makes 50/25/25 exact (2/1/1 lots)
INITIAL_CAPITAL = 4_000_000.0  # Rs 40L = Rs 10L x 4, keeps maxDD% comparable to 1-lot campaign
MIN_TRAIN_TRADES_FOR_SELECTION = 10
TOP_K_STAGE1 = 6
STAGE2_SAMPLE_N = 128
STAGE3_RADIUS = 1

# Stage 1's fixed ladder: 50% at 1R, 25% at 2R, trail the last 25% at the
# previous candle's low once both legs have filled. Structural stop
# (stop_mode="signal") comes from the strategy itself.
STAGE1_FIXED_EXIT = {
    "stop_mode": "signal",
    "scale_out": [{"at_r": 1.0, "fraction": 0.50}, {"at_r": 2.0, "fraction": 0.25}],
    "trail_mode": "prev_candle_extreme",
    "trail_after_leg": 2,
    "trail_buffer_atr": 0.0,
    "after_leg1_stop": "keep",
    "eod_squareoff": "15:15",  # 15:15, not 15:20 -- see quant/backtest/exits.py
}

# Stage 2: structural-stop params (belong to the STRATEGY's own param
# space, like every SMC strategy's stop_buffer_atr) + the ladder/trail
# params (belong to ExitConfig). Sampled together via one LHS draw so the
# two are jointly explored rather than nested loops.
STAGE2_GRID: dict[str, tuple] = {
    "stop_anchor": ("pattern_bar", "signal_bar"),
    "stop_reference": ("real", "ha"),
    "stop_buffer_atr": (0.0, 0.10, 0.25),
    "leg1_at_r": (0.8, 1.0, 1.2),
    "leg1_frac": (0.25, 0.50, 0.75),
    "leg2_at_r": (1.5, 2.0, 3.0),
    "leg2_frac": (0.0, 0.25),
    "after_leg1_stop": ("keep", "breakeven"),
    "trail_after_leg": (1, 2),
    "trail_buffer_atr": (0.0, 0.15),
}
STAGE3_NUMERIC_AXES = {
    "stop_buffer_atr": (0.0, 0.10, 0.25),
    "leg1_at_r": (0.8, 1.0, 1.2),
    "leg1_frac": (0.25, 0.50, 0.75),
    "leg2_at_r": (1.5, 2.0, 3.0),
    "trail_buffer_atr": (0.0, 0.15),
}


def _numify(frame: pl.DataFrame) -> pl.DataFrame:
    cols = ["net_pnl", "profit_factor", "max_drawdown_pct", "total_trades", "pct_closed_at_end"]
    return frame.with_columns([pl.col(c).cast(pl.Float64, strict=False) for c in cols])


def _exit_config_from_ladder(sampled: dict) -> dict:
    """Split one Stage-2/3 sampled dict into (strategy stop params,
    ExitConfig dict). ``leg2_frac=0.0`` collapses the ladder to a single
    leg (50% is more than the plan's minimum, but the sample space keeps
    it a free variable rather than a shipped assumption)."""
    legs = [{"at_r": sampled["leg1_at_r"], "fraction": sampled["leg1_frac"]}]
    if sampled["leg2_frac"] > 0.0:
        legs.append({"at_r": sampled["leg2_at_r"], "fraction": sampled["leg2_frac"]})
    exits = {
        "stop_mode": "signal",
        "scale_out": legs,
        "trail_mode": "prev_candle_extreme",
        "trail_after_leg": sampled["trail_after_leg"],
        "trail_buffer_atr": sampled["trail_buffer_atr"],
        "after_leg1_stop": sampled["after_leg1_stop"],
        "eod_squareoff": "15:15",
    }
    strategy_overrides = {
        "stop_anchor": sampled["stop_anchor"],
        "stop_reference": sampled["stop_reference"],
        "stop_buffer_atr": sampled["stop_buffer_atr"],
    }
    return strategy_overrides, exits


def _make_trial(
    *, campaign_id: str, round_no: int, symbol: str, timeframe: str, split: str,
    params: dict, exits: dict, market: dict, window: tuple[str, str] | None, seed: int,
) -> Trial:
    window_start, window_end = window if window else (None, None)
    return Trial(
        campaign_id=campaign_id,
        round=round_no,
        strategy_id=STRATEGY_ID,
        strategy_version="v1",
        params=params,
        exits=exits,
        symbol=symbol,
        price_source="index_spot_proxy",
        timeframe=timeframe,
        split=split,
        candles_path=candles_path(symbol, timeframe),
        window_start=window_start,
        window_end=window_end,
        lot_size=market["lot_size"],
        tick_size_rupees=market["tick_size"] / 100.0,
        seed=seed,
        position_size=POSITION_SIZE,
        initial_capital=INITIAL_CAPITAL,
    )


def run_stage1(campaign_id: str, round_no: int, seed: int, workers: int, root: str) -> None:
    client = UpstoxClient(require_auth=False)
    specs = {sym: resolve_contract_specs(sym, client=client) for sym in INSTRUMENTS}
    train_start, train_end = DISCOVERY_SPLITS["train"]
    window = (train_start.isoformat(), train_end.isoformat())

    spec = STRATEGY_REGISTRY[STRATEGY_ID]
    combos = full_combinations(
        spec.param_space, constraints=[lambda c: c["fast_ema"] < c["slow_ema"]]
    )
    combos = dedupe_by_effect(STRATEGY_ID, combos)
    print(f"[stage1] {len(combos)} distinct entry-logic combos")

    trials = []
    for symbol in INSTRUMENTS:
        market = specs[symbol]
        for timeframe in TIMEFRAMES:
            for params in combos:
                trials.append(
                    _make_trial(
                        campaign_id=campaign_id, round_no=round_no, symbol=symbol,
                        timeframe=timeframe, split="train", params=params,
                        exits=STAGE1_FIXED_EXIT, market=market, window=window, seed=seed,
                    )
                )
    print(f"[stage1] {len(trials)} trials ({len(INSTRUMENTS)} symbols x {len(TIMEFRAMES)} tf)")
    summary = run_sweep(
        trials, campaign_id=campaign_id, round_no=round_no, workers=workers, root=root
    )
    print(f"[stage1] {summary}")


def top_k_entries_per_cell(
    lb: pl.DataFrame, symbol: str, timeframe: str, k: int
) -> list[dict]:
    cell = lb.filter(
        (pl.col("symbol") == symbol) & (pl.col("timeframe") == timeframe)
    ).sort("net_pnl", descending=True)
    seen: set[tuple] = set()
    out: list[dict] = []
    for row in cell.to_dicts():
        params = json.loads(row["params_json"])
        key = tuple(sorted(canonical_params(STRATEGY_ID, params).items()))
        if key in seen:
            continue
        seen.add(key)
        out.append(params)
        if len(out) >= k:
            break
    return out


def _dedupe_ladder_combos(combos: list[dict]) -> list[dict]:
    """Collapse Stage-2 draws that canonicalise to the same effective
    (structural stop, scale-out ladder) at ``POSITION_SIZE`` lots -- e.g.
    ``leg1_frac=0.30`` and ``0.33`` both floor to 1 lot at 4 lots, and are
    behaviourally identical trials (see ``canonical_exits``)."""
    seen: set[tuple] = set()
    out: list[dict] = []
    for sampled in combos:
        _, exits = _exit_config_from_ladder(sampled)
        canon = canonical_exits(exits, position_size=POSITION_SIZE)
        key = (
            sampled.get("stop_anchor"),
            sampled.get("stop_reference"),
            sampled.get("stop_buffer_atr"),
            tuple(sorted(canon.items())),
        )
        if key in seen:
            continue
        seen.add(key)
        out.append(sampled)
    return out


def run_stage2(
    campaign_id: str, stage1_round: int, round_no: int, seed: int, workers: int, root: str
) -> None:
    r1 = _numify(
        load_leaderboard(campaign_id, round_no=stage1_round, root=root).filter(
            (pl.col("status") == "ok") & (pl.col("strategy_id") == STRATEGY_ID)
        )
    )
    clean = r1.filter(pl.col("total_trades") >= MIN_TRAIN_TRADES_FOR_SELECTION)

    client = UpstoxClient(require_auth=False)
    specs = {sym: resolve_contract_specs(sym, client=client) for sym in INSTRUMENTS}
    train_start, train_end = DISCOVERY_SPLITS["train"]
    window = (train_start.isoformat(), train_end.isoformat())

    ladder_combos = sample_combinations(STAGE2_GRID, n=STAGE2_SAMPLE_N, seed=seed, method="lhs")
    ladder_combos = _dedupe_ladder_combos(ladder_combos)
    print(f"[stage2] {len(ladder_combos)} distinct ladder/stop combos after canonicalisation")

    trials = []
    for symbol in INSTRUMENTS:
        market = specs[symbol]
        for timeframe in TIMEFRAMES:
            entries = top_k_entries_per_cell(clean, symbol, timeframe, TOP_K_STAGE1)
            for entry_params in entries:
                for sampled in ladder_combos:
                    strategy_overrides, exits = _exit_config_from_ladder(sampled)
                    params = {**entry_params, **strategy_overrides}
                    trials.append(
                        _make_trial(
                            campaign_id=campaign_id, round_no=round_no, symbol=symbol,
                            timeframe=timeframe, split="train", params=params, exits=exits,
                            market=market, window=window, seed=seed,
                        )
                    )
    print(f"[stage2] {len(trials)} ladder-tuning trials (train split)")
    summary = run_sweep(
        trials, campaign_id=campaign_id, round_no=round_no, workers=workers, root=root
    )
    print(f"[stage2] {summary}")


def best_stage2_config_per_cell(lb: pl.DataFrame, symbol: str, timeframe: str) -> dict | None:
    cell = lb.filter(
        (pl.col("symbol") == symbol) & (pl.col("timeframe") == timeframe)
    ).sort("net_pnl", descending=True)
    if cell.height == 0:
        return None
    best = cell.row(0, named=True)
    return {
        "params": json.loads(best["params_json"]),
        "exits": json.loads(best["exits_json"]),
        "train_net_pnl": best["net_pnl"],
    }


def run_stage3(
    campaign_id: str, stage2_round: int, round_no: int, seed: int, workers: int, root: str
) -> None:
    r2 = _numify(
        load_leaderboard(campaign_id, round_no=stage2_round, root=root).filter(
            (pl.col("status") == "ok") & (pl.col("strategy_id") == STRATEGY_ID)
        )
    )
    clean = r2.filter(pl.col("total_trades") >= MIN_TRAIN_TRADES_FOR_SELECTION)

    client = UpstoxClient(require_auth=False)
    specs = {sym: resolve_contract_specs(sym, client=client) for sym in INSTRUMENTS}
    train_start, train_end = DISCOVERY_SPLITS["train"]
    window = (train_start.isoformat(), train_end.isoformat())

    trials = []
    for symbol in INSTRUMENTS:
        market = specs[symbol]
        for timeframe in TIMEFRAMES:
            winner = best_stage2_config_per_cell(clean, symbol, timeframe)
            if winner is None:
                continue
            base_ladder = {
                "stop_buffer_atr": winner["params"].get("stop_buffer_atr", 0.0),
                "leg1_at_r": winner["exits"]["scale_out"][0]["at_r"],
                "leg1_frac": winner["exits"]["scale_out"][0]["fraction"],
                "leg2_at_r": (
                    winner["exits"]["scale_out"][1]["at_r"]
                    if len(winner["exits"]["scale_out"]) > 1
                    else STAGE2_GRID["leg2_at_r"][0]
                ),
                "trail_buffer_atr": winner["exits"].get("trail_buffer_atr", 0.0),
            }
            neighbours = local_refinement(
                base_ladder, STAGE3_NUMERIC_AXES, radius=STAGE3_RADIUS
            )
            for neighbour in neighbours:
                sampled = {
                    **neighbour,
                    "stop_anchor": winner["params"].get("stop_anchor", "pattern_bar"),
                    "stop_reference": winner["params"].get("stop_reference", "real"),
                    "leg2_frac": (
                        winner["exits"]["scale_out"][1]["fraction"]
                        if len(winner["exits"]["scale_out"]) > 1
                        else 0.0
                    ),
                    "after_leg1_stop": winner["exits"].get("after_leg1_stop", "keep"),
                    "trail_after_leg": winner["exits"].get("trail_after_leg", 2),
                }
                strategy_overrides, exits = _exit_config_from_ladder(sampled)
                entry_only = {
                    k: v
                    for k, v in winner["params"].items()
                    if k not in ("stop_anchor", "stop_reference", "stop_buffer_atr")
                }
                params = {**entry_only, **strategy_overrides}
                trials.append(
                    _make_trial(
                        campaign_id=campaign_id, round_no=round_no, symbol=symbol,
                        timeframe=timeframe, split="train", params=params, exits=exits,
                        market=market, window=window, seed=seed,
                    )
                )
    print(f"[stage3] {len(trials)} local-refinement trials (train split)")
    summary = run_sweep(
        trials, campaign_id=campaign_id, round_no=round_no, workers=workers, root=root
    )
    print(f"[stage3] {summary}")


def run_validation(
    campaign_id: str, stage3_round: int, round_no: int, seed: int, workers: int, root: str
) -> None:
    r3 = _numify(
        load_leaderboard(campaign_id, round_no=stage3_round, root=root).filter(
            (pl.col("status") == "ok") & (pl.col("strategy_id") == STRATEGY_ID)
        )
    )
    clean = r3.filter(pl.col("total_trades") >= MIN_TRAIN_TRADES_FOR_SELECTION)

    client = UpstoxClient(require_auth=False)
    specs = {sym: resolve_contract_specs(sym, client=client) for sym in INSTRUMENTS}
    val_start, val_end = DISCOVERY_SPLITS["val"]
    window = (val_start.isoformat(), val_end.isoformat())

    trials = []
    for symbol in INSTRUMENTS:
        market = specs[symbol]
        for timeframe in TIMEFRAMES:
            winner = best_stage2_config_per_cell(clean, symbol, timeframe)
            if winner is None:
                print(f"[val] {symbol} {timeframe}: no train-split candidate, skipping")
                continue
            trials.append(
                _make_trial(
                    campaign_id=campaign_id, round_no=round_no, symbol=symbol,
                    timeframe=timeframe, split="val", params=winner["params"],
                    exits=winner["exits"], market=market, window=window, seed=seed,
                )
            )
            print(
                f"[val] {symbol} {timeframe}: carrying train-net={winner['train_net_pnl']:.0f} "
                "config into validation"
            )
    print(f"[val] {len(trials)} validation-split trials")
    summary = run_sweep(
        trials, campaign_id=campaign_id, round_no=round_no, workers=workers, root=root
    )
    print(f"[val] {summary}")


def build_comparison_report(
    campaign_id: str, val_round: int, incumbent_round: int, root: str, *,
    iterations: int, seed: int,
) -> str:
    lb = _numify(
        load_leaderboard(campaign_id, round_no=val_round, root=root).filter(
            (pl.col("status") == "ok") & (pl.col("strategy_id") == STRATEGY_ID)
        )
    )
    incumbent = _numify(
        load_leaderboard(campaign_id, round_no=incumbent_round, root=root).filter(
            (pl.col("status") == "ok") & (pl.col("strategy_id") == "ema")
        )
    )
    n_trials = cumulative_trial_count(campaign_id, root=root)

    lines = [
        f"# ema_ha (HA-pattern-gated EMA + scale-out ladder) -- {campaign_id}",
        "",
        "Each (symbol, timeframe) cell's own TRAIN-split best config "
        "(3-stage search: entry logic, then the scale-out ladder + structural "
        "stop, then local refinement), scored ONCE on the untouched 2025 "
        "VALIDATION split. Position size 4 lots (50/25/25 = 2/1/1 lots exact), "
        f"initial_capital=Rs {INITIAL_CAPITAL:,.0f}. TEST split (2026) untouched.",
        "",
        f"Cumulative distinct trials this campaign has evaluated (the `n_trials` "
        f"deflated Sharpe is penalized against): **{n_trials}**",
        "",
        "## ema_ha -- validation-split results",
        "",
        "| symbol | tf | net_pnl | PF | trades | win_rate | sharpe | maxDD% | gate |",
        "|---|---|---|---|---|---|---|---|---|",
    ]

    for row in lb.sort(["timeframe", "symbol"]).to_dicts():
        gate = gate_one_candidate(row, n_trials=n_trials, iterations=iterations, seed=seed)
        verdict = "PASS" if gate["passed"] else "fail"
        failed = [k for k, v in gate["checks"].items() if not v]
        lines.append(
            f"| {row['symbol']} | {row['timeframe']} | {row['net_pnl']:,.0f} | "
            f"{row['profit_factor']:.2f} | {row['total_trades']:.0f} | "
            f"{row['win_rate']:.2%} | {row['sharpe']:.2f} | {row['max_drawdown_pct']:.2%} | "
            f"{verdict} ({', '.join(failed) if failed else 'none'}) |"
        )

    lines.append("")
    lines.append(
        "## Incumbent `ema` family (round 3's validation results, position_size=1, "
        "for reference -- NOT the same position size, compare net_pnl direction/PF, "
        "not raw rupee magnitude)"
    )
    lines.append("")
    lines.append("| symbol | tf | net_pnl | PF | trades | win_rate |")
    lines.append("|---|---|---|---|---|---|")
    for row in incumbent.sort(["timeframe", "symbol"]).to_dicts():
        lines.append(
            f"| {row['symbol']} | {row['timeframe']} | {row['net_pnl']:,.0f} | "
            f"{row['profit_factor']:.2f} | {row['total_trades']:.0f} | {row['win_rate']:.2%} |"
        )

    n_ema_ha_rows = lb.height
    n_passing = sum(
        1
        for row in lb.to_dicts()
        if gate_one_candidate(row, n_trials=n_trials, iterations=iterations, seed=seed)["passed"]
    )
    lines.append("")
    lines.append(
        f"## Verdict: {n_passing} of {n_ema_ha_rows} ema_ha (symbol, timeframe) cells "
        "pass the full statistical gate (deflated Sharpe survives at 95%, bootstrap CI "
        "excludes zero, PF>=1.3, maxDD<10%, no force-close artifact) on the validation split."
    )
    if n_passing == 0:
        lines.append("")
        lines.append(
            "**No ema_ha candidate is statistically credible on this protocol.** "
            "The table above ranks cells by raw validation-split performance for "
            "comparison, but none of these numbers demonstrate an edge -- see the "
            "per-row `gate` column. TEST split remains sealed."
        )

    return "\n".join(lines) + "\n"


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--campaign", default="C2026-09-EMA-SMC")
    parser.add_argument("--stage1-round", type=int, default=5)
    parser.add_argument("--stage2-round", type=int, default=6)
    parser.add_argument("--stage3-round", type=int, default=7)
    parser.add_argument("--val-round", type=int, default=8)
    parser.add_argument("--incumbent-round", type=int, default=4)
    parser.add_argument("--workers", type=int, default=14)
    parser.add_argument("--seed", type=int, default=45)
    parser.add_argument("--root", default="data/results/leaderboard")
    parser.add_argument("--iterations", type=int, default=1000)
    parser.add_argument(
        "--stage", choices=["1", "2", "3", "val", "report", "all"], default="all"
    )
    parser.add_argument("--out", default=None)
    args = parser.parse_args()

    t0 = time.time()
    if args.stage in ("1", "all"):
        run_stage1(args.campaign, args.stage1_round, args.seed, args.workers, args.root)
    if args.stage in ("2", "all"):
        run_stage2(
            args.campaign, args.stage1_round, args.stage2_round, args.seed, args.workers,
            args.root,
        )
    if args.stage in ("3", "all"):
        run_stage3(
            args.campaign, args.stage2_round, args.stage3_round, args.seed, args.workers,
            args.root,
        )
    if args.stage in ("val", "all"):
        run_validation(
            args.campaign, args.stage3_round, args.val_round, args.seed, args.workers, args.root
        )
    if args.stage in ("report", "all"):
        report = build_comparison_report(
            args.campaign, args.val_round, args.incumbent_round, args.root,
            iterations=args.iterations, seed=args.seed,
        )
        out_path = args.out or f"{args.root}/{args.campaign}/EMA_HA_REPORT.md"
        with open(out_path, "w", encoding="utf-8") as f:
            f.write(report)
        print(f"[report] wrote {out_path}")

    print(f"[round4] total wall={time.time() - t0:.1f}s")


if __name__ == "__main__":
    main()
