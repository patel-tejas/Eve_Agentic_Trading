"""Phase 15 P2: saved strategies, versions and backtests, per user.

The SQLite stand-in exercises the full tool flow through the gate. The
Supabase client is checked against a mock PostgREST: it must act as the user
(their token, never the service key) and scope every query to them. The RLS
policies themselves are verified in Hisaab: scripts/sql/verify-algo-rls.sql.
"""

from __future__ import annotations

import asyncio
import json

import httpx
import pytest

from mcp.quant_server import store as store_mod
from mcp.quant_server.audit import MemoryAuditSink
from mcp.quant_server.auth import Principal
from mcp.quant_server.gate import Gate, GateError
from mcp.quant_server.registry import ALL_TOOL_FUNCTIONS
from mcp.quant_server.store import SqliteStore, SupabaseStore
from mcp.quant_server.strategy_tools import EXAMPLE_SPEC
from tests._spec_fixtures import cond, const, ind, long_spec, write_processed

A = Principal(kind="user", user_id="aaaaaaaa-0000-0000-0000-000000000001", access_token="ta")
B = Principal(kind="user", user_id="bbbbbbbb-0000-0000-0000-000000000002", access_token="tb")


@pytest.fixture
def gate(tmp_path, monkeypatch):
    db = tmp_path / "store.sqlite"
    store_mod.set_store_factory(lambda p: SqliteStore(db, p.user_id))
    # processed_root is an internal parameter the gate never lets a caller
    # set, so point the tool's default at the fixture data instead.
    from mcp.quant_server import store_tools

    fn = store_tools.backtest_saved_strategy
    monkeypatch.setattr(fn, "__defaults__", (*fn.__defaults__[:-1], str(tmp_path)))
    write_processed(tmp_path)
    g = Gate(tools={fn.__name__: fn for fn in ALL_TOOL_FUNCTIONS}, audit=MemoryAuditSink())
    yield g
    store_mod.set_store_factory(None)


def call(gate: Gate, name: str, args: dict, principal=A, surface="chat"):
    return asyncio.run(gate.invoke(name, args, principal, surface=surface))["result"]


def test_save_list_get_round_trip(gate) -> None:
    saved = call(gate, "save_strategy", {"name": "Cross", "spec": EXAMPLE_SPEC})
    assert saved["status"] == "saved" and saved["strategy_status"] == "validated"
    listed = call(gate, "list_my_strategies", {})
    assert listed["count"] == 1 and listed["strategies"][0]["version"] == 1
    got = call(gate, "get_my_strategy", {"strategy_id": saved["strategy_id"]})
    assert got["version"]["spec_hash"] == saved["spec_hash"]
    assert got["version"]["summary"].startswith("Long-only NIFTY")


def test_save_is_idempotent_on_spec_hash(gate) -> None:
    first = call(gate, "save_strategy", {"name": "One", "spec": EXAMPLE_SPEC})
    renamed = {**EXAMPLE_SPEC, "name": "different label", "meta": {"source": "form"}}
    again = call(gate, "save_strategy", {"name": "Two", "spec": renamed, "source": "form"})
    assert again["status"] == "exists"
    assert again["strategy_id"] == first["strategy_id"]
    assert call(gate, "list_my_strategies", {})["count"] == 1


def test_duplicate_name_is_a_400(gate) -> None:
    call(gate, "save_strategy", {"name": "Same", "spec": EXAMPLE_SPEC})
    other = long_spec([cond(ind("rsi"), "lt", const(30))])
    with pytest.raises(GateError) as info:
        call(gate, "save_strategy", {"name": "Same", "spec": other})
    assert info.value.status == 400 and "already have" in info.value.message


def test_revise_creates_an_immutable_new_version_with_a_diff(gate) -> None:
    saved = call(gate, "save_strategy", {"name": "R", "spec": EXAMPLE_SPEC})
    tighter = json.loads(json.dumps(EXAMPLE_SPEC))
    tighter["risk"]["stop"]["value"] = 0.5
    rev = call(gate, "revise_strategy",
               {"strategy_id": saved["strategy_id"], "base_version": 1, "spec": tighter})
    assert rev["version"] == 2 and rev["trial_count"] == 1
    assert rev["diff"]["changes"] == [
        {"path": "/risk/stop/value", "before": 1.0, "after": 0.5, "op": "replace"}
    ]
    got = call(gate, "get_my_strategy", {"strategy_id": saved["strategy_id"], "version": 1})
    assert got["version"]["spec"]["risk"]["stop"]["value"] == 1.0  # v1 untouched
    assert got["versions"][0]["changes"][0]["path"] == "/risk/stop/value"


def test_revise_with_a_stale_base_is_refused(gate) -> None:
    saved = call(gate, "save_strategy", {"name": "S", "spec": EXAMPLE_SPEC})
    tighter = json.loads(json.dumps(EXAMPLE_SPEC))
    tighter["risk"]["stop"]["value"] = 0.7
    call(gate, "revise_strategy",
         {"strategy_id": saved["strategy_id"], "base_version": 1, "spec": tighter})
    tighter["risk"]["stop"]["value"] = 0.6
    with pytest.raises(GateError, match="stale base_version"):
        call(gate, "revise_strategy",
             {"strategy_id": saved["strategy_id"], "base_version": 1, "spec": tighter})


def test_backtest_is_recorded_against_the_exact_version(gate) -> None:
    saved = call(gate, "save_strategy", {"name": "BT", "spec": EXAMPLE_SPEC})
    bt = call(gate, "backtest_saved_strategy",
              {"strategy_id": saved["strategy_id"], "month": "2026-07"})
    assert bt["strategy_status"] == "backtested" and bt["trial_count"] == 1
    got = call(gate, "get_my_strategy", {"strategy_id": saved["strategy_id"]})
    assert got["backtests"][0]["metrics"] == bt["metrics"]
    listed = call(gate, "list_my_strategies", {})["strategies"][0]
    assert listed["latest_backtest"]["net_pnl"] == bt["metrics"]["net_pnl"]


def test_user_b_cannot_read_or_revise_user_a_even_with_the_id(gate) -> None:
    saved = call(gate, "save_strategy", {"name": "Mine", "spec": EXAMPLE_SPEC})
    sid = saved["strategy_id"]
    assert call(gate, "list_my_strategies", {}, principal=B)["count"] == 0
    for name, args in (
        ("get_my_strategy", {"strategy_id": sid}),
        ("revise_strategy", {"strategy_id": sid, "base_version": 1, "spec": EXAMPLE_SPEC}),
        ("backtest_saved_strategy", {"strategy_id": sid}),
    ):
        with pytest.raises(GateError) as info:
            call(gate, name, args, principal=B)
        assert info.value.status == 400 and "no strategy" in info.value.message


def test_model_supplied_user_id_is_ignored(gate) -> None:
    saved = call(gate, "save_strategy",
                 {"name": "X", "spec": EXAMPLE_SPEC, "user_id": B.user_id})
    assert call(gate, "list_my_strategies", {}, principal=B)["count"] == 0
    assert call(gate, "get_my_strategy", {"strategy_id": saved["strategy_id"]})["strategy"]


def test_archive_is_ui_only(gate) -> None:
    saved = call(gate, "save_strategy", {"name": "Old", "spec": EXAMPLE_SPEC})
    with pytest.raises(GateError) as info:
        call(gate, "archive_strategy", {"strategy_id": saved["strategy_id"]})
    assert info.value.status == 403
    out = call(gate, "archive_strategy", {"strategy_id": saved["strategy_id"]}, surface="ui")
    assert out["status"] == "archived"


def test_store_tools_need_a_user(gate) -> None:
    with pytest.raises(GateError) as info:
        call(gate, "list_my_strategies", {}, principal=Principal(kind="anonymous"))
    assert info.value.status == 401


# ------------------------------------------------------------------ PostgREST client


def test_supabase_store_acts_as_the_user_and_scopes_every_query() -> None:
    seen: list[httpx.Request] = []

    def handler(request: httpx.Request) -> httpx.Response:
        seen.append(request)
        return httpx.Response(200, json=[])

    client = httpx.Client(transport=httpx.MockTransport(handler))
    s = SupabaseStore("https://x.supabase.co", "anon-key", "user-jwt", A.user_id, client=client)
    s.list_strategies("validated")
    s.get_strategy("sid")
    s.list_versions("sid")
    s.find_version_by_hash("h")
    for req in seen:
        assert req.headers["authorization"] == "Bearer user-jwt"
        assert req.headers["apikey"] == "anon-key"
        assert req.url.params["user_id"] == f"eq.{A.user_id}"
    assert seen[0].url.path == "/rest/v1/algo_strategies"
    assert seen[0].url.params["status"] == "eq.validated"


def test_supabase_rls_refusal_maps_to_permission_error() -> None:
    def handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(403, json={"code": "42501", "message": "new row violates RLS"})

    client = httpx.Client(transport=httpx.MockTransport(handler))
    s = SupabaseStore("https://x.supabase.co", "k", "t", A.user_id, client=client)
    with pytest.raises(PermissionError):
        s.insert_strategy({"id": "x", "user_id": A.user_id, "name": "n"})


def test_unconfigured_storage_is_an_actionable_error(monkeypatch) -> None:
    monkeypatch.delenv("SUPABASE_URL", raising=False)
    monkeypatch.delenv("SUPABASE_ANON_KEY", raising=False)
    with pytest.raises(ValueError, match="SUPABASE_URL"):
        store_mod.default_store_factory(A)
