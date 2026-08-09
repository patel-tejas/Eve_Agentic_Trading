"""Phase 04: generate strategy signals for a processed month.

Reads processed candles for each timeframe, recomputes indicators and
signals with the frozen baseline config, and stores bar-level signal
frames under data/results/futures/NIFTY/<year>-<month>/signals_<tf>m.parquet
"""

from __future__ import annotations

import argparse
from pathlib import Path

import polars as pl

from quant.strategies.ema_9_15 import StrategyConfig, generate_signals


def generate_month_signals(
    *,
    year: int,
    month: int,
    processed_root: str | Path = "data/processed/futures/NIFTY",
    results_root: str | Path = "data/results/futures/NIFTY",
    timeframes: tuple[int, ...] = (1, 5, 15),
    config: StrategyConfig | None = None,
) -> dict[str, object]:
    """Signal every timeframe of a processed month; store signals parquet."""
    cfg = config or StrategyConfig()
    processed_month = Path(processed_root) / f"{year:04d}-{month:02d}"
    results_month = Path(results_root) / f"{year:04d}-{month:02d}"
    results_month.mkdir(parents=True, exist_ok=True)

    summary: dict[str, object] = {}
    for tf in timeframes:
        candles_path = processed_month / f"{tf}m" / "candles.parquet"
        if not candles_path.exists():
            raise FileNotFoundError(f"Missing processed candles: {candles_path}")
        candles = pl.read_parquet(candles_path)
        tf_label = f"{tf}m"
        signals = generate_signals(candles, config=cfg, timeframe=tf_label)
        out_path = results_month / f"signals_{tf_label}.parquet"
        signals.write_parquet(out_path)
        summary[tf_label] = {
            "bars": signals.height,
            "buys": int(signals.filter(pl.col("signal_type") == "BUY").height),
            "sells": int(signals.filter(pl.col("signal_type") == "SELL").height),
            "path": str(out_path),
        }
    return summary


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--year", type=int, required=True)
    parser.add_argument("--month", type=int, required=True)
    parser.add_argument("--timeframes", default="1,5,15")
    args = parser.parse_args()

    tfs = tuple(int(x) for x in args.timeframes.split(",") if x.strip())
    summary = generate_month_signals(year=args.year, month=args.month, timeframes=tfs)
    for label, info in summary.items():
        print(
            f"{label}: {info['bars']} bars, {info['buys']} BUY, "
            f"{info['sells']} SELL -> {info['path']}"
        )


if __name__ == "__main__":
    main()
