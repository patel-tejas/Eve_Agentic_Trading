"""Phase 07c unit tests: the numeric grounding check.

The failure mode that kills a check like this is FALSE POSITIVES -- flag
``2026-07`` as an unsourced number once and the feature gets switched off. So
the negative cases (things that must NOT be flagged) come first and outnumber
the positives.
"""

from __future__ import annotations

import pytest
from starlette.testclient import TestClient

from mcp.quant_server.grounding import (
    check_grounding,
    collect_evidence,
    extract_claims,
)
from mcp.quant_server.http_bridge import build_app, tool_manifest

# Shaped like a real run_backtest_signals result, with the genuine float noise.
TOOL_RESULT = {
    "month": "2026-07",
    "timeframe": "15m",
    "config": {
        "fast_ema": 9,
        "slow_ema": 15,
        "angle_threshold": 30.0,
        "angle_lookback": 1,
        "signal_mode": "crossover_and_angle",
    },
    "metrics": {
        "total_trades": 4,
        "win_rate": 0.25,
        "gross_pnl": 7080.000000000291,
        "net_pnl": 5736.63671700029,
        "profit_factor": 1.3511033969749748,
        "max_drawdown_pct": 0.026346088232638676,
        "sharpe": 0.954907717843873,
    },
}


@pytest.fixture(scope="module")
def client() -> TestClient:
    return TestClient(build_app())


# ---------------------------------------------------------------- masks
# Everything here is prose structure or an identifier, never a numeric claim.


@pytest.mark.parametrize(
    "text",
    [
        "Data covers 2026-07 and 2026-08.",
        "The window runs 2026-07-15 to 2026-07-31.",
        "Bar timestamp 2026-07-15T09:15:00 was the last one.",
        "Timeframes are 1m, 5m and 15m.",
        "1. First point\n2. Second point\n3. Third point",
        "1) Alpha\n2) Beta",
        "See phase-08b, phase 04 and phase-13.",
        "The session runs 09:15 to 15:30:00.",
    ],
)
def test_structural_numbers_are_not_claims(text: str) -> None:
    assert extract_claims(text) == []


def test_table_alignment_row_is_not_a_claim() -> None:
    table = "| Metric | Value |\n|---|---:|\n| Trades | 4 |"
    assert [c.text for c in extract_claims(table)] == ["4"]


def test_identifier_suffixes_are_not_claims() -> None:
    """A digit glued to a word is part of a name, not a quantity."""
    assert extract_claims("Use EMA9 and RE-0042 with x2 leverage.") == []


# ---------------------------------------------------------------- evidence


def test_evidence_walks_nested_structures() -> None:
    values = collect_evidence(TOOL_RESULT)
    assert 4 in values
    assert 9 in values  # nested under config
    assert pytest.approx(0.25) in values
    assert pytest.approx(5736.63671700029) in values


def test_evidence_ignores_booleans_and_non_numeric_strings() -> None:
    """``True`` is not the number 1 -- counting it would ground a bogus '1'."""
    values = collect_evidence({"ok": True, "mode": "crossover", "n": 3})
    assert values == [3.0]


def test_evidence_reads_numeric_strings() -> None:
    assert collect_evidence({"bars": "575"}) == [575.0]


def test_evidence_survives_deeply_nested_payloads() -> None:
    payload: object = 7.5
    for _ in range(10):
        payload = {"nested": [payload]}
    assert collect_evidence(payload) == [7.5]


# ---------------------------------------------------------------- matching


def test_display_rounding_counts_as_grounded() -> None:
    """₹5,736.64 is 5736.63671700029 written for a human."""
    report = check_grounding("Net P&L was ₹5,736.64.", TOOL_RESULT)
    assert report.grounded
    assert report.ungrounded == []


@pytest.mark.parametrize(
    "claim",
    ["5736.63671700029", "5736.64", "5736.6", "5,737", "5737"],
)
def test_the_same_value_grounds_at_every_rounding(claim: str) -> None:
    assert check_grounding(f"Net P&L {claim}.", TOOL_RESULT).grounded


def test_percentages_ground_against_their_fraction() -> None:
    """A win rate is stored 0.25 and written 25%."""
    report = check_grounding("Win rate 25% and drawdown 2.6%.", TOOL_RESULT)
    assert report.grounded, report.ungrounded


def test_a_realistic_honest_answer_is_fully_grounded() -> None:
    answer = """On 2026-07 at the 15m timeframe, EMA 9/15 with a 30.0 angle
threshold produced 4 trades.

| Metric | Value |
|---|---|
| Net P&L | ₹5,736.64 |
| Win rate | 25% |
| Profit factor | 1.35 |
| Sharpe | 0.95 |
| Max drawdown | 2.6% |

1. Costs use normal slippage.
"""
    report = check_grounding(answer, [TOOL_RESULT])
    assert report.grounded, report.ungrounded
    assert report.total_claims >= 8


# ---------------------------------------------------------------- catches


def test_fabricated_figures_are_all_flagged() -> None:
    """The case this module exists for: numbers no tool ever produced."""
    report = check_grounding(
        "Returned ₹98,400 across 61 trades, Sharpe 2.9, win rate 71%.",
        TOOL_RESULT,
    )
    assert not report.grounded
    assert report.grounded_claims == 0
    assert {c["text"] for c in report.ungrounded} == {"98,400", "61", "2.9", "71"}


def test_numbers_with_no_tool_call_at_all_are_flagged() -> None:
    report = check_grounding("Sharpe was 1.8 over 42 trades.", [])
    assert not report.grounded
    assert report.evidence_values == 0
    assert len(report.ungrounded) == 2


def test_one_bad_figure_among_good_ones_is_isolated() -> None:
    report = check_grounding(
        "There were 4 trades and the Sharpe was 3.7.", TOOL_RESULT
    )
    assert not report.grounded
    assert [c["text"] for c in report.ungrounded] == ["3.7"]
    assert report.grounded_claims == 1


def test_an_answer_without_numbers_is_trivially_grounded() -> None:
    report = check_grounding("No processed data exists for that month.", TOOL_RESULT)
    assert report.grounded
    assert report.total_claims == 0
    assert "No numeric claims" in report.summary()


def test_report_is_deterministic_and_identifies_the_draft() -> None:
    a = check_grounding("Sharpe 0.95.", TOOL_RESULT)
    b = check_grounding("Sharpe 0.95.", TOOL_RESULT)
    assert a.to_dict() == b.to_dict()
    assert len(a.answer_sha256) == 64
    assert a.answer_sha256 != check_grounding("Sharpe 0.96.", TOOL_RESULT).answer_sha256


# ---------------------------------------------------------------- endpoint


def test_grounding_is_not_offered_as_a_tool() -> None:
    """The model must never be able to call its own grader.

    If grounding ever lands in ``_TOOL_FUNCTIONS`` it becomes callable, and a
    model could invoke it, read the verdict, and tune its answer to pass.
    """
    assert not any("ground" in entry["name"] for entry in tool_manifest())


def test_endpoint_returns_the_report(client: TestClient) -> None:
    res = client.post(
        "/grounding/check",
        json={"answer": "Net P&L ₹5,736.64 over 4 trades.", "tool_results": [TOOL_RESULT]},
    )
    assert res.status_code == 200
    body = res.json()
    assert body["grounded"] is True
    assert body["total_claims"] == 2
    assert "summary" in body


def test_endpoint_flags_fabrication(client: TestClient) -> None:
    res = client.post(
        "/grounding/check",
        json={"answer": "Sharpe was 4.2.", "tool_results": [TOOL_RESULT]},
    )
    assert res.json()["grounded"] is False
    assert res.json()["ungrounded"][0]["text"] == "4.2"


def test_endpoint_rejects_a_missing_or_non_string_answer(client: TestClient) -> None:
    assert client.post("/grounding/check", json={}).status_code == 400
    assert client.post("/grounding/check", json={"answer": 5}).status_code == 400
    assert client.post("/grounding/check", content=b"{oops").status_code == 400
