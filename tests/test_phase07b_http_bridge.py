"""Phase 07b unit tests: the HTTP bridge over the quant tools.

Uses Starlette's TestClient, so no server process and no network. The tools
themselves read real processed parquet, so tests that would need data are
skipped when it is absent rather than failing on a fresh clone.
"""

from __future__ import annotations

from pathlib import Path

import pytest
from starlette.testclient import TestClient

from mcp.quant_server.http_bridge import (
    _INTERNAL_PARAMS,
    _TOOLS,
    _WRITE_TOOLS,
    WRITE_TOOLS_ENABLED,
    build_app,
    tool_manifest,
)
from mcp.quant_server.server import TOOL_NAMES

PROCESSED = (
    Path(__file__).resolve().parents[1]
    / "data"
    / "processed"
    / "futures"
    / "NIFTY"
    / "2026-07"
    / "15m"
    / "candles.parquet"
)
needs_data = pytest.mark.skipif(
    not PROCESSED.exists(), reason="processed 2026-07 15m parquet not present"
)


@pytest.fixture(scope="module")
def client() -> TestClient:
    return TestClient(build_app())


def test_health_reports_every_served_tool(client: TestClient) -> None:
    body = client.get("/health").json()
    assert body["ok"] is True
    assert body["tools"] == len(_TOOLS)


def test_manifest_covers_the_mcp_tool_set_minus_write_tools() -> None:
    """The bridge and the MCP server must expose the same READ tools.

    Both read ``_TOOL_FUNCTIONS``, so this pins that they cannot drift apart,
    while the write tools stay withheld unless explicitly enabled.
    """
    expected = set(TOOL_NAMES)
    if not WRITE_TOOLS_ENABLED:
        expected -= _WRITE_TOOLS
    assert {entry["name"] for entry in tool_manifest()} == expected


@pytest.mark.skipif(WRITE_TOOLS_ENABLED, reason="write tools deliberately enabled")
def test_write_tools_are_withheld_by_default() -> None:
    """Prompt-level 'ask first' is not enforcement.

    ``process_month_data`` overwrites parquet under ``data/processed/``. A
    model that ignores the system prompt must still not be able to reach it,
    so the gate lives in the bridge rather than in the wording.
    """
    assert not ({e["name"] for e in tool_manifest()} & _WRITE_TOOLS)


@pytest.mark.skipif(WRITE_TOOLS_ENABLED, reason="write tools deliberately enabled")
def test_calling_a_withheld_write_tool_is_403_with_the_remedy(
    client: TestClient,
) -> None:
    res = client.post("/tools/process_month_data", json={"year": 2026, "month": 7})
    assert res.status_code == 403
    assert "QUANT_ALLOW_WRITE_TOOLS" in res.json()["error"]


def test_manifest_never_exposes_filesystem_parameters() -> None:
    """Path arguments must not be model-controllable.

    ``processed_root`` and friends default to the project's data directories;
    letting a generated payload set them would turn a chat turn into arbitrary
    filesystem access.
    """
    for entry in tool_manifest():
        assert not (set(entry["parameters"]["properties"]) & _INTERNAL_PARAMS), entry["name"]


def test_manifest_entries_are_well_formed_json_schema() -> None:
    for entry in tool_manifest():
        schema = entry["parameters"]
        assert schema["type"] == "object"
        assert schema["additionalProperties"] is False
        assert entry["description"], f"{entry['name']} has no description"
        # Every required name must actually be a declared property.
        assert set(schema["required"]) <= set(schema["properties"])
        # A parameter is required exactly when it has no default.
        for name, prop in schema["properties"].items():
            assert (name in schema["required"]) == ("default" not in prop)


def test_unknown_tool_is_a_404_listing_the_real_ones(client: TestClient) -> None:
    body = client.post("/tools/not_a_tool", json={}).json()
    assert "unknown tool" in body["error"]
    assert set(body["available"]) == set(_TOOLS)


def test_malformed_body_is_rejected(client: TestClient) -> None:
    assert client.post("/tools/list_research_months", content=b"{oops").status_code == 400
    assert client.post("/tools/list_research_months", json=[1, 2]).status_code == 400


def test_empty_body_is_treated_as_no_arguments(client: TestClient) -> None:
    res = client.post("/tools/list_research_months", content=b"")
    assert res.status_code == 200
    assert "months" in res.json()["result"]


@needs_data
def test_backtest_returns_engine_metrics(client: TestClient) -> None:
    res = client.post(
        "/tools/run_backtest_signals", json={"month": "2026-07", "timeframe": "15m"}
    )
    assert res.status_code == 200
    body = res.json()
    assert body["tool"] == "run_backtest_signals"
    metrics = body["result"]["metrics"]
    for key in ("total_trades", "net_pnl", "profit_factor", "sharpe"):
        assert key in metrics


@needs_data
def test_unknown_and_path_arguments_are_stripped_not_fatal(client: TestClient) -> None:
    """A hallucinated argument must be ignored and reported, never a 500."""
    res = client.post(
        "/tools/run_backtest_signals",
        json={
            "month": "2026-07",
            "timeframe": "15m",
            "processed_root": "C:/somewhere/else",
            "hallucinated": 1,
        },
    )
    assert res.status_code == 200
    assert res.json()["ignored_arguments"] == ["hallucinated", "processed_root"]


def test_engine_errors_come_back_as_actionable_400s(client: TestClient) -> None:
    """The model can correct a bad month itself, so the message matters."""
    res = client.post("/tools/run_backtest_signals", json={"month": "1999-01"})
    assert res.status_code == 400
    assert "not found" in res.json()["error"].lower()


def test_missing_required_argument_is_a_400(client: TestClient) -> None:
    res = client.post("/tools/run_backtest_signals", json={})
    assert res.status_code == 400
    assert "TypeError" in res.json()["error"]
