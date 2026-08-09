"""Baseline experiment runner.

Phase 06: run strategy variants A (crossover), B (+angle) and
C (+angle + trend) across 1m/5m/15m over a processed month, attach
experiment metadata (id, config hash, dataset version), and emit a
comparison JSON + markdown report.
"""

from __future__ import annotations

import hashlib
import json
from dataclasses import dataclass
from pathlib import Path

import polars as pl
from pydantic import BaseModel

from quant.backtest.costs import CostConfig, SlippageConfig
from quant.backtest.engine import BacktestConfig, BacktestResult, run_backtest
from quant.backtest.execution import ExecutionConfig
from quant.strategies.ema_9_15 import StrategyConfig, generate_signals

DATASET_VERSION = "nifty_futures_july_2026_v1"
STRATEGY_VERSION = "ema_9_15_angle_v1"
COST_MODEL_VERSION = "india_futures_v1"
ENGINE_VERSION = "0.1.0"

BASELINE_SLIPPAGE = SlippageConfig(mode="normal")  # 1 tick adverse


def config_hash(model: BaseModel) -> str:
    """Deterministic sha256 over the canonical JSON of a config dataclass."""
    canonical = json.dumps(model.model_dump(), sort_keys=True, separators=(",", ":"))
    return "sha256:" + hashlib.sha256(canonical.encode()).hexdigest()[:16]


@dataclass(frozen=True)
class Variant:
    """A named strategy variant used by the baseline."""

    label: str  # "A" | "B" | "C"
    config: StrategyConfig


def baseline_variants(
    angle_threshold: float = 30.0,
) -> list[Variant]:
    """The three baseline strategy variants (A/B/C from the research spec)."""
    return [
        Variant("A", StrategyConfig(signal_mode="crossover")),
        Variant(
            "B",
            StrategyConfig(
                signal_mode="crossover_and_angle",
                angle_threshold=angle_threshold,
            ),
        ),
        Variant(
            "C",
            StrategyConfig(
                signal_mode="crossover_angle_and_trend", angle_threshold=angle_threshold
            ),
        ),
    ]


@dataclass(frozen=True)
class Experiment:
    """One (variant, timeframe) run with full reproducibility metadata."""

    experiment_id: str
    variant: str
    timeframe: str
    config: StrategyConfig
    config_hash: str
    dataset_version: str
    strategy_version: str
    cost_model_version: str
    engine_version: str
    result: BacktestResult


def run_baseline(
    *,
    year: int,
    month: int,
    processed_root: str | Path = "data/processed/futures/NIFTY",
    results_root: str | Path = "data/results/futures/NIFTY",
    timeframes: tuple[int, ...] = (1, 5, 15),
    angle_threshold: float = 30.0,
) -> list[Experiment]:
    """Run all variant x timeframe experiments for a processed month."""
    processed_month = Path(processed_root) / f"{year:04d}-{month:02d}"
    results_month = Path(results_root) / f"{year:04d}-{month:02d}"
    results_month.mkdir(parents=True, exist_ok=True)

    backtest_cfg = BacktestConfig(
        costs=CostConfig(),
        execution=ExecutionConfig(slippage=BASELINE_SLIPPAGE),
    )

    experiments: list[Experiment] = []
    seq = 0
    for tf in timeframes:
        tf_label = f"{tf}m"
        candles = pl.read_parquet(processed_month / tf_label / "candles.parquet")
        for variant in baseline_variants(angle_threshold=angle_threshold):
            seq += 1
            experiment_id = f"EXP-{year:04d}-{seq:04d}"
            signals = generate_signals(candles, config=variant.config, timeframe=tf_label)
            result = run_backtest(candles, signals, backtest_cfg)
            experiments.append(
                Experiment(
                    experiment_id=experiment_id,
                    variant=variant.label,
                    timeframe=tf_label,
                    config=variant.config,
                    config_hash=config_hash(variant.config),
                    dataset_version=DATASET_VERSION,
                    strategy_version=STRATEGY_VERSION,
                    cost_model_version=COST_MODEL_VERSION,
                    engine_version=ENGINE_VERSION,
                    result=result,
                )
            )
            (results_month / "baseline" / f"trades_{experiment_id}.parquet").parent.mkdir(
                parents=True, exist_ok=True
            )
            result.trades.write_parquet(
                results_month / "baseline" / f"trades_{experiment_id}.parquet"
            )
    return experiments


def experiment_record(exp: Experiment) -> dict[str, object]:
    """Flatten an experiment into the comparison JSON entry."""
    return {
        "experiment_id": exp.experiment_id,
        "variant": exp.variant,
        "timeframe": exp.timeframe,
        "config": exp.config.model_dump(),
        "config_hash": exp.config_hash,
        "dataset_version": exp.dataset_version,
        "strategy_version": exp.strategy_version,
        "cost_model_version": exp.cost_model_version,
        "engine_version": exp.engine_version,
        "metrics": exp.result.metrics,
        "trades": exp.result.trades.height,
    }


def comparison_table(experiments: list[Experiment]) -> dict[str, object]:
    """Group experiment metrics into a variant x timeframe table."""
    by_key = {(e.variant, e.timeframe): e for e in experiments}
    keys = [
        "total_trades",
        "win_rate",
        "gross_pnl",
        "net_pnl",
        "profit_factor",
        "max_drawdown_pct",
        "sharpe",
        "sortino",
        "avg_trade_pnl",
        "avg_holding_periods",
    ]
    table: dict[str, object] = {}
    for variant in "ABC":
        table[variant] = {}
        tf_keys = sorted(
            {k[1] for k in by_key}, key=lambda s: int(s[:-1])
        )
        for tf in tf_keys:
            exp = by_key.get((variant, tf))
            if exp is None:
                continue
            table[variant][tf] = {k: exp.result.metrics.get(k) for k in keys}
    return table


def write_baseline_outputs(
    experiments: list[Experiment],
    *,
    year: int,
    month: int,
    results_root: str | Path = "data/results/futures/NIFTY",
) -> Path:
    """Write baseline_comparison.json + baseline_report.md; return the report path."""
    results_month = Path(results_root) / f"{year:04d}-{month:02d}"
    comparison = {
        "experiment_count": len(experiments),
        "dataset": DATASET_VERSION,
        "period": f"{year:04d}-{month:02d}",
        "assumptions": {
            "execution": "next candle open",
            "slippage": "normal (1 tick adverse)",
            "costs": "india_futures_v1 (flat 20/order + STT + exchange + SEBI + stamp + GST)",
            "lot_size": 50,
            "position_size": 1,
            "initial_capital": 1_000_000,
        },
        "experiments": [experiment_record(e) for e in experiments],
        "comparison_table": comparison_table(experiments),
    }
    (results_month / "baseline_comparison.json").write_text(
        json.dumps(comparison, indent=2), encoding="utf-8"
    )
    from quant.research.report import render_markdown_report

    report = render_markdown_report(comparison)
    report_path = results_month / "baseline_report.md"
    report_path.write_text(report, encoding="utf-8")
    return report_path
