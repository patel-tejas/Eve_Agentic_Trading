"""Phase 08 orchestrator: grid search + walk-forward + regime analysis + report.

Usage:
    uv run python scripts/run_research.py --year 2026 --month 7
    uv run python scripts/run_research.py --year 2026 --month 7 --timeframes 5,15

Outputs under data/results/futures/NIFTY/<year>-<month>/research/:
    parameter_search_<tf>.parquet   grid results on the training window
    walk_forward_<tf>.parquet       per-step in-sample/out-of-sample results
    regime_analysis.json            splits, grid, walk-forward, regimes
    robustness_report.md            consolidated markdown report

Note: the 320-combination grid on 1m candles is the slowest; pass
--timeframes 5,15 if you only want the faster runs.
"""

from __future__ import annotations

import argparse
import json
from pathlib import Path

import polars as pl

from quant.backtest.costs import CostConfig
from quant.backtest.engine import BacktestConfig, run_backtest
from quant.backtest.execution import ExecutionConfig
from quant.research.baseline import BASELINE_SLIPPAGE
from quant.research.parameter_search import parameter_grid_search, split_schedule
from quant.research.regime import analyse_regimes
from quant.research.report import render_robustness_report
from quant.research.walk_forward import walk_forward
from quant.strategies.ema_9_15 import StrategyConfig, generate_signals


def run_research(
    *,
    year: int,
    month: int,
    processed_root: str | Path = "data/processed/futures/NIFTY",
    results_root: str | Path = "data/results/futures/NIFTY",
    timeframes: tuple[int, ...] = (5, 15),
    grid: dict[str, tuple[int | float, ...]] | None = None,
) -> dict[str, object]:
    """Run the phase-08 research toolkit for a processed month."""
    processed_month = Path(processed_root) / f"{year:04d}-{month:02d}"
    results_month = Path(results_root) / f"{year:04d}-{month:02d}"
    research_dir = results_month / "research"
    research_dir.mkdir(parents=True, exist_ok=True)

    cfg = BacktestConfig(
        costs=CostConfig(),
        execution=ExecutionConfig(slippage=BASELINE_SLIPPAGE),
    )
    summary: dict[str, object] = {
        "period": f"{year:04d}-{month:02d}",
        "timeframes": {},
    }
    existing = research_dir / "regime_analysis.json"
    if existing.exists():
        summary["timeframes"] = json.loads(existing.read_text(encoding="utf-8"))[
            "timeframes"
        ]

    for tf in timeframes:
        tf_label = f"{tf}m"
        print(f"[research] {tf_label}: loading candles ...")
        candles = pl.read_parquet(processed_month / tf_label / "candles.parquet")

        splits = split_schedule(candles)
        print(f"[research] {tf_label}: grid search on train window ...")
        grid_df = parameter_grid_search(
            candles, window=splits["train"], backtest_config=cfg, grid=grid
        )
        grid_df.write_parquet(research_dir / f"parameter_search_{tf_label}.parquet")

        print(f"[research] {tf_label}: walk-forward ...")
        wf_steps = walk_forward(candles, backtest_config=cfg, grid=grid)
        wf_df = pl.DataFrame([s.to_row() for s in wf_steps])
        wf_df.write_parquet(research_dir / f"walk_forward_{tf_label}.parquet")

        print(f"[research] {tf_label}: regime analysis (B-config full month) ...")
        signals = generate_signals(candles, config=StrategyConfig())
        backtest = run_backtest(candles, signals, cfg)
        regimes = analyse_regimes(candles, backtest.trades)

        grid_top = grid_df.head(1).to_dicts()[0]
        summary["timeframes"][tf_label] = {
            "splits": {
                name: (start.isoformat(), end.isoformat())
                for name, (start, end) in splits.items()
            },
            "grid_search": {
                "combinations": grid_df.height,
                "positive_share": float(
                    (grid_df["net_pnl"] > 0).sum() / grid_df.height
                ),
                "median_net_pnl": float(grid_df["net_pnl"].median()),
                "best": {
                    "params": {
                        k: grid_top[k]
                        for k in ("fast_ema", "slow_ema", "angle_threshold", "angle_lookback")
                    },
                    "net_pnl": grid_top["net_pnl"],
                    "total_trades": grid_top["total_trades"],
                    "profit_factor": grid_top["profit_factor"],
                },
            },
            "walk_forward": wf_df.to_dicts(),
            "regimes": [r.to_dict() for r in regimes],
        }

    (research_dir / "regime_analysis.json").write_text(
        json.dumps(summary, indent=2, default=str), encoding="utf-8"
    )
    report_path = research_dir / "robustness_report.md"
    report_path.write_text(render_robustness_report(summary), encoding="utf-8")
    print(f"[research] report -> {report_path}")
    return summary


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--year", type=int, required=True)
    parser.add_argument("--month", type=int, required=True)
    parser.add_argument("--timeframes", default="5,15")
    args = parser.parse_args()
    timeframes = tuple(int(x) for x in args.timeframes.split(",") if x.strip())
    summary = run_research(year=args.year, month=args.month, timeframes=timeframes)
    for tf_label, info in summary["timeframes"].items():
        best = info["grid_search"]["best"]
        print(
            f"[research] {tf_label}: best {best['params']} -> "
            f"net {best['net_pnl']:,.0f} on the training window"
        )


if __name__ == "__main__":
    main()
