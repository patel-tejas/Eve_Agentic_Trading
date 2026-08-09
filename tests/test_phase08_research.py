"""Phase 08 unit tests: grid search, walk-forward, regimes, runner.

Polars only; no network.
"""

from __future__ import annotations

import json
from datetime import datetime

import polars as pl
import pytest

from quant.backtest.engine import BacktestConfig
from quant.research.parameter_search import (
    DEFAULT_GRID,
    evaluate_params,
    grid_combinations,
    parameter_grid_search,
    split_schedule,
)
from quant.research.regime import analyse_regimes, day_regime_labels
from quant.research.walk_forward import (
    define_walk_windows,
    walk_forward,
)

BASE = datetime(2026, 7, 1, 9, 15)

TINY_GRID = {
    "fast_ema": (5, 9),
    "slow_ema": (15, 21),
    "angle_threshold": (20.0, 30.0),
    "angle_lookback": (1, 2),
}


def _month_candles(days: int = 31) -> pl.DataFrame:
    """Six hourly bars per day across the first ``days`` days of July 2026."""
    rows = []
    for day in range(1, days + 1):
        for hour in range(10, 16):
            ts = datetime(2026, 7, day, hour)
            i = (day - 1) * 6 + (hour - 10)
            price = 100.0 + 25.0 * __import__("math").sin(i / 6) + i * 0.05
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


def _range_day(day: int, range_pct: float) -> list[dict[str, object]]:
    close = 100.0
    half = close * range_pct / 2
    return [
        {
            "timestamp": datetime(2026, 7, day, 10 + h),
            "open": close,
            "high": close + half,
            "low": close - half,
            "close": close,
        }
        for h in range(3)
    ]


def _regime_candles() -> pl.DataFrame:
    rows = _range_day(1, 0.02) + _range_day(2, 0.007)
    return pl.DataFrame(rows, schema_overrides={"timestamp": pl.Datetime("ms")})


def _trade(day: int, hour: int, net: float, gross: float) -> dict[str, object]:
    return {
        "entry_time": datetime(2026, 7, day, hour),
        "net_pnl": net,
        "gross_pnl": gross,
    }


def test_grid_combinations_default_320():
    combos = grid_combinations()
    assert len(combos) == 320
    for combo in combos:
        assert set(combo) == set(DEFAULT_GRID)
        assert combo["fast_ema"] < combo["slow_ema"]


def test_grid_combinations_drops_invalid_fast_slow():
    combos = grid_combinations(
        {
            "fast_ema": (12,),
            "slow_ema": (15, 10),
            "angle_threshold": (20.0,),
            "angle_lookback": (1,),
        }
    )
    assert len(combos) == 1
    assert combos[0]["slow_ema"] == 15


def test_parameter_grid_search_sorted_and_deterministic():
    candles = _month_candles()
    results = parameter_grid_search(candles, grid=TINY_GRID)
    assert results.height == 16
    assert results["net_pnl"].is_sorted(descending=True)
    for column in (
        "experiment_id",
        "fast_ema",
        "slow_ema",
        "angle_threshold",
        "angle_lookback",
        "net_pnl",
        "profit_factor",
        "total_trades",
    ):
        assert column in results.columns
    again = parameter_grid_search(candles, grid=TINY_GRID)
    assert results.to_dicts() == again.to_dicts()


def test_evaluate_params_respects_window():
    candles = _month_candles()
    params = {"fast_ema": 5, "slow_ema": 15, "angle_threshold": 30.0, "angle_lookback": 1}
    window = (datetime(2026, 7, 1), datetime(2026, 7, 10))
    result = evaluate_params(candles, params, window=window)
    assert result.metrics["total_trades"] >= 0
    cfg = BacktestConfig()
    from quant.strategies.ema_9_15 import StrategyConfig, generate_signals

    frame = candles.filter(
        (pl.col("timestamp") >= window[0]) & (pl.col("timestamp") < window[1])
    )
    signals = generate_signals(frame, config=StrategyConfig(**params))
    from quant.backtest.engine import run_backtest

    bt = run_backtest(frame, signals, cfg)
    assert result.metrics["net_pnl"] == pytest.approx(bt.metrics["net_pnl"])


def test_split_schedule_matches_spec():
    candles = _month_candles()
    splits = split_schedule(candles)
    assert splits["train"] == (datetime(2026, 7, 1), datetime(2026, 7, 24))
    assert splits["validation"] == (datetime(2026, 7, 24), datetime(2026, 7, 28))
    assert splits["test"] == (datetime(2026, 7, 28), datetime(2026, 8, 1))


def test_define_walk_windows_three_steps():
    windows = define_walk_windows(datetime(2026, 7, 1), datetime(2026, 7, 31))
    assert len(windows) == 3
    assert windows[0] == (
        datetime(2026, 7, 1),
        datetime(2026, 7, 15),
        datetime(2026, 7, 16),
        datetime(2026, 7, 21),
    )
    assert windows[1][1:] == (
        datetime(2026, 7, 20),
        datetime(2026, 7, 21),
        datetime(2026, 7, 26),
    )
    assert windows[2][1:] == (
        datetime(2026, 7, 25),
        datetime(2026, 7, 26),
        datetime(2026, 7, 31),
    )


def test_walk_forward_calibrates_on_train_only():
    candles = _month_candles()
    steps = walk_forward(candles, grid=TINY_GRID)
    assert len(steps) == 3
    for step in steps:
        assert step.test_start >= step.train_end
        expected = parameter_grid_search(
            candles.filter(
                (pl.col("timestamp") >= step.train_start)
                & (pl.col("timestamp") < step.train_end)
            ),
            grid=TINY_GRID,
        ).head(1).to_dicts()[0]
        assert step.best_params == {
            k: expected[k] for k in ("fast_ema", "slow_ema", "angle_threshold", "angle_lookback")
        }
        assert step.train_net_pnl == pytest.approx(expected["net_pnl"])


def test_walk_forward_too_short_raises():
    candles = _month_candles(days=10)
    with pytest.raises(ValueError, match="too short"):
        walk_forward(candles, grid=TINY_GRID)


def test_day_regime_labels_thresholds():
    labels = day_regime_labels(_regime_candles())
    by_day = {row["day_of"]: row["regime"] for row in labels.to_dicts()}
    assert by_day[datetime(2026, 7, 1).date()] == "high"
    assert by_day[datetime(2026, 7, 2).date()] == "low"


def test_analyse_regimes_empty_trades():
    summaries = analyse_regimes(_regime_candles(), pl.DataFrame())
    assert [s.regime for s in summaries] == ["high", "mid", "low"]
    assert all(s.trades == 0 and s.net_pnl == 0.0 for s in summaries)


def test_analyse_regimes_joins_by_entry_date():
    trades = pl.DataFrame(
        [
            _trade(1, 10, 500.0, 600.0),
            _trade(2, 11, -200.0, -180.0),
            _trade(3, 10, 999.0, 999.0),  # no candle day -> dropped
        ]
    )
    summaries = {s.regime: s for s in analyse_regimes(_regime_candles(), trades)}
    high = summaries["high"]
    assert high.trades == 1
    assert high.net_pnl == pytest.approx(500.0)
    assert high.win_rate == pytest.approx(1.0)
    low = summaries["low"]
    assert low.trades == 1
    assert low.net_pnl == pytest.approx(-200.0)
    assert low.profit_factor == pytest.approx(0.0)


def test_run_research_end_to_end(tmp_path):
    src = tmp_path / "processed"
    month = src / "2026-07"
    (month / "5m").mkdir(parents=True)
    _month_candles().write_parquet(month / "5m" / "candles.parquet")
    (month / "15m").mkdir(parents=True)
    _month_candles().write_parquet(month / "15m" / "candles.parquet")

    from scripts.run_research import run_research

    summary = run_research(
        year=2026,
        month=7,
        processed_root=src,
        results_root=tmp_path / "res",
        timeframes=(5,),
        grid=TINY_GRID,
    )
    research = tmp_path / "res" / "2026-07" / "research"
    assert (research / "parameter_search_5m.parquet").exists()
    assert (research / "walk_forward_5m.parquet").exists()
    assert (research / "regime_analysis.json").exists()
    assert (research / "robustness_report.md").exists()

    info = summary["timeframes"]["5m"]
    assert info["grid_search"]["combinations"] == 16
    assert len(info["walk_forward"]) == 3
    assert len(info["regimes"]) == 3

    merged = run_research(
        year=2026,
        month=7,
        processed_root=src,
        results_root=tmp_path / "res",
        timeframes=(15,),
        grid=TINY_GRID,
    )
    assert set(merged["timeframes"]) == {"5m", "15m"}

    report = (research / "robustness_report.md").read_text(encoding="utf-8")
    assert "Robustness Report" in report
    assert "Walk-forward" in report and "Regime analysis" in report

    data = json.loads((research / "regime_analysis.json").read_text(encoding="utf-8"))
    assert data["period"] == "2026-07"
    assert set(data["timeframes"]) == {"5m", "15m"}
