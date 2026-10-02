"""Paper trading and the kill switch (Phase 15, P5).

Paper trading here is a forward test with no money and no broker: a
strategy version is frozen when it is promoted, and from then on only bars
that arrive AFTER that moment count. ``paper_results`` replays the frozen
rules over those bars with the same engine as every backtest, so the result
cannot have been tuned on them. Nothing in this module places an order; the
``trade_live`` tier is denied by the gate and no tool uses it.

The kill switch stops every paper run at once (a database trigger does it,
so it holds even if this process is down) and blocks new promotions. Eve may
ENGAGE it from chat; releasing it is a deliberate click in Hisaab only.
"""

from __future__ import annotations

from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import Any

import polars as pl

from mcp.quant_server.auth import require_principal
from mcp.quant_server.server import (
    DEFAULT_PROCESSED_ROOT,
    _available_months,
    _json_safe,
    _metrics_brief,
    _processed_candles,
)
from mcp.quant_server.store import StoreError, new_id, store_for
from mcp.quant_server.store_tools import ENGINE_VERSION, _strategy_or_404, _version_row
from quant.backtest.engine import run_backtest
from quant.strategies.spec import NIFTY_LOT_SIZE, parse_spec, spec_backtest_config, spec_signals


def _store():
    return store_for(require_principal())


# Candles are stored as naive IST (quant/data/upstox.py, dhan.py).
IST = timezone(timedelta(hours=5, minutes=30))


def _parse_ts(value: str) -> datetime:
    ts = datetime.fromisoformat(value.replace("Z", "+00:00"))
    return ts if ts.tzinfo else ts.replace(tzinfo=timezone.utc)


def _controls_summary(rows: list[dict[str, Any]], user_id: str | None) -> dict[str, Any]:
    own = next((r for r in rows if r.get("user_id") == user_id), None)
    glob = next((r for r in rows if r.get("user_id") is None), None)
    return {
        "engaged": any(bool(r.get("kill_switch")) for r in rows),
        "own": {"engaged": bool(own["kill_switch"]), "reason": own.get("reason")} if own else
        {"engaged": False, "reason": None},
        "global": {"engaged": bool(glob["kill_switch"]), "reason": glob.get("reason")} if glob else
        {"engaged": False, "reason": None},
    }


# ------------------------------------------------------------------ paper


def promote_to_paper(strategy_id: str) -> dict[str, object]:
    """Start paper trading the current version (Hisaab UI only).

    Needs a backtest and an honest check (evaluate_saved_strategy) on the
    current version, and no kill switch engaged. The rules are frozen from
    now: saving a new version stops the paper run."""
    store = _store()
    strategy = _strategy_or_404(store, strategy_id)
    if strategy["status"] == "paper":
        return _json_safe({"strategy_id": strategy_id, "status": "paper",
                           "paper_started_at": strategy.get("paper_started_at"),
                           "message": "already paper trading"})
    row = _version_row(store, strategy, 0)
    runs = store.list_backtests([row["id"]])
    holdout = next((b for b in runs if b.get("kind") == "holdout"), None)
    if holdout is None:
        raise StoreError(
            "run the honest check (evaluate_saved_strategy) on this version first, so the "
            "verdict is on record before paper trading starts"
        )
    updated = store.update_strategy(strategy_id, {"status": "paper"})
    return _json_safe(
        {
            "strategy_id": strategy_id,
            "version": row["version"],
            "status": updated["status"],
            "paper_started_at": updated.get("paper_started_at"),
            "verdict_at_promotion": (holdout.get("verdict") or {}).get("label"),
            "message": "paper trading started: only bars after this moment will count",
        }
    )


def stop_paper(strategy_id: str) -> dict[str, object]:
    """Stop paper trading a strategy (Hisaab UI only). Results so far are kept."""
    store = _store()
    strategy = _strategy_or_404(store, strategy_id)
    if strategy["status"] != "paper":
        raise StoreError("this strategy is not paper trading")
    updated = store.update_strategy(strategy_id, {"status": "backtested"})
    return _json_safe({"strategy_id": strategy_id, "status": updated["status"]})


def paper_results(
    strategy_id: str,
    processed_root: str = str(DEFAULT_PROCESSED_ROOT),
) -> dict[str, object]:
    """Forward-test results of a paper-trading strategy: its frozen rules
    replayed over only the bars processed since it was promoted. Recorded as
    a paper run when there is new data. Not a trial: nothing was tuned."""
    store = _store()
    strategy = _strategy_or_404(store, strategy_id)
    if strategy["status"] != "paper" or not strategy.get("paper_started_at"):
        raise StoreError("this strategy is not paper trading")
    started = _parse_ts(strategy["paper_started_at"])
    row = _version_row(store, strategy, 0)
    spec = parse_spec(row["spec"])

    root = Path(processed_root)
    frames = []
    for month in _available_months(root):
        if (root / month / spec.timeframe / "candles.parquet").exists():
            frames.append(_processed_candles(month, spec.timeframe, root))
    if not frames:
        raise ValueError("no processed data for this strategy's timeframe")
    candles = pl.concat(frames).unique("timestamp").sort("timestamp")
    # Signals are computed over all history (indicators need warm-up), then
    # only bars after promotion are traded.
    signals = spec_signals(candles, spec)
    # Compare in the candles' own clock: a UTC cutoff read as IST would let
    # up to 5.5 hours of bars from BEFORE promotion into the forward test.
    cutoff = started.astimezone(IST).replace(tzinfo=None)
    keep = pl.col("timestamp") > pl.lit(cutoff).cast(candles["timestamp"].dtype)
    fwd_candles = candles.filter(keep)
    base = {
        "strategy_id": strategy_id,
        "version": row["version"],
        "paper_started_at": strategy["paper_started_at"],
        "timeframe": spec.timeframe,
    }
    if fwd_candles.height < 2:
        last = candles["timestamp"][-1]
        return _json_safe(
            {
                **base,
                "status": "waiting",
                "bars": fwd_candles.height,
                "latest_data": last,
                "message": "no bars since paper trading started; results appear as new "
                "months are downloaded and processed",
            }
        )
    result = run_backtest(fwd_candles, signals.filter(keep), spec_backtest_config(spec))
    until = fwd_candles["timestamp"][-1]
    metrics = _metrics_brief(result.metrics)
    previous = next(
        (b for b in store.list_backtests([row["id"]]) if b.get("kind") == "paper"), None
    )
    recorded = None
    if previous is None or (previous.get("params") or {}).get("until") != str(until):
        recorded = store.insert_backtest(
            {
                "id": new_id(),
                "strategy_version_id": row["id"],
                "user_id": store.user_id,
                "kind": "paper",
                "params": {
                    "since": strategy["paper_started_at"],
                    "until": str(until),
                    "timeframe": spec.timeframe,
                    "lot_size": NIFTY_LOT_SIZE,
                    "lots": spec.sizing.lots,
                },
                "metrics": metrics,
                "verdict": {"bars": fwd_candles.height},
                "engine_version": ENGINE_VERSION,
                "data_version": str(until),
                "run_card_hash": row["spec_hash"],
                "status": "ok",
            }
        )["id"]
    return _json_safe(
        {
            **base,
            "status": "updated" if recorded else "unchanged",
            "bars": fwd_candles.height,
            "until": until,
            "metrics": metrics,
            "backtest_id": recorded,
        }
    )


# ------------------------------------------------------------------ kill switch


def trading_controls() -> dict[str, object]:
    """Is a kill switch engaged for the signed-in user (their own or the
    global one), and why."""
    store = _store()
    return _json_safe(_controls_summary(store.get_controls(), store.user_id))


def engage_kill_switch(reason: str = "") -> dict[str, object]:
    """Engage the user's kill switch: every paper-trading strategy stops at
    once and none can start until the user releases it in Hisaab. Call this
    whenever the user asks to stop, halt or pause trading. Eve cannot release
    it."""
    store = _store()
    before = [s["id"] for s in store.list_strategies("paper")]
    store.set_own_kill_switch(True, (reason or "engaged")[:500])
    after = {s["id"] for s in store.list_strategies("paper")}
    stopped = [sid for sid in before if sid not in after]
    return _json_safe(
        {
            **_controls_summary(store.get_controls(), store.user_id),
            "stopped_paper_runs": stopped,
            "released_by": "the Hisaab app only",
        }
    )


def release_kill_switch() -> dict[str, object]:
    """Release the user's own kill switch (Hisaab UI only). Paper runs it
    stopped stay stopped; promote them again deliberately."""
    store = _store()
    store.set_own_kill_switch(False, None)
    return _json_safe(_controls_summary(store.get_controls(), store.user_id))


PAPER_TOOL_FUNCTIONS = (
    promote_to_paper,
    stop_paper,
    paper_results,
    trading_controls,
    engage_kill_switch,
    release_kill_switch,
)
