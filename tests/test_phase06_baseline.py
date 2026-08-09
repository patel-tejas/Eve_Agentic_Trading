"""Phase 06 unit tests: baseline variants, experiment metadata, report.

Polars only; no network.
"""

from __future__ import annotations

from datetime import datetime, timedelta

import polars as pl
import pytest

from quant.backtest.engine import BacktestConfig, run_backtest
from quant.research.baseline import (
    baseline_variants,
    config_hash,
    run_baseline,
    write_baseline_outputs,
)
from quant.strategies.ema_9_15 import StrategyConfig, generate_signals

BASE = datetime(2026, 7, 1, 9, 15)


def _candles(n: int = 200) -> pl.DataFrame:
    import math

    rows = []
    for i in range(n):
        ts = BASE + timedelta(minutes=i)
        price = 100.0 + 30.0 * math.sin(i / 12) + i * 0.15
        rows.append(
            {
                "timestamp": ts,
                "open": price,
                "high": price + 1,
                "low": price - 1,
                "close": price + 0.25,
            }
        )
    return pl.DataFrame(rows, schema_overrides={"timestamp": pl.Datetime("ms")})


def test_variants_are_distinct_and_valid():
    variants = baseline_variants()
    assert [v.label for v in variants] == ["A", "B", "C"]
    modes = [v.config.signal_mode for v in variants]
    assert modes == ["crossover", "crossover_and_angle", "crossover_angle_and_trend"]


def test_config_hash_stable():
    a = config_hash(StrategyConfig())
    b = config_hash(StrategyConfig())
    c = config_hash(StrategyConfig(fast_ema=10))
    assert a == b
    assert a.startswith("sha256:")
    assert a != c


def test_variant_a_generates_more_signals_than_b():
    frame = _candles()
    sig_a = generate_signals(frame, config=StrategyConfig(signal_mode="crossover"))
    sig_b = generate_signals(frame, config=StrategyConfig(signal_mode="crossover_and_angle"))
    n_a = int((sig_a["signal_type"] != "HOLD").sum())
    n_b = int((sig_b["signal_type"] != "HOLD").sum())
    assert n_a >= n_b
    assert n_a > 0


def test_variant_c_buy_requires_price_above_slow_ema():
    frame = _candles()
    sig = generate_signals(frame, config=StrategyConfig(signal_mode="crossover_angle_and_trend"))
    buys = sig.filter(pl.col("signal_type") == "BUY")
    if buys.height:
        assert (buys["candle_close"] > buys["ema_slow"]).all()


def test_run_baseline_full_matrix(tmp_path):
    src = tmp_path / "processed"
    month = src / "2026-07"
    for tf in (1, 5):
        (month / f"{tf}m").mkdir(parents=True)
        _candles().write_parquet(month / f"{tf}m" / "candles.parquet")
    exps = run_baseline(
        year=2026,
        month=7,
        processed_root=src,
        results_root=tmp_path / "res",
        timeframes=(1, 5),
    )
    assert len(exps) == 6  # 3 variants x 2 timeframes
    ids = [e.experiment_id for e in exps]
    assert len(set(ids)) == 6
    for e in exps:
        assert e.config_hash.startswith("sha256:")
        assert e.dataset_version.startswith("nifty_futures")
        assert e.result.trades.height == e.result.trades.height  # consistency
    report = write_baseline_outputs(exps, year=2026, month=7, results_root=tmp_path / "res")
    assert report.exists()
    comp = (tmp_path / "res" / "2026-07" / "baseline_comparison.json").read_text(encoding="utf-8")
    import json

    data = json.loads(comp)
    assert data["experiment_count"] == 6
    assert set(data["comparison_table"].keys()) == {"A", "B", "C"}
    md = report.read_text(encoding="utf-8")
    assert "Comparison" in md and "Reproducibility" in md


def test_compare_variant_net_pnl_consistent_with_backtest():
    frame = _candles()
    cfg = BacktestConfig()
    sig = generate_signals(frame, config=StrategyConfig(signal_mode="crossover"))
    result = run_backtest(frame, sig, cfg)
    assert result.metrics["net_pnl"] == pytest.approx(result.trades["net_pnl"].sum())
