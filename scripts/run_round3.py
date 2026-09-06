"""Phase 09 -- Round 3: comprehensive, FAIR validation-split comparison
of every strategy on every timeframe, plus the final report.

Unlike round 2 (which only carried forward a narrowed subset -- top-6
EMA entries on 15m only, top-5 per SMC cell), round 3 answers "which
strategy is best on which timeframe" fairly: for ALL 6 strategies x 3
instruments x 2 timeframes (36 cells), take that cell's own TRAIN-split
best config (round 1's leaderboard) and score it ONCE on the untouched
2025 VALIDATION split. No cell is excluded for looking weak elsewhere.

Also runs the formal statistical gate (deflated Sharpe, bootstrap CI) on
every one of the 36 validation results and writes the final comparison
report: `data/results/leaderboard/<campaign>/FINAL_REPORT.md`.

The TEST split (2026) is not touched by this script.
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
from quant.research.leaderboard import cumulative_trial_count, load_leaderboard
from quant.research.protocol import DISCOVERY_SPLITS
from quant.research.sweep import Trial, run_sweep
from quant.strategies.base import STRATEGY_REGISTRY
from scripts.promote_candidate import gate_one_candidate
from scripts.run_round1 import INSTRUMENTS, TIMEFRAMES, candles_path

MIN_TRAIN_TRADES_FOR_SELECTION = 10  # avoid literally-degenerate winners


def _numify(frame: pl.DataFrame) -> pl.DataFrame:
    cols = ["net_pnl", "profit_factor", "max_drawdown_pct", "total_trades", "pct_closed_at_end"]
    return frame.with_columns([pl.col(c).cast(pl.Float64, strict=False) for c in cols])


def best_train_config_per_cell(round1_lb: pl.DataFrame) -> list[dict]:
    """One row per (strategy, symbol, timeframe): the train-split
    best-by-net_pnl config with at least MIN_TRAIN_TRADES_FOR_SELECTION
    trades. Every strategy x instrument x timeframe combination is
    included -- nothing is dropped for looking weak elsewhere, unlike
    round 2's narrower carry-forward."""
    clean = round1_lb.filter(pl.col("total_trades") >= MIN_TRAIN_TRADES_FOR_SELECTION)
    out = []
    for strategy_id in STRATEGY_REGISTRY:
        for symbol in INSTRUMENTS:
            for timeframe in TIMEFRAMES:
                cell = clean.filter(
                    (pl.col("strategy_id") == strategy_id)
                    & (pl.col("symbol") == symbol)
                    & (pl.col("timeframe") == timeframe)
                ).sort("net_pnl", descending=True)
                if cell.height == 0:
                    continue
                best = cell.row(0, named=True)
                out.append(
                    {
                        "strategy_id": strategy_id,
                        "symbol": symbol,
                        "timeframe": timeframe,
                        "params": json.loads(best["params_json"]),
                        "exits": json.loads(best["exits_json"]),
                        "train_net_pnl": best["net_pnl"],
                        "train_trades": best["total_trades"],
                    }
                )
    return out


def run_validation_sweep(
    campaign_id: str, round_no: int, seed: int, workers: int, root: str
) -> None:
    r1 = _numify(
        load_leaderboard(campaign_id, round_no=1, root=root).filter(pl.col("status") == "ok")
    )
    winners = best_train_config_per_cell(r1)
    n_possible = len(STRATEGY_REGISTRY) * len(INSTRUMENTS) * len(TIMEFRAMES)
    print(
        f"[round3] {len(winners)} of {n_possible} (strategy, symbol, timeframe) "
        "cells have a train-split candidate"
    )

    client = UpstoxClient(require_auth=False)
    specs = {sym: resolve_contract_specs(sym, client=client) for sym in INSTRUMENTS}
    val_start, val_end = DISCOVERY_SPLITS["val"]

    trials = []
    for w in winners:
        market = specs[w["symbol"]]
        trials.append(
            Trial(
                campaign_id=campaign_id,
                round=round_no,
                strategy_id=w["strategy_id"],
                strategy_version="v1",
                params=w["params"],
                exits=w["exits"],
                symbol=w["symbol"],
                price_source="index_spot_proxy",
                timeframe=w["timeframe"],
                split="val",
                candles_path=candles_path(w["symbol"], w["timeframe"]),
                window_start=val_start.isoformat(),
                window_end=val_end.isoformat(),
                lot_size=market["lot_size"],
                tick_size_rupees=market["tick_size"] / 100.0,
                seed=seed,
            )
        )

    summary = run_sweep(
        trials, campaign_id=campaign_id, round_no=round_no, workers=workers, root=root
    )
    print(f"[round3] validation sweep: {summary}")


def build_final_report(
    campaign_id: str, round_no: int, root: str, *, iterations: int, seed: int
) -> str:
    lb = _numify(
        load_leaderboard(campaign_id, round_no=round_no, root=root).filter(
            pl.col("status") == "ok"
        )
    )
    n_trials = cumulative_trial_count(campaign_id, root=root)

    lines = [
        f"# Final report -- {campaign_id}",
        "",
        "Every strategy, every timeframe, each instrument's own TRAIN-split best "
        "config, scored ONCE on the untouched 2025 VALIDATION year "
        "(`DISCOVERY_SPLITS['val']`). The TEST split (2026) has not been touched.",
        "",
        f"Cumulative distinct trials this campaign has evaluated (the `n_trials` "
        f"deflated Sharpe is penalized against): **{n_trials}**",
        "",
        "## Per (strategy, symbol, timeframe) -- validation-split results",
        "",
        "| strategy | symbol | tf | net_pnl | PF | trades | win_rate | sharpe | maxDD% "
        "| gate |",
        "|---|---|---|---|---|---|---|---|---|---|",
    ]

    gate_results = {}
    for row in lb.sort(["strategy_id", "timeframe", "symbol"]).to_dicts():
        gate = gate_one_candidate(row, n_trials=n_trials, iterations=iterations, seed=seed)
        gate_results[row["trial_id"]] = gate
        verdict = "PASS" if gate["passed"] else "fail"
        lines.append(
            f"| {row['strategy_id']} | {row['symbol']} | {row['timeframe']} | "
            f"{row['net_pnl']:,.0f} | {row['profit_factor']:.2f} | "
            f"{row['total_trades']:.0f} | {row['win_rate']:.2%} | {row['sharpe']:.2f} | "
            f"{row['max_drawdown_pct']:.2%} | {verdict} |"
        )

    lines.append("")
    lines.append(
        "## Best strategy per timeframe (validation-split net_pnl, averaged "
        "across instruments)"
    )
    lines.append("")
    lines.append(
        "| timeframe | strategy | avg net_pnl | avg PF | avg trades | cells passing gate |"
    )
    lines.append("|---|---|---|---|---|---|")

    passing_ids = {tid for tid, g in gate_results.items() if g["passed"]}
    lb_gate = lb.with_columns(
        pl.col("trial_id").is_in(list(passing_ids)).alias("gate_pass")
    )
    for timeframe in TIMEFRAMES:
        tf_frame = lb_gate.filter(pl.col("timeframe") == timeframe)
        agg = (
            tf_frame.group_by("strategy_id")
            .agg(
                pl.col("net_pnl").mean().alias("avg_net"),
                pl.col("profit_factor").mean().alias("avg_pf"),
                pl.col("total_trades").mean().alias("avg_trades"),
                pl.col("gate_pass").sum().alias("n_pass"),
                pl.len().alias("n_cells"),
            )
            .sort("avg_net", descending=True)
        )
        for i, row in enumerate(agg.to_dicts()):
            marker = " <-- BEST" if i == 0 else ""
            lines.append(
                f"| {timeframe} | {row['strategy_id']} | {row['avg_net']:,.0f} | "
                f"{row['avg_pf']:.2f} | {row['avg_trades']:.0f} | "
                f"{row['n_pass']}/{row['n_cells']}{marker} |"
            )

    n_passing = len(passing_ids)
    lines.append("")
    lines.append(
        f"## Overall verdict: {n_passing} of {lb.height} (strategy, symbol, timeframe) "
        "cells pass the full statistical gate (deflated Sharpe survives at 95%, "
        "bootstrap CI excludes zero) on the validation split."
    )
    if n_passing == 0:
        lines.append("")
        lines.append(
            "**No candidate is statistically credible on this protocol.** The "
            "table above ranks strategies by raw validation-split performance "
            "for comparison purposes, but none of these numbers should be read "
            "as a demonstrated edge -- see the per-row `gate` column. This is "
            "the honest, pre-registered outcome the campaign was built to "
            "report either way; the TEST split remains sealed and untouched."
        )

    return "\n".join(lines) + "\n"


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--campaign", default="C2026-09-EMA-SMC")
    parser.add_argument("--round", type=int, default=4)
    parser.add_argument("--workers", type=int, default=14)
    parser.add_argument("--seed", type=int, default=44)
    parser.add_argument("--root", default="data/results/leaderboard")
    parser.add_argument("--iterations", type=int, default=1000)
    parser.add_argument("--skip-sweep", action="store_true")
    parser.add_argument("--out", default=None)
    args = parser.parse_args()

    t0 = time.time()
    if not args.skip_sweep:
        run_validation_sweep(
            args.campaign, round_no=args.round, seed=args.seed, workers=args.workers, root=args.root
        )

    report = build_final_report(
        args.campaign, args.round, args.root, iterations=args.iterations, seed=args.seed
    )
    out_path = args.out or f"{args.root}/{args.campaign}/FINAL_REPORT.md"
    with open(out_path, "w", encoding="utf-8") as f:
        f.write(report)
    print(f"[round3] wrote {out_path}")
    print(f"[round3] total wall={time.time() - t0:.1f}s")


if __name__ == "__main__":
    main()
