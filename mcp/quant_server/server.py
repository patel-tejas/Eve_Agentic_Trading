"""quant-server: MCP boundary over the deterministic quant engine (Phase 07).

Principle: the server only validates arguments, calls ``quant/`` functions
and serializes results as JSON-safe dicts. No financial logic lives here.
Tools are plain, unit-testable functions decorated onto the FastMCP app.

Run:
    uv run python -m mcp.quant_server.server
"""

from __future__ import annotations

import json
from datetime import date, datetime
from pathlib import Path

import polars as pl
from fastmcp import FastMCP

from quant.backtest.costs import CostConfig, SlippageConfig
from quant.backtest.engine import BacktestConfig, run_backtest
from quant.backtest.execution import ExecutionConfig
from quant.data.download import download_nifty_futures_upstox
from quant.data.validation import validate_dataset as validate_dataset_engine
from quant.processing.pipeline import process_month
from quant.research.baseline import comparison_table, run_baseline
from quant.research.parameter_search import parameter_grid_search, split_schedule
from quant.research.walk_forward import walk_forward
from quant.strategies.ema_9_15 import StrategyConfig, generate_signals

PROJECT_ROOT = Path(__file__).resolve().parents[2]

DEFAULT_RAW_ROOT = PROJECT_ROOT / "data" / "raw" / "futures" / "NIFTY"
DEFAULT_PROCESSED_ROOT = PROJECT_ROOT / "data" / "processed" / "futures" / "NIFTY"
DEFAULT_RESULTS_ROOT = PROJECT_ROOT / "data" / "results" / "futures" / "NIFTY"

TIMEFRAME_LABELS = ("1m", "5m", "15m")
MAX_PREVIEW_ROWS = 200
MAX_TRADES = 300
MAX_SIGNALS = 100


def _json_safe(value: object) -> object:
    """Convert datetimes/dates and numpy scalars to JSON-safe types."""
    if isinstance(value, (datetime, date)):
        return value.isoformat()
    if isinstance(value, pl.DataFrame):
        return [_json_safe(row) for row in value.to_dicts()]
    if isinstance(value, dict):
        return {k: _json_safe(v) for k, v in value.items()}
    if isinstance(value, (list, tuple)):
        return [_json_safe(v) for v in value]
    if hasattr(value, "item"):
        try:
            return value.item()
        except ValueError:
            return str(value)
    return value


def _parse_month(month: str) -> tuple[int, int]:
    parts = str(month).split("-")
    if len(parts) != 2:
        raise ValueError(f"month must be 'YYYY-MM', got {month!r}")
    try:
        return int(parts[0]), int(parts[1])
    except ValueError as exc:
        raise ValueError(f"month must be 'YYYY-MM', got {month!r}") from exc


def _parse_timeframes(timeframes: str) -> tuple[int, ...]:
    tfs = tuple(int(x) for x in str(timeframes).split(",") if x.strip())
    if not tfs:
        raise ValueError("no timeframes given")
    return tfs


def _parse_int_list(value: str) -> list[int]:
    values = [int(x.strip()) for x in str(value).split(",") if x.strip()]
    if not values:
        raise ValueError("empty list")
    return values


def _parse_float_list(value: str) -> list[float]:
    values = [float(x.strip()) for x in str(value).split(",") if x.strip()]
    if not values:
        raise ValueError("empty list")
    return values


def _available_months(root: str | Path) -> list[str]:
    root = Path(root)
    if not root.exists():
        return []
    return sorted(p.name for p in root.iterdir() if p.is_dir() and len(p.name) == 7)


def _processed_candles(month: str, timeframe: str, processed_root: str | Path) -> pl.DataFrame:
    if timeframe not in TIMEFRAME_LABELS:
        raise ValueError(f"timeframe must be one of {TIMEFRAME_LABELS}, got {timeframe!r}")
    path = Path(processed_root) / month / timeframe / "candles.parquet"
    if not path.exists():
        available = _available_months(Path(processed_root))
        raise ValueError(
            f"processed candles not found: {path}. Processed months: {available or 'none'} — "
            "run process_month_data first (or download_month_data when raw data is missing)."
        )
    return pl.read_parquet(path).sort("timestamp")


def _backtest_config(slippage: str = "normal", slippage_ticks: int = 1) -> BacktestConfig:
    if slippage == "ticks":
        sc = SlippageConfig(mode="ticks", entry_ticks=slippage_ticks, exit_ticks=slippage_ticks)
    else:
        sc = SlippageConfig(mode=slippage)
    return BacktestConfig(costs=CostConfig(), execution=ExecutionConfig(slippage=sc))


def _metrics_brief(metrics: dict[str, float | int | str]) -> dict[str, object]:
    keys = (
        "total_trades",
        "win_rate",
        "gross_pnl",
        "net_pnl",
        "profit_factor",
        "avg_trade_pnl",
        "avg_holding_periods",
        "max_drawdown_pct",
        "max_drawdown_duration_bars",
        "sharpe",
        "sortino",
        "calmar",
        "trading_days",
    )
    return {key: metrics.get(key) for key in keys}


def _param_dict(
    fast_ema: int,
    slow_ema: int,
    angle_threshold: float,
    angle_lookback: int,
    signal_mode: str,
) -> dict[str, object]:
    if signal_mode not in (
        "crossover",
        "crossover_and_angle",
        "crossover_angle_and_trend",
    ):
        raise ValueError(
            "signal_mode must be one of crossover|crossover_and_angle"
            "|crossover_angle_and_trend"
        )
    return {
        "fast_ema": fast_ema,
        "slow_ema": slow_ema,
        "angle_threshold": angle_threshold,
        "angle_lookback": angle_lookback,
        "signal_mode": signal_mode,
    }


# ------------------------------------------------------------------ tools


def list_research_months(
    processed_root: str = str(DEFAULT_PROCESSED_ROOT),
) -> dict[str, object]:
    """List processed research months and their bar counts per timeframe."""
    months: dict[str, object] = {}
    for dirname in _available_months(processed_root):
        months[dirname] = {}
        for tf in TIMEFRAME_LABELS:
            metadata = Path(processed_root) / dirname / tf / "dataset_metadata.json"
            candles = Path(processed_root) / dirname / tf / "candles.parquet"
            if metadata.exists():
                data = json.loads(metadata.read_text(encoding="utf-8"))
                months[dirname][tf] = data.get("bars")
            elif candles.exists():
                months[dirname][tf] = int(
                    pl.scan_parquet(candles).select(pl.len()).collect().item()
                )
    return _json_safe({"months": months})


def get_historical_candles(
    month: str = "2026-07",
    timeframe: str = "1m",
    limit: int = 10,
    offset: int = 0,
    processed_root: str = str(DEFAULT_PROCESSED_ROOT),
) -> dict[str, object]:
    """Read processed OHLCV candles for a month+timeframe (deterministic parquet).

    ``limit`` (1-200) rows start at ``offset``. Returns schema, bar count,
    date range and a preview of the requested window.
    """
    if not 1 <= limit <= MAX_PREVIEW_ROWS:
        raise ValueError(f"limit must be 1..{MAX_PREVIEW_ROWS}")
    frame = _processed_candles(month, timeframe, processed_root)
    if offset >= frame.height:
        raise ValueError(f"offset {offset} beyond {frame.height} bars")
    preview_cols = [
        col for col in ("timestamp", "open", "high", "low", "close", "volume", "open_interest")
        if col in frame.columns
    ]
    window = frame.slice(offset, limit).select(*preview_cols)
    return _json_safe(
        {
            "month": month,
            "timeframe": timeframe,
            "path": str(Path(processed_root) / month / timeframe / "candles.parquet"),
            "bars": frame.height,
            "date_range": [
                frame["timestamp"].min().isoformat(),
                frame["timestamp"].max().isoformat(),
            ],
            "columns": frame.columns,
            "preview": window.to_dicts(),
        }
    )


def download_month_data(
    year: int,
    month: int,
    out_dir: str = str(DEFAULT_RAW_ROOT / ".."),
) -> dict[str, object]:
    """Fetch a research month of NIFTY futures 1m candles from the data
    provider (Upstox expired-contract API for past months) and store raw
    Parquet + contract metadata. Network required."""
    result = download_nifty_futures_upstox(
        year=year, month=month, out_dir=out_dir
    )
    return _json_safe(
        {
            "candles": result["candles"],
            "contract_symbol": result["contract"].trading_symbol,
            "expiry": result["contract"].expiry,
            "parquet_path": str(result["parquet_path"]),
            "metadata_path": str(result["metadata_path"]),
        }
    )


def validate_dataset(
    month: str,
    raw_root: str = str(DEFAULT_RAW_ROOT),
) -> dict[str, object]:
    """Run the full phase-02 validation suite on a raw 1m dataset.

    Returns the audit report (checks, overall status, warnings/errors).
    """
    year, _ = _parse_month(month)
    candles_path = Path(raw_root) / month / "candles_1m.parquet"
    if not candles_path.exists():
        raise ValueError(
            f"raw dataset not found: {candles_path}. "
            f"Available: {_available_months(raw_root) or 'none'}"
        )
    frame = pl.read_parquet(candles_path)
    report = validate_dataset_engine(
        frame, f"{month}_1m", interval_minutes=1
    )
    report_path = candles_path.with_name("validation_report.json")
    report.save(report_path)
    return _json_safe({"report_path": str(report_path), **report.to_dict()})


def process_month_data(
    year: int,
    month: int,
    timeframes: str = "1,5,15",
    raw_root: str = str(DEFAULT_RAW_ROOT),
    processed_root: str = str(DEFAULT_PROCESSED_ROOT),
) -> dict[str, object]:
    """Validate raw 1m, resample to 5m/15m, add EMA9/15 + angle indicators
    and store processed candles per timeframe. Idempotent."""
    tfs = _parse_timeframes(timeframes)
    results = process_month(
        year=year,
        month=month,
        raw_root=raw_root,
        processed_root=processed_root,
        timeframes=tfs,
    )
    return _json_safe(results)


def generate_signal(
    month: str,
    timeframe: str = "1m",
    fast_ema: int = 9,
    slow_ema: int = 15,
    angle_threshold: float = 30.0,
    angle_lookback: int = 1,
    signal_mode: str = "crossover_and_angle",
    count: int = 10,
    processed_root: str = str(DEFAULT_PROCESSED_ROOT),
) -> dict[str, object]:
    """Generate BUY/SELL/HOLD signals for a processed month+timeframe.

    Returns counts and the most recent non-HOLD events. Strategy
    parameters are the deterministic phase-04 engine ones.
    """
    if not 1 <= count <= MAX_SIGNALS:
        raise ValueError(f"count must be 1..{MAX_SIGNALS}")
    candles = _processed_candles(month, timeframe, processed_root)
    cfg = StrategyConfig(
        **_param_dict(fast_ema, slow_ema, angle_threshold, angle_lookback, signal_mode)
    )
    signals = generate_signals(candles, config=cfg, timeframe=timeframe)
    events = signals.filter(pl.col("signal_type") != "HOLD").sort("timestamp")
    counts = {
        "BUY": int((events["signal_type"] == "BUY").sum()),
        "SELL": int((events["signal_type"] == "SELL").sum()),
    }
    return _json_safe(
        {
            "month": month,
            "timeframe": timeframe,
            "config": cfg.model_dump(),
            "bars": candles.height,
            "counts": counts,
            "recent_events": events.tail(count)
            .select("timestamp", "signal_type", "ema_fast", "ema_slow", "angle", "candle_close")
            .to_dicts(),
        }
    )


def run_backtest_signals(
    month: str,
    timeframe: str = "1m",
    fast_ema: int = 9,
    slow_ema: int = 15,
    angle_threshold: float = 30.0,
    angle_lookback: int = 1,
    signal_mode: str = "crossover_and_angle",
    slippage: str = "normal",
    slippage_ticks: int = 1,
    include_trades: bool = False,
    processed_root: str = str(DEFAULT_PROCESSED_ROOT),
) -> dict[str, object]:
    """Backtest a strategy config over a month+timeframe (phase-05 engine).

    Returns full metrics plus (optional, capped at 300) per-trade records.
    Execution: signals at close -> fills at next candle open + slippage.
    """
    candles = _processed_candles(month, timeframe, processed_root)
    cfg = StrategyConfig(
        **_param_dict(fast_ema, slow_ema, angle_threshold, angle_lookback, signal_mode)
    )
    signals = generate_signals(candles, config=cfg, timeframe=timeframe)
    bt = run_backtest(candles, signals, _backtest_config(slippage, slippage_ticks))
    payload: dict[str, object] = {
        "month": month,
        "timeframe": timeframe,
        "config": cfg.model_dump(),
        "slippage": slippage,
        "metrics": _metrics_brief(bt.metrics),
        "equity": {
            "start": bt.equity["equity"][0],
            "end": bt.equity["equity"][-1],
            "bars": bt.equity.height,
        },
    }
    if include_trades:
        trades = bt.trades.select(
            "trade_id", "entry_time", "exit_time", "direction",
            "entry_price", "exit_price", "quantity", "gross_pnl", "costs", "net_pnl",
        )
        payload["trades"] = trades.head(MAX_TRADES).to_dicts()
    return _json_safe(payload)


def compare_timeframes(
    month: str,
    timeframes: str = "1,5,15",
    angle_threshold: float = 30.0,
    results_root: str = str(DEFAULT_RESULTS_ROOT),
    processed_root: str = str(DEFAULT_PROCESSED_ROOT),
) -> dict[str, object]:
    """Run baseline variants A/B/C across timeframes (phase-06) and return
    the comparison table with per-experiment metadata."""
    year, m = _parse_month(month)
    tfs = _parse_timeframes(timeframes)
    if not all(tf in (1, 5, 15) for tf in tfs):
        raise ValueError("timeframes must be a subset of 1,5,15")
    for tf in tfs:
        _processed_candles(month, f"{tf}m", processed_root)
    experiments = run_baseline(
        year=year,
        month=m,
        processed_root=processed_root,
        results_root=results_root,
        timeframes=tfs,
        angle_threshold=angle_threshold,
    )
    records = [
        {
            "experiment_id": e.experiment_id,
            "variant": e.variant,
            "timeframe": e.timeframe,
            "config_hash": e.config_hash,
            "metrics": _metrics_brief(e.result.metrics),
        }
        for e in experiments
    ]
    return _json_safe(
        {
            "month": month,
            "comparison_table": comparison_table(experiments),
            "experiments": records,
            "experiment_count": len(experiments),
        }
    )


def parameter_search(
    month: str,
    timeframe: str = "1m",
    fast_emas: str = "5,7,9,12",
    slow_emas: str = "15,18,21,25",
    angle_thresholds: str = "20,25,30,35,40",
    angle_lookbacks: str = "1,2,3,5",
    top_n: int = 20,
    processed_root: str = str(DEFAULT_PROCESSED_ROOT),
) -> dict[str, object]:
    """Grid-search strategy parameters on the TRAINING windows (phase-08).

    Only the train split (first 23 days of the month) is used for
    calibration; validation/test windows stay clean. Returns summary
    statistics plus the top-N configurations.
    """
    if not 1 <= top_n <= 1000:
        raise ValueError("top_n must be 1..1000")
    candles = _processed_candles(month, timeframe, processed_root)
    grid: dict[str, tuple[object, ...]] = {
        "fast_ema": tuple(_parse_int_list(fast_emas)),
        "slow_ema": tuple(_parse_int_list(slow_emas)),
        "angle_threshold": tuple(_parse_float_list(angle_thresholds)),
        "angle_lookback": tuple(_parse_int_list(angle_lookbacks)),
    }
    train = split_schedule(candles)["train"]
    results = parameter_grid_search(
        candles, window=train, grid=grid, backtest_config=_backtest_config()
    )
    columns = (
        "experiment_id", "fast_ema", "slow_ema", "angle_threshold", "angle_lookback",
        "total_trades", "net_pnl", "profit_factor", "win_rate", "max_drawdown_pct",
    )
    top = results.head(top_n).select(*columns).to_dicts()
    best = top[0]
    return _json_safe(
        {
            "month": month,
            "timeframe": timeframe,
            "train_window": [train[0].isoformat(), train[1].isoformat()],
            "combinations": results.height,
            "positive_share": float((results["net_pnl"] > 0).sum() / results.height),
            "median_net_pnl": float(results["net_pnl"].median()),
            "best": {
                "params": {
                    k: best[k]
                    for k in ("fast_ema", "slow_ema", "angle_threshold", "angle_lookback")
                },
                "net_pnl": best["net_pnl"],
                "total_trades": best["total_trades"],
                "profit_factor": best["profit_factor"],
            },
            "top": top,
        }
    )


def walk_forward_test(
    month: str,
    timeframe: str = "1m",
    fast_emas: str = "5,7,9,12",
    slow_emas: str = "15,18,21,25",
    angle_thresholds: str = "20,25,30,35,40",
    angle_lookbacks: str = "1,2,3,5",
    processed_root: str = str(DEFAULT_PROCESSED_ROOT),
) -> dict[str, object]:
    """Walk-forward validation (phase-08): calibrate on training windows,
    evaluate on untouched test windows, return per-step out-of-sample
    results. Dataset must span at least ~20 calendar days."""
    candles = _processed_candles(month, timeframe, processed_root)
    grid: dict[str, tuple[object, ...]] = {
        "fast_ema": tuple(_parse_int_list(fast_emas)),
        "slow_ema": tuple(_parse_int_list(slow_emas)),
        "angle_threshold": tuple(_parse_float_list(angle_thresholds)),
        "angle_lookback": tuple(_parse_int_list(angle_lookbacks)),
    }
    steps = walk_forward(candles, grid=grid, backtest_config=_backtest_config())
    rows = [_json_safe(s.to_row()) for s in steps]
    test_nets = [float(r["test_net_pnl"]) for r in rows]
    return _json_safe(
        {
            "month": month,
            "timeframe": timeframe,
            "steps": rows,
            "summary": {
                "steps_count": len(rows),
                "oos_positive_steps": sum(1 for v in test_nets if v > 0),
                "oos_total_net_pnl": sum(test_nets),
            },
        }
    )


_TOOL_FUNCTIONS = (
    list_research_months,
    get_historical_candles,
    download_month_data,
    validate_dataset,
    process_month_data,
    generate_signal,
    run_backtest_signals,
    compare_timeframes,
    parameter_search,
    walk_forward_test,
)

TOOL_NAMES = tuple(fn.__name__ for fn in _TOOL_FUNCTIONS)


def build_server() -> FastMCP:
    """Assemble the FastMCP app with every quant tool registered."""
    mcp = FastMCP(
        "quant-engine",
        instructions=(
            "MCP server for the deterministic quant research engine. "
            "Every tool is deterministic given the same inputs. "
            "The agent orchestrates; the engine calculates."
        ),
    )
    for fn in _TOOL_FUNCTIONS:
        mcp.tool(name=fn.__name__, description=fn.__doc__.strip().splitlines()[0])(fn)
    return mcp


def main() -> None:
    build_server().run()


if __name__ == "__main__":
    main()
