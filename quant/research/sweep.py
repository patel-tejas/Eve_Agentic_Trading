"""Parallel sweep harness over 16 cores (Phase 09).

The repo's first use of process parallelism -- a grep across the pre-
Phase-09 codebase for
``multiprocessing|ProcessPoolExecutor|joblib|concurrent.futures``
returns zero hits; ``parameter_grid_search`` is a serial list
comprehension, which is why ``scripts/run_research.py`` skips 1m by
default.

Windows/spawn specifics (all mandatory, not stylistic):

* ``os.environ["POLARS_MAX_THREADS"] = "1"`` is set in the PARENT before
  the pool is created, so every spawned worker inherits it before ever
  importing polars. ``pl.thread_pool_size()`` defaults to the machine's
  core count (16 here); without this, N workers x 16 Polars threads each
  is N x 16-way oversubscription and the sweep runs SLOWER than serial.
* Candle data is passed as a file PATH, never a pickled DataFrame --
  workers load (and cache) it themselves.
* Every sweep entrypoint needs an ``if __name__ == "__main__":`` guard
  (enforced in ``scripts/run_sweep.py``, not here).
* Each worker chunk writes its OWN leaderboard shard
  (``part_<pid>_<chunk>.jsonl``) directly -- never a shared file two
  workers could append to concurrently.
"""

from __future__ import annotations

import os
import platform
import socket
import subprocess
import time
from concurrent.futures import ProcessPoolExecutor, as_completed
from dataclasses import dataclass, field
from datetime import date, datetime, timezone
from typing import Any

import polars as pl

# Importing these registers every strategy into STRATEGY_REGISTRY as a
# side effect. This MUST happen at module import time, here, not lazily
# inside run_trial: on Windows, ProcessPoolExecutor SPAWNS a fresh
# interpreter per worker rather than forking, so a worker only ever
# imports what the modules it actually imports pull in. A caller that
# imported the strategy modules in its own __main__ script does NOT make
# them available inside a spawned worker -- only importing them from
# INSIDE quant.research.sweep (which every worker necessarily imports to
# call run_trial at all) guarantees the registry is populated everywhere
# this function runs. Verified: without this, every trial in a
# multi-worker sweep errors with a KeyError on STRATEGY_REGISTRY.
import quant.strategies.ema_9_15  # noqa: E402,F401
import quant.strategies.ist_judas  # noqa: E402,F401
import quant.strategies.orb_vwap  # noqa: E402,F401
import quant.strategies.pdh_pdl_turtle_soup  # noqa: E402,F401
import quant.strategies.smc_ob_choch  # noqa: E402,F401
import quant.strategies.smc_sweep_fvg  # noqa: E402,F401
from quant.backtest.costs import CostConfig, SlippageConfig
from quant.backtest.engine import BacktestConfig, run_backtest
from quant.backtest.execution import ExecutionConfig
from quant.backtest.exits import ExitConfig
from quant.backtest.market import MarketContext
from quant.backtest.metrics import daily_returns_by_date
from quant.research.leaderboard import (
    LEADERBOARD_COLUMNS,
    append_results,
    completed_trial_ids,
    make_trial_id,
    trial_param_hash,
)
from quant.research.run_card import canonical_json, hash_mapping

ENGINE_VERSION = "0.9.0"
COST_MODEL_VERSION = "india_futures_v1"


@dataclass(frozen=True)
class Trial:
    """One unit of sweep work. Every field is a plain, picklable type --
    required for ``ProcessPoolExecutor`` on Windows (spawn)."""

    campaign_id: str
    round: int
    strategy_id: str
    strategy_version: str
    params: dict[str, Any]
    exits: dict[str, Any]
    symbol: str
    price_source: str  # "futures" | "index_spot_proxy"
    timeframe: str
    split: str  # "train" | "val" | "test"
    candles_path: str
    window_start: str | None  # ISO date, half-open [start, end)
    window_end: str | None
    lot_size: int
    tick_size_rupees: float
    costs: dict[str, Any] = field(default_factory=dict)  # CostConfig field overrides
    slippage: dict[str, Any] = field(default_factory=dict)  # SlippageConfig field overrides
    seed: int = 0

    @property
    def param_hash(self) -> str:
        market = {"lot_size": self.lot_size, "tick_size_rupees": self.tick_size_rupees}
        return trial_param_hash(self.strategy_id, self.params, self.exits, market)

    @property
    def trial_id(self) -> str:
        return make_trial_id(self.round, self.param_hash, self.symbol, self.timeframe, self.split)


# Per-worker-process cache: {candles_path: DataFrame}. Persists across
# every trial a given worker processes for the life of the pool, so a
# 1,000-trial sweep against one file reads that parquet exactly once
# per worker, not once per trial.
_FRAME_CACHE: dict[str, pl.DataFrame] = {}


def _load_candles(path: str) -> pl.DataFrame:
    if path not in _FRAME_CACHE:
        _FRAME_CACHE[path] = pl.read_parquet(path).sort("timestamp")
    return _FRAME_CACHE[path]


def _git_sha() -> str:
    try:
        out = subprocess.run(
            ["git", "rev-parse", "--short", "HEAD"],
            capture_output=True,
            text=True,
            timeout=5,
            check=False,
        )
        return out.stdout.strip() or "unknown"
    except Exception:  # noqa: BLE001 -- git_sha is informational, never fatal
        return "unknown"


_GIT_SHA = None  # resolved lazily, once per process


def run_trial(trial: Trial) -> dict[str, Any]:
    """Execute one trial end to end; returns a leaderboard row dict.

    Never raises -- any failure is captured as ``status="error"`` with
    the exception text, so one bad config cannot kill an entire sweep
    chunk. Module-level (not a closure/lambda) so it is picklable.
    """
    global _GIT_SHA
    if _GIT_SHA is None:
        _GIT_SHA = _git_sha()

    t0 = time.time()
    row: dict[str, Any] = {col: None for col in LEADERBOARD_COLUMNS}
    row.update(
        campaign_id=trial.campaign_id,
        round=trial.round,
        trial_id=trial.trial_id,
        strategy_id=trial.strategy_id,
        strategy_version=trial.strategy_version,
        param_hash=trial.param_hash,
        params_json=canonical_json(trial.params),
        exits_json=canonical_json(trial.exits),
        symbol=trial.symbol,
        price_source=trial.price_source,
        timeframe=trial.timeframe,
        split=trial.split,
        window_start=trial.window_start,
        window_end=trial.window_end,
        lot_size=trial.lot_size,
        tick_size_rupees=trial.tick_size_rupees,
        slippage_mode=trial.slippage.get("mode", "normal"),
        engine_version=ENGINE_VERSION,
        cost_model_version=COST_MODEL_VERSION,
        git_sha=_GIT_SHA,
        seed=trial.seed,
        created_at=datetime.now(timezone.utc).isoformat(),
        host=socket.gethostname(),
        status="ok",
        error=None,
    )

    try:
        from quant.strategies.base import STRATEGY_REGISTRY

        frame = _load_candles(trial.candles_path)
        if trial.window_start is not None or trial.window_end is not None:
            start = date.fromisoformat(trial.window_start) if trial.window_start else None
            end = date.fromisoformat(trial.window_end) if trial.window_end else None
            if start is not None:
                frame = frame.filter(pl.col("timestamp").dt.date() >= start)
            if end is not None:
                frame = frame.filter(pl.col("timestamp").dt.date() < end)
        if frame.height == 0:
            raise ValueError(f"no bars in window [{trial.window_start}, {trial.window_end})")

        spec = STRATEGY_REGISTRY[trial.strategy_id]
        signals = spec.generate_signals(frame, trial.params)

        market = MarketContext(
            symbol=trial.symbol,
            price_source=trial.price_source,
            lot_size=trial.lot_size,
            tick_size_rupees=trial.tick_size_rupees,
        )
        bt_cfg = BacktestConfig(
            market=market,
            costs=CostConfig(**trial.costs),
            execution=ExecutionConfig(slippage=SlippageConfig(**trial.slippage)),
            exits=ExitConfig(**trial.exits),
        )
        result = run_backtest(frame, signals, bt_cfg)
        m = result.metrics
        trades = result.trades

        exit_reason_counts = {}
        pct_closed_at_end = 0.0
        if trades.height > 0:
            vc = trades["exit_reason"].value_counts()
            exit_reason_counts = dict(
                zip(vc["exit_reason"].to_list(), vc["count"].to_list(), strict=True)
            )
            pct_closed_at_end = float(trades["closed_at_end"].mean())

        row.update(
            n_bars=frame.height,
            trading_days=frame["timestamp"].dt.date().n_unique(),
            total_trades=m.get("total_trades", 0),
            winning_trades=m.get("winning_trades", 0),
            losing_trades=m.get("losing_trades", 0),
            win_rate=m.get("win_rate", 0.0),
            gross_pnl=m.get("gross_pnl", 0.0),
            net_pnl=m.get("net_pnl", 0.0),
            avg_trade_pnl=m.get("avg_trade_pnl", 0.0),
            profit_factor=m.get("profit_factor", 0.0),
            expectancy=m.get("expectancy", 0.0),
            max_drawdown_pct=m.get("max_drawdown_pct", 0.0),
            max_drawdown_value=m.get("max_drawdown_value", 0.0),
            sharpe=m.get("sharpe", 0.0),
            sortino=m.get("sortino", 0.0),
            calmar=m.get("calmar", 0.0),
            total_return_pct=m.get("total_return_pct", 0.0),
            avg_holding_periods=m.get("avg_holding_periods", 0.0),
            pct_closed_at_end=pct_closed_at_end,
            exit_reason_counts_json=canonical_json(exit_reason_counts),
            daily_returns_json=canonical_json(
                {str(k): v for k, v in daily_returns_by_date(result.equity).items()}
            ),
            config_hash=hash_mapping(
                {"strategy_id": trial.strategy_id, "params": trial.params, "exits": trial.exits}
            ),
            run_card_hash=hash_mapping(row),
            duration_ms=int((time.time() - t0) * 1000),
        )
    except Exception as exc:  # noqa: BLE001 -- captured, never fatal to the sweep
        row.update(
            status="error",
            error=f"{type(exc).__name__}: {exc}",
            duration_ms=int((time.time() - t0) * 1000),
        )
    return row


def _run_chunk(
    trials: list[Trial], *, campaign_id: str, round_no: int, root: str, chunk_idx: int
) -> dict[str, int]:
    """Runs entirely inside one worker process; writes its own shard."""
    rows = [run_trial(t) for t in trials]
    append_results(
        rows,
        campaign_id=campaign_id,
        round_no=round_no,
        root=root,
        shard_name=f"part_{os.getpid()}_{chunk_idx}",
    )
    n_errors = sum(1 for r in rows if r["status"] == "error")
    return {"n": len(rows), "errors": n_errors}


def run_sweep(
    trials: list[Trial],
    *,
    campaign_id: str,
    round_no: int,
    workers: int | None = None,
    root: str = "data/results/leaderboard",
    chunk_size: int = 64,
) -> dict[str, Any]:
    """Dispatch ``trials`` across ``workers`` processes; resumable.

    Trials whose ``trial_id`` is already recorded with
    ``status != "error"`` are skipped before dispatch (idempotent
    resume). ``trials`` is ALSO deduplicated by ``trial_id`` against
    itself (first occurrence kept) -- two identical trials in the same
    call (e.g. a caller's grid degenerating to fewer distinct configs
    than positions) must not both run and both get written; that would
    silently duplicate rows in the leaderboard and waste compute.
    Returns a summary dict, not the leaderboard itself -- call
    ``quant.research.leaderboard.load_leaderboard`` for that.
    """
    os.environ["POLARS_MAX_THREADS"] = "1"  # MUST be set before the pool is created

    seen_ids: set[str] = set()
    deduped: list[Trial] = []
    duplicates_in_input = 0
    for t in trials:
        if t.trial_id in seen_ids:
            duplicates_in_input += 1
            continue
        seen_ids.add(t.trial_id)
        deduped.append(t)

    already_done = completed_trial_ids(campaign_id, root=root)
    pending = [t for t in deduped if t.trial_id not in already_done]
    skipped = len(deduped) - len(pending) + duplicates_in_input

    if not pending:
        return {"submitted": 0, "skipped": skipped, "errors": 0, "duration_s": 0.0}

    chunks = [pending[i : i + chunk_size] for i in range(0, len(pending), chunk_size)]
    max_workers = workers or min(14, os.cpu_count() or 4)

    t0 = time.time()
    total_errors = 0
    with ProcessPoolExecutor(max_workers=max_workers) as pool:
        futures = [
            pool.submit(
                _run_chunk,
                chunk,
                campaign_id=campaign_id,
                round_no=round_no,
                root=root,
                chunk_idx=i,
            )
            for i, chunk in enumerate(chunks)
        ]
        for future in as_completed(futures):
            result = future.result()
            total_errors += result["errors"]

    return {
        "submitted": len(pending),
        "skipped": skipped,
        "errors": total_errors,
        "duration_s": time.time() - t0,
        "platform": platform.system(),
    }
