"""Phase 06: run the three-variant baseline across timeframes.

Usage:
    uv run python scripts/run_baseline.py --year 2026 --month 7

Writes baseline_comparison.json + baseline_report.md into the results
month directory, plus per-experiment trade logs under baseline/.
"""

from __future__ import annotations

import argparse

from quant.research.baseline import run_baseline, write_baseline_outputs


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--year", type=int, required=True)
    parser.add_argument("--month", type=int, required=True)
    parser.add_argument("--timeframes", default="1,5,15")
    parser.add_argument("--angle-threshold", type=float, default=30.0)
    args = parser.parse_args()

    tfs = tuple(int(x) for x in args.timeframes.split(",") if x.strip())
    experiments = run_baseline(
        year=args.year,
        month=args.month,
        timeframes=tfs,
        angle_threshold=args.angle_threshold,
    )
    report_path = write_baseline_outputs(experiments, year=args.year, month=args.month)

    print(f"{len(experiments)} experiments -> {report_path}")
    for exp in experiments:
        m = exp.result.metrics
        print(
            f"{exp.experiment_id} {exp.variant} {exp.timeframe}: "
            f"{m['total_trades']} trades, net {m['net_pnl']:,.0f}, "
            f"win {m['win_rate']:.0%}, PF {m['profit_factor']:.2f}, "
            f"maxDD {m['max_drawdown_pct']:.1%}"
        )


if __name__ == "__main__":
    main()
