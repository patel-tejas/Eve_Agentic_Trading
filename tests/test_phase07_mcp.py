"""Phase 07 unit tests: quant-server MCP tools (local, network-free).

Tools are tested as plain functions (deterministic, same signature as the
FastMCP-wrapped versions). Polars only; no network.
"""

from __future__ import annotations

import math
from datetime import datetime, timedelta

import polars as pl
import pytest

from mcp.quant_server.server import (
    MAX_PREVIEW_ROWS,
    TOOL_NAMES,
    build_server,
    compare_timeframes,
    generate_signal,
    get_historical_candles,
    list_research_months,
    parameter_search,
    process_month_data,
    run_backtest_signals,
    validate_dataset,
    walk_forward_test,
)

BASE = datetime(2026, 7, 1, 9, 15)

TINY_GRIDS = {
    "fast_emas": "5,9",
    "slow_emas": "15,21",
    "angle_thresholds": "20,30",
    "angle_lookbacks": "1,2",
}


def _month_candles(days: int = 31) -> pl.DataFrame:
    """Six hourly bars per day for the first ``days`` days of July 2026."""
    rows = []
    for day in range(1, days + 1):
        for hour in range(10, 16):
            ts = datetime(2026, 7, day, hour)
            i = (day - 1) * 6 + (hour - 10)
            price = 100.0 + 25.0 * math.sin(i / 6) + i * 0.05
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


def _raw_frame(days: int = 2) -> pl.DataFrame:
    """Canonical-schema raw frame: full 375-bar trading days (09:15-15:29)."""
    rows = []
    for day in range(1, days + 1):
        for minute in range(375):
            ts = datetime(2026, 7, day, 9, 15) + timedelta(minutes=minute)
            price = 100.0 + minute * 0.01 + day
            rows.append(
                {
                    "timestamp": ts,
                    "instrument": "NIFTY_FUT",
                    "security_id": "54209",
                    "exchange": "NSE",
                    "instrument_type": "FUTIDX",
                    "expiry": datetime(2026, 7, 30).date(),
                    "open": price,
                    "high": price + 0.05,
                    "low": price - 0.05,
                    "close": price + 0.01,
                    "volume": 100,
                    "open_interest": 1474,
                    "lot_size": 50,
                    "tick_size": 0.05,
                }
            )
    return pl.DataFrame(rows, schema_overrides={"timestamp": pl.Datetime("ms")})


def _write_processed(root, days: int = 31) -> None:
    for tf in ("1m", "5m", "15m"):
        d = root / "2026-07" / tf
        d.mkdir(parents=True, exist_ok=True)
        _month_candles(days).write_parquet(d / "candles.parquet")


def _write_raw(root) -> None:
    d = root / "2026-07"
    d.mkdir(parents=True, exist_ok=True)
    _raw_frame().write_parquet(d / "candles_1m.parquet")


def test_tools_registered_and_server_builds():
    assert TOOL_NAMES == (
        "list_research_months",
        "get_historical_candles",
        "download_month_data",
        "validate_dataset",
        "process_month_data",
        "generate_signal",
        "run_backtest_signals",
        "compare_timeframes",
        "parameter_search",
        "walk_forward_test",
    )
    build_server()


def test_list_research_months(tmp_path):
    _write_processed(tmp_path)
    result = list_research_months(processed_root=str(tmp_path))
    assert set(result["months"]) == {"2026-07"}
    assert result["months"]["2026-07"]["5m"] == 186
    assert list_research_months(processed_root=str(tmp_path / "missing"))["months"] == {}


def test_get_historical_candles(tmp_path):
    _write_processed(tmp_path, days=2)
    result = get_historical_candles(
        month="2026-07",
        timeframe="1m",
        limit=3,
        processed_root=str(tmp_path),
    )
    assert result["bars"] == 12
    assert result["date_range"] == ["2026-07-01T10:00:00", "2026-07-02T15:00:00"]
    assert len(result["preview"]) == 3
    assert isinstance(result["preview"][0]["timestamp"], str)
    assert result["preview"][0]["open"] == pytest.approx(100.0)


def test_get_historical_candles_missing_month_hints(tmp_path):
    with pytest.raises(ValueError, match="Processed months: none"):
        get_historical_candles(month="2026-07", processed_root=str(tmp_path))
    with pytest.raises(ValueError, match="timeframe must be"):
        _write_processed(tmp_path)
        get_historical_candles(month="2026-07", timeframe="7m", processed_root=str(tmp_path))


def test_get_historical_candles_limit_bounds(tmp_path):
    _write_processed(tmp_path)
    with pytest.raises(ValueError, match="limit must be"):
        get_historical_candles(limit=MAX_PREVIEW_ROWS + 1, processed_root=str(tmp_path))


def test_validate_dataset_tool(tmp_path):
    _write_raw(tmp_path)
    result = validate_dataset(month="2026-07", raw_root=str(tmp_path))
    assert result["overall_status"] in ("pass", "pass_with_warnings")
    assert result["trading_days"] == 2
    names = [c["name"] for c in result["checks"]]
    assert "ohlc_integrity" in names and "continuity" in names and "market_hours" in names
    assert result["report_path"].endswith("validation_report.json")


def test_validate_dataset_tool_missing(tmp_path):
    with pytest.raises(ValueError, match="raw dataset not found"):
        validate_dataset(month="2026-07", raw_root=str(tmp_path))


def test_process_month_data(tmp_path):
    _write_raw(tmp_path)
    result = process_month_data(
        year=2026,
        month=7,
        timeframes="1,5,15",
        raw_root=str(tmp_path),
        processed_root=str(tmp_path / "processed"),
    )
    assert set(result) == {"1m", "5m", "15m", "validation", "verification"}
    assert result["validation"] == "pass"
    assert result["1m"]["bars"] == 750
    assert result["verification"]["5m"] == "pass"


def test_generate_signal_matches_engine(tmp_path):
    _write_processed(tmp_path)
    from quant.strategies.ema_9_15 import StrategyConfig, generate_signals

    result = generate_signal(month="2026-07", timeframe="5m", count=5, processed_root=str(tmp_path))
    candles = _month_candles()
    signals = generate_signals(candles, config=StrategyConfig())
    expected = {
        "BUY": int((signals["signal_type"] == "BUY").sum()),
        "SELL": int((signals["signal_type"] == "SELL").sum()),
    }
    assert result["counts"] == expected
    assert result["config"]["fast_ema"] == 9
    assert len(result["recent_events"]) == 5


def test_run_backtest_signals_matches_engine(tmp_path):
    _write_processed(tmp_path)
    from quant.backtest.engine import BacktestConfig, run_backtest
    from quant.strategies.ema_9_15 import StrategyConfig, generate_signals

    result = run_backtest_signals(
        month="2026-07", timeframe="5m", include_trades=True, processed_root=str(tmp_path)
    )
    candles = _month_candles()
    signals = generate_signals(candles, config=StrategyConfig())
    from quant.backtest.costs import SlippageConfig
    from quant.backtest.execution import ExecutionConfig

    direct = run_backtest(
        candles,
        signals,
        BacktestConfig(
            execution=ExecutionConfig(slippage=SlippageConfig(mode="normal"))
        ),
    )
    assert result["metrics"]["total_trades"] == direct.metrics["total_trades"]
    assert result["metrics"]["net_pnl"] == pytest.approx(direct.metrics["net_pnl"])
    assert result["equity"]["end"] == pytest.approx(direct.equity["equity"][-1])
    assert result["trades"][0]["direction"] in ("LONG", "SHORT")


def test_compare_timeframes(tmp_path):
    _write_processed(tmp_path, days=5)
    result = compare_timeframes(
        month="2026-07",
        timeframes="1,5",
        processed_root=str(tmp_path),
        results_root=str(tmp_path / "res"),
    )
    assert result["experiment_count"] == 6
    assert set(result["comparison_table"]) == {"A", "B", "C"}
    assert result["comparison_table"]["B"]["5m"]["total_trades"] is not None
    ids = [e["experiment_id"] for e in result["experiments"]]
    assert ids[0] == "EXP-2026-0001" and len(set(ids)) == 6


def test_parameter_search_training_window_only(tmp_path):
    _write_processed(tmp_path)
    result = parameter_search(
        month="2026-07", timeframe="5m", top_n=5, processed_root=str(tmp_path), **TINY_GRIDS
    )
    assert result["combinations"] == 16
    bounds = result["train_window"]
    assert bounds[0] == "2026-07-01T00:00:00" and bounds[1] == "2026-07-24T00:00:00"
    assert 0.0 <= result["positive_share"] <= 1.0
    assert len(result["top"]) == 5
    assert result["top"][0]["experiment_id"] == "RE-0001"
    assert result["best"]["params"]["fast_ema"] == result["top"][0]["fast_ema"]


def test_walk_forward_test_steps(tmp_path):
    _write_processed(tmp_path, days=31)
    result = walk_forward_test(
        month="2026-07", timeframe="5m", processed_root=str(tmp_path), **TINY_GRIDS
    )
    assert result["summary"]["steps_count"] == 3
    assert result["steps"][0]["test_start"].startswith("2026-07-16")
    assert result["steps"][2]["test_end"].startswith("2026-07-31")


def test_walk_forward_test_too_short(tmp_path):
    _write_processed(tmp_path, days=10)
    with pytest.raises(ValueError, match="too short"):
        walk_forward_test(
            month="2026-07",
            timeframe="5m",
            processed_root=str(tmp_path),
            **TINY_GRIDS,
        )
