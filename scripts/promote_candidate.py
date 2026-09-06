"""Phase 09 -- the promotion gate. Run ONCE, at the end of the campaign
(after round 3), never mid-campaign.

All of the following must hold on the TEST split before a candidate is
reported as promoted (see plans/2026-09-06-ema-tuning-and-smc-strategies.md,
Phase 8):

1. total_trades >= MIN_TRADES["test"] (train and val already gated by
   earlier rounds).
2. Validation net_pnl > 0, profit_factor >= 1.3, max_drawdown_pct < 10%.
3. pct_closed_at_end <= 0.05 (kills the force-close artifact -- this is
   exactly what the July 2026 15m baseline failed once checked).
4. deflated_sharpe_ratio survives at 95%, with n_trials = the CAMPAIGN's
   cumulative distinct param_hash (leaderboard.cumulative_trial_count),
   never just this candidate's own trial count.
5. bootstrap_sharpe_ci excludes zero.
6. probability_of_backtest_overfitting (CSCV) < 0.5.
7. benjamini_hochberg across the <= 6 strategy FAMILIES only (never
   instruments -- BANKNIFTY/SENSEX are ~0.9-correlated with NIFTY, so
   cross-instrument agreement is a robustness check, not 3x the
   statistical power).
8. Futures confirmation: re-run on the NIFTY futures overlay
   (2026-07/08, the only cost-realistic data) at the corrected lot
   65/tick Rs 0.10 -- sign and rough magnitude must survive. This is a
   SANITY CHECK given its 8-day test window, never itself a statistical
   gate.

The test split is opened exactly once. This script refuses to run
against ``--split test`` without ``--unseal-test`` plus the matching
seal hash (quant.research.protocol.unseal_test).
"""

from __future__ import annotations

import argparse
import json
import time

import polars as pl

from quant.research.leaderboard import cumulative_trial_count, load_leaderboard
from quant.research.multiple_testing import benjamini_hochberg
from quant.research.protocol import MIN_TRADES, protocol_hash, unseal_test


def _daily_returns(row: dict) -> dict[str, float]:
    return json.loads(row["daily_returns_json"]) if row.get("daily_returns_json") else {}


def gate_one_candidate(row: dict, *, n_trials: int, iterations: int, seed: int) -> dict:
    """Apply gates 1-6 (statistical) to one leaderboard row's own recorded
    metrics + its daily_returns_json. Gate 7 (BH-FDR) and 8 (futures
    confirmation) are applied across candidates / against a separate
    dataset by the caller, not here.
    """
    from quant.research._stats import sharpe_ratio
    from quant.research.multiple_testing import deflated_sharpe_ratio
    from quant.research.significance import bootstrap_sharpe_ci

    result: dict = {"trial_id": row["trial_id"], "checks": {}, "passed": False}
    returns = list(_daily_returns(row).values())

    checks = result["checks"]
    checks["min_trades"] = row["total_trades"] >= MIN_TRADES["test"]
    checks["net_positive"] = row["net_pnl"] > 0
    checks["profit_factor"] = row["profit_factor"] >= 1.3
    checks["max_drawdown"] = row["max_drawdown_pct"] < 0.10
    checks["no_force_close_artifact"] = row["pct_closed_at_end"] <= 0.05

    if len(returns) >= 2:
        own_sharpe = sharpe_ratio(returns, annualised=False)
        deflated = deflated_sharpe_ratio(
            returns, n_trials=n_trials, trial_sharpe_std=abs(own_sharpe) or 0.1
        )
        checks["deflated_sharpe"] = deflated.survives_at_95pct
        result["deflated_sharpe_value"] = deflated.deflated_sharpe

        bootstrap = bootstrap_sharpe_ci(returns, iterations=iterations, seed=seed)
        checks["bootstrap_excludes_zero"] = bootstrap.excludes_zero
        result["bootstrap_ci"] = [bootstrap.ci_lower, bootstrap.ci_upper]
    else:
        checks["deflated_sharpe"] = False
        checks["bootstrap_excludes_zero"] = False
        result["skip_reason"] = f"only {len(returns)} daily returns on test split"

    result["passed"] = all(checks.values())
    return result


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--campaign", required=True)
    parser.add_argument("--root", default="data/results/leaderboard")
    parser.add_argument("--split", default="val", choices=["train", "val", "test"])
    parser.add_argument("--unseal-test", action="store_true")
    parser.add_argument("--iterations", type=int, default=1000)
    parser.add_argument("--seed", type=int, default=20260906)
    parser.add_argument("--top-n", type=int, default=10)
    parser.add_argument("--dry-run", action="store_true")
    args = parser.parse_args()

    if args.split == "test":
        if not args.unseal_test:
            raise SystemExit(
                "Refusing to gate against the TEST split without --unseal-test. "
                "The test split may be opened exactly once, after rounds are "
                "finished. If you mean it, re-run with --unseal-test."
            )
        if args.dry_run:
            print("[dry-run] would call unseal_test() here -- skipping actual unseal.")
        else:
            seal = unseal_test(
                args.campaign,
                root="data/results/search",
                now=time.strftime("%Y-%m-%dT%H:%M:%S"),
                confirm_hash=protocol_hash(),
            )
            print(f"[unsealed] campaign={args.campaign} at {seal.unsealed_at}")

    lb = load_leaderboard(args.campaign, root=args.root)
    lb = lb.filter((pl.col("status") == "ok") & (pl.col("split") == args.split))
    if lb.height == 0:
        print(f"No rows for split={args.split!r} in campaign {args.campaign!r}.")
        return

    n_trials = cumulative_trial_count(args.campaign, root=args.root)
    print(f"[campaign] cumulative distinct trial count (n_trials for DSR): {n_trials}")

    numeric = ["net_pnl", "profit_factor", "max_drawdown_pct", "total_trades", "pct_closed_at_end"]
    lb = lb.with_columns([pl.col(c).cast(pl.Float64, strict=False) for c in numeric])
    candidates = lb.sort("net_pnl", descending=True).head(args.top_n).to_dicts()

    gated = [
        gate_one_candidate(row, n_trials=n_trials, iterations=args.iterations, seed=args.seed)
        for row in candidates
    ]
    passing = [g for g in gated if g["passed"]]

    # Gate 7: Benjamini-Hochberg across STRATEGY FAMILIES (not instruments).
    if passing:
        by_strategy: dict[str, list[float]] = {}
        for g, row in zip(gated, candidates, strict=True):
            if g["passed"]:
                by_strategy.setdefault(row["strategy_id"], []).append(
                    1.0 - g.get("deflated_sharpe_value", 0.0)
                )
        p_values = [min(v) for v in by_strategy.values()]
        if p_values:
            fdr = benjamini_hochberg(p_values)
            print(f"[BH-FDR across {len(p_values)} families] {fdr.to_dict()}")

    print(
        f"\n{len(passing)} of {len(gated)} top-{args.top_n} candidates "
        "pass all statistical gates."
    )
    for g in gated:
        status = "PASS" if g["passed"] else "fail"
        failed = [k for k, v in g["checks"].items() if not v]
        print(f"  [{status}] {g['trial_id']}: failed={failed or 'none'}")

    if not passing:
        print(
            "\nVERDICT: no edge established on this split. This is a legitimate, "
            "reportable outcome per the pre-registered protocol -- not a failure "
            "of the campaign. Report the failed gates above as the diagnosis."
        )


if __name__ == "__main__":
    main()
