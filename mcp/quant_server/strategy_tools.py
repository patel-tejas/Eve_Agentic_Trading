"""Strategy-builder tools: user strategies as ``eve.strategy/1`` specs (Phase 15).

The model's job is to fill in a typed spec; these tools validate it, describe
it in template-rendered English, and run it through the same deterministic
engine as every other strategy. Nothing here executes model-written code, and
every number returned comes from ``quant/``.

Stateless tools (P1) live here. Tools that read or write the user's saved
strategies (P2+) are in ``store_tools.py``.
"""

from __future__ import annotations

from typing import Any

import polars as pl

from mcp.quant_server.server import (
    DEFAULT_PROCESSED_ROOT,
    MAX_TRADES,
    _json_safe,
    _metrics_brief,
    _processed_candles,
    list_research_months,
)
from quant.backtest.engine import run_backtest
from quant.research.significance import bootstrap_sharpe_ci, monte_carlo_permutation_test
from quant.strategies.spec import (
    NIFTY_LOT_SIZE,
    StrategySpecV1,
    analyse,
    describe,
    public_vocabulary,
    spec_backtest_config,
    spec_hash,
    spec_signals,
)

MAX_PREVIEW_EVENTS = 100
MAX_SIGNIFICANCE_ITERATIONS = 5_000


def _valid(spec: StrategySpecV1 | dict[str, Any]) -> StrategySpecV1:
    return analyse(spec).require_valid()


def describe_strategy_vocabulary() -> dict[str, object]:
    """What a strategy spec (eve.strategy/1) may contain: indicators with
    parameter bounds and defaults, comparators, operand kinds, price levels,
    risk modes, timeframes and the research months that have data. Call this
    before building a spec; never use an indicator or field not listed."""
    vocab = public_vocabulary()
    vocab["research_months"] = sorted(list_research_months()["months"].keys())
    vocab["lot_size"] = NIFTY_LOT_SIZE
    vocab["example"] = EXAMPLE_SPEC
    return _json_safe(vocab)


def validate_strategy_spec(spec: StrategySpecV1) -> dict[str, object]:
    """Check a strategy spec (eve.strategy/1) without running it.

    Returns valid, errors and warnings (each with a JSON-Pointer path and how
    to fix it), the normalised spec with defaults filled in, a template
    plain-English summary to show the user, and the spec_hash. Fix every
    error and validate again before backtesting.
    """
    return _json_safe(analyse(spec).to_dict())


def preview_strategy_signals(
    spec: StrategySpecV1,
    month: str = "2026-07",
    count: int = 20,
    processed_root: str = str(DEFAULT_PROCESSED_ROOT),
) -> dict[str, object]:
    """Run a strategy spec's entry/exit rules over one research month and
    return signal counts plus the most recent ``count`` (1-100) BUY/SELL/EXIT
    bars. Cheap: no backtest. Use it to check a spec fires at all."""
    if not 1 <= count <= MAX_PREVIEW_EVENTS:
        raise ValueError(f"count must be 1..{MAX_PREVIEW_EVENTS}")
    valid = _valid(spec)
    candles = _processed_candles(month, valid.timeframe, processed_root)
    signals = spec_signals(candles, valid)
    events = signals.filter(pl.col("signal_type") != "HOLD").sort("timestamp")
    counts = {
        k: int((events["signal_type"] == k).sum())
        for k in ("BUY", "SELL", "EXIT_LONG", "EXIT_SHORT", "EXIT")
    }
    recent = (
        events.tail(count)
        .join(candles.select("timestamp", "close"), on="timestamp", how="left")
        .select("timestamp", "signal_type", "close")
    )
    return _json_safe(
        {
            "month": month,
            "timeframe": valid.timeframe,
            "bars": candles.height,
            "counts": counts,
            "recent_events": recent.to_dicts(),
            "spec_hash": spec_hash(valid),
        }
    )


def run_spec_backtest(
    spec: StrategySpecV1,
    month: str,
    processed_root: str = str(DEFAULT_PROCESSED_ROOT),
):
    """(validated spec, candles, BacktestResult) -- shared by the tools below."""
    valid = _valid(spec)
    candles = _processed_candles(month, valid.timeframe, processed_root)
    signals = spec_signals(candles, valid)
    result = run_backtest(candles, signals, spec_backtest_config(valid))
    return valid, candles, result


def backtest_payload(valid: StrategySpecV1, month: str, result, include_trades: bool):
    trades = result.trades
    exit_reasons: dict[str, int] = {}
    if trades.height and "exit_reason" in trades.columns:
        exit_reasons = {
            row["exit_reason"]: int(row["len"])
            for row in trades.group_by("exit_reason").len().to_dicts()
        }
    payload: dict[str, Any] = {
        "month": month,
        "timeframe": valid.timeframe,
        "spec_hash": spec_hash(valid),
        "summary": describe(valid),
        "lot_size": NIFTY_LOT_SIZE,
        "lots": valid.sizing.lots,
        "slippage": valid.execution.slippage,
        "metrics": _metrics_brief(result.metrics),
        "exit_reasons": exit_reasons,
        "equity": {
            "start": result.equity["equity"][0],
            "end": result.equity["equity"][-1],
            "bars": result.equity.height,
        },
    }
    if include_trades:
        payload["trades"] = (
            trades.select(
                "trade_id", "entry_time", "exit_time", "direction", "entry_price",
                "exit_price", "quantity", "gross_pnl", "costs", "net_pnl", "exit_reason",
            )
            .head(MAX_TRADES)
            .to_dicts()
        )
    return payload


def backtest_strategy_spec(
    spec: StrategySpecV1,
    month: str = "2026-07",
    include_trades: bool = False,
    processed_root: str = str(DEFAULT_PROCESSED_ROOT),
) -> dict[str, object]:
    """Backtest a strategy spec (eve.strategy/1) over one research month.

    Same engine as every other strategy: signals at bar close, fills at the
    next open plus slippage, Indian futures costs, the spec's stop/target/
    trail and session square-off. Returns metrics, exit-reason counts and
    (optionally, capped at 300) trades. Quote numbers only from this result.
    """
    valid, _, result = run_spec_backtest(spec, month, processed_root)
    return _json_safe(backtest_payload(valid, month, result, include_trades))


def strategy_significance(
    spec: StrategySpecV1,
    month: str = "2026-07",
    iterations: int = 1000,
    seed: int = 20260831,
    processed_root: str = str(DEFAULT_PROCESSED_ROOT),
) -> dict[str, object]:
    """Is a strategy spec's backtest distinguishable from luck?

    Bootstrap confidence interval on the Sharpe ratio and a permutation test
    on the trade order, seeded and capped at 5000 iterations. A single
    backtest carries no correction for how many versions were tried.
    """
    if not 1 <= iterations <= MAX_SIGNIFICANCE_ITERATIONS:
        raise ValueError(f"iterations must be 1..{MAX_SIGNIFICANCE_ITERATIONS}")
    valid, _, result = run_spec_backtest(spec, month, processed_root)
    returns = result.daily_returns
    pnls = result.trades["net_pnl"].to_list()
    skipped: dict[str, str] = {}
    ci = None
    perm = None
    if len(returns) >= 2:
        ci = bootstrap_sharpe_ci(returns, iterations=iterations, seed=seed).to_dict()
    else:
        skipped["sharpe_ci"] = f"{len(returns)} daily returns, need >= 2"
    if len(pnls) >= 2:
        perm = monte_carlo_permutation_test(pnls, iterations=iterations, seed=seed).to_dict()
    else:
        skipped["permutation"] = f"{len(pnls)} trades, need >= 2"
    return _json_safe(
        {
            "month": month,
            "timeframe": valid.timeframe,
            "spec_hash": spec_hash(valid),
            "metrics": _metrics_brief(result.metrics),
            "sharpe_ci": ci,
            "permutation": perm,
            "skipped": skipped,
        }
    )


EXAMPLE_SPEC: dict[str, Any] = {
    "schema_version": "eve.strategy/1",
    "name": "EMA 9/21 cross with RSI filter",
    "timeframe": "15m",
    "direction": "long_only",
    "entry": {
        "long": {
            "all": [
                {
                    "lhs": {"kind": "indicator", "name": "ema", "params": {"period": 9}},
                    "cmp": "crosses_above",
                    "rhs": {"kind": "indicator", "name": "ema", "params": {"period": 21}},
                },
                {
                    "lhs": {"kind": "indicator", "name": "rsi", "params": {"period": 14}},
                    "cmp": "lt",
                    "rhs": {"kind": "const", "value": 70},
                },
            ],
            "any": [],
        },
        "short": None,
    },
    "exit": {
        "long": {
            "all": [],
            "any": [
                {
                    "lhs": {"kind": "indicator", "name": "ema", "params": {"period": 9}},
                    "cmp": "crosses_below",
                    "rhs": {"kind": "indicator", "name": "ema", "params": {"period": 21}},
                }
            ],
        },
        "short": None,
    },
    "risk": {
        "stop": {"mode": "pct", "value": 1.0},
        "target": {"mode": "r_multiple", "value": 2.0},
        "trail": {"mode": "none"},
        "time_stop_bars": None,
    },
    "session": {
        "entry_start": "09:30",
        "entry_end": "14:30",
        "eod_squareoff": True,
        "squareoff_time": "15:15",
    },
    "sizing": {"lots": 1},
    "execution": {"slippage": "normal"},
    "meta": {"source": "chat", "defaulted": ["/risk/target", "/session/entry_end"]},
}

# The chat sees the full spec schema once, on the validator.
validate_strategy_spec.__eve_full_schema__ = True  # type: ignore[attr-defined]

STRATEGY_TOOL_FUNCTIONS = (
    describe_strategy_vocabulary,
    validate_strategy_spec,
    preview_strategy_signals,
    backtest_strategy_spec,
    strategy_significance,
)
