"""Golden workflow (Phase 07 evals): the full research chain for July 2026.

Regression test against the documented July baseline numbers. Every step
uses the same public APIs the MCP tools wrap, so a green run means the
agent's "backtest July and compare timeframes" workflow returns stable,
reproducible numbers.

Usage:
    uv run python agent/evals/golden_workflow.py
"""

from __future__ import annotations

import sys
from pathlib import Path

import polars as pl

from quant.backtest.costs import CostConfig
from quant.backtest.engine import BacktestConfig, run_backtest
from quant.backtest.execution import ExecutionConfig
from quant.processing.pipeline import process_month
from quant.research.baseline import BASELINE_SLIPPAGE, comparison_table, run_baseline
from quant.research.parameter_search import parameter_grid_search, split_schedule
from quant.strategies.ema_9_15 import StrategyConfig, generate_signals

YEAR, MONTH = 2026, 7
ROOT = Path(__file__).resolve().parents[2]
RAW = ROOT / "data" / "raw" / "futures" / "NIFTY"
PROCESSED = ROOT / "data" / "processed" / "futures" / "NIFTY"
RESULTS = ROOT / "data" / "results" / "futures" / "NIFTY"

failures: list[str] = []


def check(name: str, condition: bool, actual: object) -> None:
    if condition:
        print(f"  [PASS] {name}")
    else:
        failures.append(name)
        print(f"  [FAIL] {name} -> actual: {actual}")


def main() -> int:
    print(f"Step 1: raw data present ({YEAR}-{MONTH:02d})")
    raw_path = RAW / f"{YEAR:04d}-{MONTH:02d}" / "candles_1m.parquet"
    check("raw candles exist", raw_path.exists(), raw_path)

    print("Step 2: validate + process month (idempotent pipeline)")
    processed = process_month(
        year=YEAR, month=MONTH, raw_root=RAW, processed_root=PROCESSED
    )
    check(
        "validation passes (pass/pass_with_warnings)",
        processed["validation"] in ("pass", "pass_with_warnings"),
        processed["validation"],
    )
    check("verification passes", processed["verification"] == {"5m": "pass", "15m": "pass"},
          processed["verification"])

    cfg = BacktestConfig(
        costs=CostConfig(),
        execution=ExecutionConfig(slippage=BASELINE_SLIPPAGE),
    )

    print("Step 3: B-config backtests (defaults 9/15/30)")
    expectations = {
        "1m": {"trades": 2, "net_pnl": -18_672},
        "5m": {"trades": 4, "net_pnl": -20_225},
        "15m": {"trades": 4, "net_pnl": 5_737},
    }
    for tf, expected in expectations.items():
        candles = pl.read_parquet(PROCESSED / f"{YEAR:04d}-{MONTH:02d}" / tf / "candles.parquet")
        signals = generate_signals(candles, config=StrategyConfig())
        result = run_backtest(candles, signals, cfg)
        check(
            f"B {tf} trades == {expected['trades']}",
            result.metrics["total_trades"] == expected["trades"],
            result.metrics["total_trades"],
        )
        check(
            f"B {tf} net_pnl == {expected['net_pnl']}",
            abs(result.metrics["net_pnl"] - expected["net_pnl"]) < 1.0,
            result.metrics["net_pnl"],
        )

    print("Step 4: baseline comparison (A/B/C x 1m/5m/15m)")
    experiments = run_baseline(
        year=YEAR, month=MONTH, processed_root=PROCESSED, results_root=RESULTS
    )
    table = comparison_table(experiments)
    check("comparison covers A/B/C", set(table) == {"A", "B", "C"}, set(table))
    check("15m B profitable", table["B"]["15m"]["net_pnl"] > 0, table["B"]["15m"]["net_pnl"])
    check("9 experiments (3 variants x 3 tfs)", len(experiments) == 9, len(experiments))

    print("Step 5: grid search still trains on July 1-23 only")
    candles = pl.read_parquet(PROCESSED / f"{YEAR:04d}-{MONTH:02d}" / "5m" / "candles.parquet")
    train = split_schedule(candles)["train"]
    check("train window starts July 1", train[0].day == 1, train[0])
    check("train window ends July 23", train[1].day == 24, train[1])
    grid = parameter_grid_search(candles, window=train, backtest_config=cfg)
    check("grid = 320 combos", grid.height == 320, grid.height)
    best = grid.head(1).to_dicts()[0]
    check(
        "grid best matches phase-08 doc (5m)",
        (best["fast_ema"], best["slow_ema"]) == (7, 21),
        (best["fast_ema"], best["slow_ema"]),
    )

    print()
    if failures:
        print(f"Golden workflow FAILED: {failures}")
        return 1
    print("Golden workflow PASSED — numbers reproducible.")
    return 0


if __name__ == "__main__":
    sys.exit(main())
