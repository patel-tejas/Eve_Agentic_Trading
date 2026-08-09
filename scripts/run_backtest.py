"""Phase 05: run the backtest over a processed month for every timeframe.

Reads processed candles + phase-04 signals, executes the baseline
configuration, and stores per timeframe:
    data/results/futures/NIFTY/<year>-<month>/trades_<tf>m.parquet
    data/results/futures/NIFTY/<year>-<month>/metrics_<tf>m.json
    data/results/futures/NIFTY/<year>-<month>/equity_<tf>m.parquet
"""

from __future__ import annotations

import argparse
import json
from pathlib import Path

import polars as pl

from quant.backtest.engine import BacktestConfig, run_backtest


def run_month_backtests(
    *,
    year: int,
    month: int,
    processed_root: str | Path = "data/processed/futures/NIFTY",
    results_root: str | Path = "data/results/futures/NIFTY",
    timeframes: tuple[int, ...] = (1, 5, 15),
    config: BacktestConfig | None = None,
) -> dict[str, object]:
    """Backtest every timeframe of a processed month and store outputs."""
    processed_month = Path(processed_root) / f"{year:04d}-{month:02d}"
    results_month = Path(results_root) / f"{year:04d}-{month:02d}"
    results_month.mkdir(parents=True, exist_ok=True)
    cfg = config or BacktestConfig()

    summary: dict[str, object] = {}
    for tf in timeframes:
        tf_label = f"{tf}m"
        candles = pl.read_parquet(processed_month / tf_label / "candles.parquet")
        signals = pl.read_parquet(results_month / f"signals_{tf_label}.parquet")
        result = run_backtest(candles, signals, cfg)

        result.trades.write_parquet(results_month / f"trades_{tf_label}.parquet")
        result.equity.write_parquet(results_month / f"equity_{tf_label}.parquet")
        (results_month / f"metrics_{tf_label}.json").write_text(
            json.dumps(result.metrics, indent=2), encoding="utf-8"
        )
        summary[tf_label] = {
            **result.metrics,
            "trades_path": str(results_month / f"trades_{tf_label}.parquet"),
        }
    return summary


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--year", type=int, required=True)
    parser.add_argument("--month", type=int, required=True)
    parser.add_argument("--timeframes", default="1,5,15")
    args = parser.parse_args()
    tfs = tuple(int(x) for x in args.timeframes.split(",") if x.strip())
    summary = run_month_backtests(year=args.year, month=args.month, timeframes=tfs)
    for label, m in summary.items():
        print(
            f"{label}: {m['total_trades']} trades, net P&L {m['net_pnl']:.0f}, "
            f"win {m['win_rate']:.0%}, PF {m['profit_factor']:.2f}, "
            f"maxDD {m['max_drawdown_pct']:.1%}"
        )


if __name__ == "__main__":
    main()
