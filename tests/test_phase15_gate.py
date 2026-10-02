"""Phase 15 P0: the common gate in front of every tool, on both surfaces.

Network-free. JWTs are minted locally with the HS256 legacy-secret path, which
exercises the same claim checks as the JWKS path.
"""

from __future__ import annotations

import asyncio
import time

import jwt
import pytest
from fastmcp import Client
from starlette.testclient import TestClient

from mcp.quant_server import http_bridge
from mcp.quant_server.audit import MemoryAuditSink
from mcp.quant_server.auth import ANONYMOUS, Principal, current_principal
from mcp.quant_server.gate import Controls, Gate, GateError
from mcp.quant_server.policy import TOOL_POLICY, ToolPolicy
from mcp.quant_server.registry import ALL_TOOL_FUNCTIONS
from mcp.quant_server.server import build_server

SECRET = "test-internal-secret"
JWT_SECRET = "test-jwt-secret-which-is-long-enough-for-hs256"
SUPABASE_URL = "https://example.supabase.co"
USER_A = "11111111-1111-1111-1111-111111111111"


def _token(sub: str = USER_A, **overrides: object) -> str:
    claims = {
        "sub": sub,
        "aud": "authenticated",
        "role": "authenticated",
        "iss": f"{SUPABASE_URL}/auth/v1",
        "exp": int(time.time()) + 600,
        **overrides,
    }
    return jwt.encode(claims, JWT_SECRET, algorithm="HS256")


@pytest.fixture
def secured(monkeypatch: pytest.MonkeyPatch) -> TestClient:
    monkeypatch.setenv("EVE_INTERNAL_SECRET", SECRET)
    monkeypatch.setenv("SUPABASE_JWT_SECRET", JWT_SECRET)
    monkeypatch.setenv("SUPABASE_URL", SUPABASE_URL)
    monkeypatch.delenv("EVE_LOCAL_DEV", raising=False)
    return TestClient(http_bridge.build_app())


# ------------------------------------------------------------------ policy


def test_every_served_tool_has_exactly_one_policy_row() -> None:
    names = {fn.__name__ for fn in ALL_TOOL_FUNCTIONS}
    assert names <= set(TOOL_POLICY)


def test_no_live_trading_tool_is_registered_or_offered() -> None:
    live = {n for n, p in TOOL_POLICY.items() if p.tier == "trade_live"}
    assert not live & {fn.__name__ for fn in ALL_TOOL_FUNCTIONS}


def test_bridge_manifest_is_the_policy_derived_chat_set() -> None:
    names = {e["name"] for e in http_bridge.tool_manifest()}
    assert names == set(http_bridge.GATE.offered("chat"))
    for entry in http_bridge.tool_manifest():
        assert entry["tier"] == TOOL_POLICY[entry["name"]].tier


def test_stdio_manifest_matches_the_gate_and_hides_paths() -> None:
    async def listed() -> list:
        async with Client(build_server()) as client:
            return await client.list_tools()

    tools = asyncio.run(listed())
    gate = Gate(tools={fn.__name__: fn for fn in ALL_TOOL_FUNCTIONS}, audit=MemoryAuditSink())
    assert {t.name for t in tools} == set(gate.offered("mcp"))
    for tool in tools:
        props = set(tool.inputSchema.get("properties", {}))
        assert not props & {"processed_root", "raw_root", "results_root", "out_dir"}, tool.name


def test_stdio_write_tool_is_refused_without_the_flag(monkeypatch) -> None:
    monkeypatch.delenv("QUANT_ALLOW_WRITE_TOOLS", raising=False)
    gate = Gate(
        tools={fn.__name__: fn for fn in ALL_TOOL_FUNCTIONS},
        audit=MemoryAuditSink(),
        write_tools_enabled=False,
    )

    async def call() -> None:
        async with Client(build_server(gate)) as client:
            await client.call_tool("download_month_data", {"year": 2026, "month": 7})

    with pytest.raises(Exception) as info:
        asyncio.run(call())
    assert "QUANT_ALLOW_WRITE_TOOLS" in str(info.value)


def test_stdio_path_arguments_cannot_redirect_reads(tmp_path) -> None:
    """A client-chosen processed_root is dropped, not honoured."""
    gate = Gate(tools={fn.__name__: fn for fn in ALL_TOOL_FUNCTIONS}, audit=MemoryAuditSink())

    async def call():
        async with Client(build_server(gate)) as client:
            return await client.call_tool(
                "list_research_months", {"processed_root": str(tmp_path)}
            )

    result = asyncio.run(call())
    assert result.structured_content["ignored_arguments"] == ["processed_root"]


# ------------------------------------------------------------------ bridge auth


def test_missing_internal_secret_is_403(secured: TestClient) -> None:
    res = secured.post("/tools/list_research_months", json={})
    assert res.status_code == 403
    assert secured.get("/tools").status_code == 403


def test_bad_token_is_401(secured: TestClient) -> None:
    headers = {"x-eve-internal": SECRET, "authorization": "Bearer not-a-jwt"}
    assert secured.post("/tools/list_research_months", json={}, headers=headers).status_code == 401
    expired = _token(exp=int(time.time()) - 10)
    headers["authorization"] = f"Bearer {expired}"
    assert secured.post("/tools/list_research_months", json={}, headers=headers).status_code == 401
    wrong_aud = _token(aud="anon")
    headers["authorization"] = f"Bearer {wrong_aud}"
    assert secured.post("/tools/list_research_months", json={}, headers=headers).status_code == 401


def test_valid_secret_and_token_pass(secured: TestClient) -> None:
    headers = {"x-eve-internal": SECRET, "authorization": f"Bearer {_token()}"}
    res = secured.post("/tools/list_research_months", json={}, headers=headers)
    assert res.status_code == 200
    assert res.headers["x-request-id"]


def test_require_user_everywhere(secured: TestClient, monkeypatch) -> None:
    monkeypatch.setenv("EVE_REQUIRE_USER", "1")
    res = secured.post(
        "/tools/list_research_months", json={}, headers={"x-eve-internal": SECRET}
    )
    assert res.status_code == 401


# ------------------------------------------------------------------ gate pipeline


def _echo(n: int = 1, user_id: str = "") -> dict:
    """Echo the coerced argument and who the gate says is calling."""
    return {"n": n, "type": type(n).__name__, "as": current_principal().user_id}


def _save(name: str) -> dict:
    """Pretend user-tier write."""
    return {"saved": name, "by": current_principal().user_id}


def _promote(strategy_id: str) -> dict:
    """Pretend UI-only paper promotion."""
    return {"promoted": strategy_id}


def _order(qty: int) -> dict:
    """Must never run."""
    raise AssertionError("trade_live tool ran")


POLICY = {
    "echo": ToolPolicy("read"),
    "save": ToolPolicy("user_write", rate_per_minute=2),
    "promote": ToolPolicy("trade_paper", chat_visible=False),
    "order": ToolPolicy("trade_live"),
}


class _Killed(Controls):
    def kill_switch_reason(self, principal):
        return "test kill switch"


def _gate(**kw) -> tuple[Gate, MemoryAuditSink]:
    sink = MemoryAuditSink()
    gate = Gate(
        tools={"echo": _echo, "save": _save, "promote": _promote, "order": _order},
        policy=POLICY,
        audit=sink,
        **kw,
    )
    return gate, sink


USER = Principal(kind="user", user_id=USER_A, access_token="t")


def _run(gate: Gate, name: str, args: dict, principal=USER, **kw):
    return asyncio.run(gate.invoke(name, args, principal, **kw))


def test_arguments_are_coerced_and_identity_is_injected_not_trusted() -> None:
    gate, sink = _gate()
    out = _run(gate, "echo", {"n": "5", "user_id": "someone-else"})
    assert out["result"] == {"n": 5, "type": "int", "as": USER_A}
    assert out["ignored_arguments"] == ["user_id"]
    assert sink.records[-1].decision == "allow"
    assert sink.records[-1].user_id == USER_A


def test_invalid_argument_is_400_with_a_json_pointer() -> None:
    gate, sink = _gate()
    with pytest.raises(GateError) as info:
        _run(gate, "echo", {"n": "five"})
    assert info.value.status == 400
    assert info.value.extra["issues"][0]["path"] == "/n"
    assert sink.records[-1].decision == "deny"


def test_user_tier_without_a_user_is_401() -> None:
    gate, _ = _gate()
    with pytest.raises(GateError) as info:
        _run(gate, "save", {"name": "x"}, principal=ANONYMOUS)
    assert info.value.status == 401


def test_rate_limit_is_per_user_and_tier() -> None:
    gate, _ = _gate()
    _run(gate, "save", {"name": "a"})
    _run(gate, "save", {"name": "b"})
    with pytest.raises(GateError) as info:
        _run(gate, "save", {"name": "c"})
    assert info.value.status == 429
    other = Principal(kind="user", user_id="22222222-2222-2222-2222-222222222222")
    assert _run(gate, "save", {"name": "c"}, principal=other)["result"]["by"] == other.user_id


def test_ui_only_tool_is_hidden_from_chat_and_refused_there() -> None:
    gate, _ = _gate()
    assert "promote" not in gate.offered("chat")
    assert "promote" not in gate.offered("mcp")
    assert "promote" in gate.offered("ui")
    with pytest.raises(GateError) as info:
        _run(gate, "promote", {"strategy_id": "s"}, surface="chat")
    assert info.value.status == 403
    assert _run(gate, "promote", {"strategy_id": "s"}, surface="ui")["result"]["promoted"] == "s"


def test_trade_live_tier_is_hard_denied_everywhere() -> None:
    gate, _ = _gate()
    for surface in ("chat", "ui", "mcp"):
        assert "order" not in gate.offered(surface)
        with pytest.raises(GateError) as info:
            _run(gate, "order", {"qty": 1}, surface=surface)
        assert info.value.status == 403


def test_kill_switch_blocks_trading_tiers_only() -> None:
    gate, _ = _gate(controls=_Killed())
    with pytest.raises(GateError) as info:
        _run(gate, "promote", {"strategy_id": "s"}, surface="ui")
    assert info.value.status == 423
    assert _run(gate, "echo", {"n": 1})["result"]["n"] == 1


def test_unknown_tool_is_404_and_audited() -> None:
    gate, sink = _gate()
    with pytest.raises(GateError) as info:
        _run(gate, "nope", {})
    assert info.value.status == 404
    assert sink.records[-1].tool == "nope"


def test_audit_never_stores_secrets() -> None:
    gate, sink = _gate()
    _run(gate, "echo", {"n": 1, "access_token": "abc"})
    assert sink.records[-1].args_redacted["access_token"] == "[redacted]"
