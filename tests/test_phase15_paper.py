"""Phase 15 P5: paper trading and the kill switch.

Paper trading is a forward test: only bars after promotion count. The kill
switch stops every paper run and blocks promotion, Eve can engage it but
never release it, and the gate refuses trading calls when it cannot read the
switch at all.
"""

from __future__ import annotations

import asyncio
import sqlite3
from datetime import timedelta

import polars as pl
import pytest

from mcp.quant_server import paper_tools, store_tools
from mcp.quant_server import store as store_mod
from mcp.quant_server.audit import MemoryAuditSink
from mcp.quant_server.auth import Principal
from mcp.quant_server.gate import Gate, GateError
from mcp.quant_server.policy import TOOL_POLICY
from mcp.quant_server.registry import ALL_TOOL_FUNCTIONS
from mcp.quant_server.store import SqliteStore
from mcp.quant_server.strategy_tools import EXAMPLE_SPEC
from tests._spec_fixtures import intraday_candles

A = Principal(kind="user", user_id="aaaaaaaa-0000-0000-0000-000000000001", access_token="ta")


def _write_month(root, month: str, shift_days: int, seed: int) -> None:
    d = root / month / "15m"
    d.mkdir(parents=True, exist_ok=True)
    intraday_candles(seed=seed).with_columns(
        pl.col("timestamp") + timedelta(days=shift_days)
    ).write_parquet(d / "candles.parquet")


@pytest.fixture
def env(tmp_path, monkeypatch):
    db = tmp_path / "store.sqlite"
    store_mod.set_store_factory(lambda p: SqliteStore(db, p.user_id))
    for fn in (
        store_tools.backtest_saved_strategy,
        store_tools.evaluate_saved_strategy,
        paper_tools.paper_results,
    ):
        monkeypatch.setattr(fn, "__defaults__", (*fn.__defaults__[:-1], str(tmp_path)))
    _write_month(tmp_path, "2026-07", 0, 7)
    _write_month(tmp_path, "2026-08", 31, 11)
    g = Gate(tools={fn.__name__: fn for fn in ALL_TOOL_FUNCTIONS}, audit=MemoryAuditSink())
    yield g, db, tmp_path
    store_mod.set_store_factory(None)


def call(gate, name, args, surface="ui"):
    return asyncio.run(gate.invoke(name, args, A, surface=surface))["result"]


def _evaluated(gate) -> str:
    sid = call(gate, "save_strategy", {"name": "Cross", "spec": EXAMPLE_SPEC})["strategy_id"]
    call(gate, "backtest_saved_strategy", {"strategy_id": sid, "month": "2026-07"})
    call(gate, "evaluate_saved_strategy", {"strategy_id": sid, "holdout_month": "2026-08"})
    return sid


def _backdate_paper_start(db, sid: str, iso: str) -> None:
    with sqlite3.connect(db) as conn:
        conn.execute("update algo_strategies set paper_started_at = ? where id = ?", (iso, sid))


def test_no_tool_can_place_a_live_order() -> None:
    assert not [n for n, p in TOOL_POLICY.items() if p.tier == "trade_live"]
    assert TOOL_POLICY["promote_to_paper"].tier == "trade_paper"


def test_promotion_is_ui_only_and_needs_the_honest_check(env) -> None:
    gate, _, _ = env
    sid = call(gate, "save_strategy", {"name": "X", "spec": EXAMPLE_SPEC})["strategy_id"]
    with pytest.raises(GateError) as chat:
        call(gate, "promote_to_paper", {"strategy_id": sid}, surface="chat")
    assert chat.value.status == 403
    call(gate, "backtest_saved_strategy", {"strategy_id": sid, "month": "2026-07"})
    with pytest.raises(GateError) as info:
        call(gate, "promote_to_paper", {"strategy_id": sid})
    assert "honest check" in info.value.message


def test_promote_then_new_version_stops_paper(env) -> None:
    gate, _, _ = env
    sid = _evaluated(gate)
    out = call(gate, "promote_to_paper", {"strategy_id": sid})
    assert out["status"] == "paper" and out["paper_started_at"]
    risk = {**EXAMPLE_SPEC["risk"], "stop": {"mode": "pct", "value": 0.5}}
    tighter = {**EXAMPLE_SPEC, "risk": risk}
    call(gate, "revise_strategy", {"strategy_id": sid, "base_version": 1, "spec": tighter})
    got = call(gate, "get_my_strategy", {"strategy_id": sid})["strategy"]
    assert got["status"] != "paper" and got["paper_started_at"] is None


def test_paper_results_only_trade_bars_after_promotion(env) -> None:
    gate, db, _ = env
    sid = _evaluated(gate)
    call(gate, "promote_to_paper", {"strategy_id": sid})
    waiting = call(gate, "paper_results", {"strategy_id": sid}, surface="chat")
    assert waiting["status"] == "waiting" and waiting["bars"] == 0

    _backdate_paper_start(db, sid, "2026-08-10T00:00:00+00:00")
    first = call(gate, "paper_results", {"strategy_id": sid}, surface="chat")
    assert first["status"] == "updated" and first["bars"] > 0
    aug = intraday_candles(seed=11).with_columns(pl.col("timestamp") + timedelta(days=31))
    after = aug.filter(pl.col("timestamp") > pl.datetime(2026, 8, 10)).height
    assert first["bars"] == after
    again = call(gate, "paper_results", {"strategy_id": sid}, surface="chat")
    assert again["status"] == "unchanged"
    kinds = [b["kind"] for b in call(gate, "get_my_strategy", {"strategy_id": sid})["backtests"]]
    assert kinds.count("paper") == 1


def test_paper_results_are_not_counted_as_trials(env) -> None:
    gate, db, _ = env
    sid = _evaluated(gate)
    call(gate, "promote_to_paper", {"strategy_id": sid})
    _backdate_paper_start(db, sid, "2026-08-10T00:00:00+00:00")
    before = call(gate, "get_my_strategy", {"strategy_id": sid})["strategy"]["trial_count"]
    call(gate, "paper_results", {"strategy_id": sid})
    after = call(gate, "get_my_strategy", {"strategy_id": sid})["strategy"]["trial_count"]
    assert before == after


def test_kill_switch_stops_paper_and_blocks_promotion(env) -> None:
    gate, _, _ = env
    sid = _evaluated(gate)
    call(gate, "promote_to_paper", {"strategy_id": sid})
    out = call(gate, "engage_kill_switch", {"reason": "market is wild"}, surface="chat")
    assert out["engaged"] and out["stopped_paper_runs"] == [sid]
    with pytest.raises(GateError) as info:
        call(gate, "promote_to_paper", {"strategy_id": sid})
    assert info.value.status == 423 and "market is wild" in info.value.message


def test_eve_can_engage_but_never_release(env) -> None:
    gate, _, _ = env
    call(gate, "engage_kill_switch", {}, surface="chat")
    with pytest.raises(GateError) as info:
        call(gate, "release_kill_switch", {}, surface="chat")
    assert info.value.status == 403
    assert call(gate, "trading_controls", {}, surface="chat")["engaged"] is True
    released = call(gate, "release_kill_switch", {})
    assert released["engaged"] is False


def test_the_gate_fails_closed_when_the_switch_cannot_be_read(env) -> None:
    gate, _, _ = env
    sid = _evaluated(gate)

    class Broken(SqliteStore):
        def get_controls(self):
            raise RuntimeError("database unreachable")

    db = env[1]
    store_mod.set_store_factory(lambda p: Broken(db, p.user_id))
    with pytest.raises(GateError) as info:
        call(gate, "promote_to_paper", {"strategy_id": sid})
    assert info.value.status == 423 and "could not be checked" in info.value.message


def test_cutoff_is_read_in_ist_like_the_candles(env) -> None:
    gate, db, _ = env
    sid = _evaluated(gate)
    call(gate, "promote_to_paper", {"strategy_id": sid})
    # 04:30 UTC is 10:00 IST: the 09:15-10:00 IST bars of that day must not count.
    _backdate_paper_start(db, sid, "2026-08-10T04:30:00+00:00")
    out = call(gate, "paper_results", {"strategy_id": sid})
    aug = intraday_candles(seed=11).with_columns(pl.col("timestamp") + timedelta(days=31))
    assert out["bars"] == aug.filter(pl.col("timestamp") > pl.datetime(2026, 8, 10, 10, 0)).height
