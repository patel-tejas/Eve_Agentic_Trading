"""Phase 15 P4: honest evaluation of a saved strategy.

The verdict must never flatter: too few trades, a losing holdout, or a
Sharpe that the number of tries explains each block a pass, and a holdout
month the strategy was already tuned on is refused outright.
"""

from __future__ import annotations

import asyncio
import json
from datetime import timedelta

import polars as pl
import pytest

from mcp.quant_server import store as store_mod
from mcp.quant_server import store_tools
from mcp.quant_server.audit import MemoryAuditSink
from mcp.quant_server.auth import Principal
from mcp.quant_server.gate import Gate, GateError
from mcp.quant_server.registry import ALL_TOOL_FUNCTIONS
from mcp.quant_server.store import SqliteStore
from mcp.quant_server.strategy_tools import EXAMPLE_SPEC
from quant.strategies.spec.evaluation import (
    MIN_TRADES,
    buy_and_hold,
    make_verdict,
    trials_adjusted_sharpe,
)
from tests._spec_fixtures import intraday_candles

A = Principal(kind="user", user_id="aaaaaaaa-0000-0000-0000-000000000001", access_token="ta")


def _write_month(root, month: str, shift_days: int, seed: int) -> None:
    d = root / month / "15m"
    d.mkdir(parents=True, exist_ok=True)
    c = intraday_candles(seed=seed).with_columns(
        pl.col("timestamp") + timedelta(days=shift_days)
    )
    c.write_parquet(d / "candles.parquet")


@pytest.fixture
def gate(tmp_path, monkeypatch):
    db = tmp_path / "store.sqlite"
    store_mod.set_store_factory(lambda p: SqliteStore(db, p.user_id))
    for fn in (store_tools.backtest_saved_strategy, store_tools.evaluate_saved_strategy):
        monkeypatch.setattr(fn, "__defaults__", (*fn.__defaults__[:-1], str(tmp_path)))
    _write_month(tmp_path, "2026-07", 0, 7)
    _write_month(tmp_path, "2026-08", 31, 11)
    g = Gate(tools={fn.__name__: fn for fn in ALL_TOOL_FUNCTIONS}, audit=MemoryAuditSink())
    yield g
    store_mod.set_store_factory(None)


def call(gate, name, args):
    return asyncio.run(gate.invoke(name, args, A, surface="chat"))["result"]


def _saved_and_backtested(gate) -> str:
    sid = call(gate, "save_strategy", {"name": "Cross", "spec": EXAMPLE_SPEC})["strategy_id"]
    call(gate, "backtest_saved_strategy", {"strategy_id": sid, "month": "2026-07"})
    return sid


# ------------------------------------------------------------------ pure rules


def _metrics(trades: int, net: float) -> dict:
    return {"total_trades": trades, "net_pnl": net}


def test_too_few_trades_wins_over_everything() -> None:
    v = make_verdict(
        trials=1,
        in_sample_metrics=_metrics(10, 5_000),
        holdout_metrics=_metrics(12, 4_000),
        in_sample_returns=[0.01] * 20,
        recorded_sharpes=[],
        benchmark=None,
        holdout_reused=False,
    )
    assert v.label == "too_few_trades"
    assert any(str(MIN_TRADES) in r for r in v.reasons)


def test_losing_holdout_fails_even_with_a_great_in_sample() -> None:
    v = make_verdict(
        trials=1,
        in_sample_metrics=_metrics(60, 90_000),
        holdout_metrics=_metrics(55, -1),
        in_sample_returns=[0.004, 0.006, 0.005, 0.007] * 10,
        recorded_sharpes=[],
        benchmark=None,
        holdout_reused=False,
    )
    assert v.label == "failed_holdout"


def test_more_trials_lower_the_deflated_sharpe() -> None:
    rets = [0.003, -0.001, 0.002, 0.004, -0.002, 0.001] * 4
    one = trials_adjusted_sharpe(rets, trials=1)["deflated_sharpe"]
    forty = trials_adjusted_sharpe(rets, trials=40)["deflated_sharpe"]
    assert forty < one


def test_a_strong_edge_on_few_tries_survives_and_says_so() -> None:
    rets = [0.004, 0.003, 0.005, 0.002, 0.004, 0.003, -0.001, 0.004] * 5
    v = make_verdict(
        trials=2,
        in_sample_metrics=_metrics(80, 50_000),
        holdout_metrics=_metrics(70, 30_000),
        in_sample_returns=rets,
        recorded_sharpes=[],
        benchmark={"gross_pnl": 10_000},
        holdout_reused=False,
    )
    assert v.label == "survived_holdout"
    assert "cannot establish an edge" in v.caveat


def test_profitable_but_behind_buy_and_hold_is_named() -> None:
    rets = [0.004, 0.003, 0.005, 0.002, 0.004, 0.003, -0.001, 0.004] * 5
    v = make_verdict(
        trials=1,
        in_sample_metrics=_metrics(80, 50_000),
        holdout_metrics=_metrics(70, 3_000),
        in_sample_returns=rets,
        recorded_sharpes=[],
        benchmark={"gross_pnl": 40_000},
        holdout_reused=False,
    )
    assert v.label == "lags_buy_and_hold"


def test_buy_and_hold_is_first_open_to_last_close_at_size() -> None:
    c = intraday_candles(days=2)
    bh = buy_and_hold(c, 65, 2)
    expected = (float(c["close"][-1]) - float(c["open"][0])) * 65 * 2
    assert bh["gross_pnl"] == pytest.approx(expected)


# ------------------------------------------------------------------ tool


def test_evaluate_needs_an_in_sample_backtest_first(gate) -> None:
    sid = call(gate, "save_strategy", {"name": "X", "spec": EXAMPLE_SPEC})["strategy_id"]
    with pytest.raises(GateError) as info:
        call(gate, "evaluate_saved_strategy", {"strategy_id": sid, "holdout_month": "2026-08"})
    assert info.value.status == 400 and "in-sample" in info.value.message


def test_holdout_month_must_be_unseen(gate) -> None:
    sid = _saved_and_backtested(gate)
    with pytest.raises(GateError) as info:
        call(gate, "evaluate_saved_strategy", {"strategy_id": sid, "holdout_month": "2026-07"})
    assert "not unseen" in info.value.message


def test_evaluate_records_a_holdout_and_counts_a_trial(gate) -> None:
    sid = _saved_and_backtested(gate)
    out = call(gate, "evaluate_saved_strategy", {"strategy_id": sid, "holdout_month": "2026-08"})
    v = out["verdict"]
    assert v["label"] in {
        "too_few_trades", "failed_holdout", "not_significant",
        "lags_buy_and_hold", "survived_holdout",
    }
    assert v["in_sample_month"] == "2026-07" and v["holdout_month"] == "2026-08"
    assert v["trials"] == 2 and out["trial_count"] == 2
    assert v["benchmark"]["gross_pnl"] is not None
    detail = call(gate, "get_my_strategy", {"strategy_id": sid})
    kinds = sorted(b["kind"] for b in detail["backtests"])
    assert kinds == ["holdout", "in_sample"]
    holdout = next(b for b in detail["backtests"] if b["kind"] == "holdout")
    assert holdout["verdict"]["label"] == v["label"]
    json.dumps(out)  # JSON-safe end to end


def test_a_reused_holdout_is_flagged(gate) -> None:
    sid = _saved_and_backtested(gate)
    call(gate, "evaluate_saved_strategy", {"strategy_id": sid, "holdout_month": "2026-08"})
    tighter = json.loads(json.dumps(EXAMPLE_SPEC))
    tighter["risk"]["stop"]["value"] = 0.6
    call(gate, "revise_strategy", {"strategy_id": sid, "base_version": 1, "spec": tighter})
    call(gate, "backtest_saved_strategy", {"strategy_id": sid, "month": "2026-07"})
    again = call(gate, "evaluate_saved_strategy", {"strategy_id": sid, "holdout_month": "2026-08"})
    assert again["verdict"]["holdout_reused"] is True
    assert any("no longer unseen" in r for r in again["verdict"]["reasons"])


def test_the_same_version_is_evaluated_once_per_month(gate) -> None:
    sid = _saved_and_backtested(gate)
    call(gate, "evaluate_saved_strategy", {"strategy_id": sid, "holdout_month": "2026-08"})
    with pytest.raises(GateError) as info:
        call(gate, "evaluate_saved_strategy", {"strategy_id": sid, "holdout_month": "2026-08"})
    assert "already evaluated" in info.value.message
