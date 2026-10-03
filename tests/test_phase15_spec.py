"""Phase 15 P1: the eve.strategy/1 spec, its validator and the rule_spec compiler."""

from __future__ import annotations

import polars as pl
import pytest
from pydantic import ValidationError
from starlette.testclient import TestClient

from mcp.quant_server import http_bridge
from mcp.quant_server.strategy_tools import (
    EXAMPLE_SPEC,
    backtest_strategy_spec,
    describe_strategy_vocabulary,
    preview_strategy_signals,
    strategy_significance,
    validate_strategy_spec,
)
from quant.backtest.engine import BacktestConfig, run_backtest
from quant.strategies.base import get_strategy
from quant.strategies.spec import (
    StrategySpecV1,
    analyse,
    describe,
    spec_backtest_config,
    spec_hash,
    spec_signals,
)
from tests._spec_fixtures import cond, const, ind, intraday_candles, long_spec, write_processed

EMA_CROSS = {
    "name": "EMA 9/15 crossover",
    "timeframe": "15m",
    "direction": "both",
    "entry": {
        "long": {"all": [cond(ind("ema", period=9), "crosses_above", ind("ema", period=15))]},
        "short": {"all": [cond(ind("ema", period=9), "crosses_below", ind("ema", period=15))]},
    },
    "session": {"eod_squareoff": False, "entry_start": "09:15", "entry_end": "15:30"},
}


# ------------------------------------------------------------------ golden


def test_ema_spec_reproduces_the_registered_ema_strategy_bar_for_bar() -> None:
    """The compiler's acceptance gate: a spec encoding EMA 9/15 crossover must
    produce exactly the incumbent strategy's signals and backtest."""
    candles = intraday_candles(days=22)
    spec = analyse(EMA_CROSS).require_valid()

    ours = spec_signals(candles, spec)
    theirs = get_strategy("ema").generate_signals(
        candles, {"fast_ema": 9, "slow_ema": 15, "signal_mode": "crossover"}
    )
    assert ours["signal_type"].to_list() == theirs["signal_type"].to_list()
    assert (ours["signal_type"] != "HOLD").sum() > 4  # the fixture actually crosses

    cfg = BacktestConfig()
    a = run_backtest(candles, ours, cfg)
    b = run_backtest(candles, theirs, cfg)
    assert a.metrics == b.metrics
    assert a.trades.equals(b.trades)


def test_rule_spec_is_registered_for_the_sweep() -> None:
    candles = intraday_candles(days=5)
    out = get_strategy("rule_spec").generate_signals(candles, {"spec": EMA_CROSS})
    assert out.columns == ["timestamp", "signal_type", "stop_price", "target_price"]


# ------------------------------------------------------------------ schema


def test_negative_offsets_are_unrepresentable() -> None:
    bad = long_spec([cond(ind("ema", offset=-1, period=9), "gt", const(1))])
    with pytest.raises(ValidationError) as info:
        StrategySpecV1.model_validate(bad)
    assert any(e["loc"][-1] == "offset" for e in info.value.errors())


def test_unknown_fields_and_indicators_are_rejected() -> None:
    with pytest.raises(ValidationError):
        StrategySpecV1.model_validate(long_spec([cond(ind("supertrend"), "gt", const(1))]))
    with pytest.raises(ValidationError):
        StrategySpecV1.model_validate({**long_spec([cond(ind("rsi"), "lt", const(30))]),
                                       "leverage": 10})


def test_direction_must_match_the_entry_sides() -> None:
    with pytest.raises(ValidationError, match="entry.short has conditions"):
        StrategySpecV1.model_validate(
            {**EMA_CROSS, "direction": "long_only"}
        )


def test_r_multiple_target_needs_a_stop() -> None:
    with pytest.raises(ValidationError, match="r_multiple"):
        StrategySpecV1.model_validate(
            long_spec([cond(ind("rsi"), "lt", const(30))],
                      risk={"target": {"mode": "r_multiple", "value": 2}})
        )


# ------------------------------------------------------------------ semantics


def _paths(raw) -> dict[str, str]:
    return {i.path: i.severity for i in analyse(raw).issues}


def test_out_of_range_parameter_names_the_exact_path() -> None:
    a = analyse(long_spec([cond(ind("rsi", period=400), "lt", const(30))]))
    assert not a.valid
    assert a.errors[0].path == "/entry/long/all/0/lhs/params/period"
    assert "2..100" in a.errors[0].message


def test_unknown_parameter_and_output() -> None:
    paths = _paths(long_spec([
        cond(ind("rsi", length=14), "lt", const(30)),
        cond(ind("macd", output="banana"), "gt", const(0)),
    ]))
    assert "/entry/long/all/0/lhs/params/length" in paths
    assert "/entry/long/all/1/lhs/output" in paths


def test_contradictory_ranges_are_an_error() -> None:
    a = analyse(long_spec([
        cond(ind("rsi", period=14), "gt", const(70)),
        cond(ind("rsi", period=14), "lt", const(30)),
    ]))
    assert any(i.kind == "inconsistent_field" for i in a.errors)


def test_a_position_needs_a_way_out() -> None:
    raw = long_spec([cond(ind("rsi"), "lt", const(30))],
                    risk={"stop": {"mode": "none"}},
                    session={"eod_squareoff": False})
    assert _paths(raw)["/exit/long"] == "error"


def test_session_window_checks() -> None:
    raw = long_spec([cond(ind("rsi"), "lt", const(30))],
                    session={"entry_start": "14:00", "entry_end": "10:00"})
    assert _paths(raw)["/session/entry_end"] == "error"


def test_defaults_are_filled_so_chat_and_form_hash_the_same() -> None:
    sparse = long_spec([cond(ind("rsi"), "lt", const(30))], meta={"source": "chat"})
    explicit = long_spec([cond(ind("rsi", period=14), "lt", const(30))], name="other name",
                         meta={"source": "form", "user_prompt": "buy oversold"})
    a, b = analyse(sparse), analyse(explicit)
    assert spec_hash(a.spec) == spec_hash(b.spec)
    tweaked = analyse(long_spec([cond(ind("rsi", period=15), "lt", const(30))]))
    assert spec_hash(tweaked.spec) != spec_hash(a.spec)


def test_summary_is_template_rendered() -> None:
    spec = analyse(EXAMPLE_SPEC).require_valid()
    text = describe(spec)
    assert text.startswith("Long-only NIFTY futures strategy on 15-minute bars.")
    assert "Buy when EMA(9) crosses above EMA(21) and RSI(14) is below 70." in text
    assert "Stop-loss 1% from entry." in text and "Target 2R" in text


# ------------------------------------------------------------------ engine semantics


def test_long_only_exit_never_opens_a_short() -> None:
    candles = intraday_candles(days=22)
    spec = analyse(
        long_spec(
            [cond(ind("ema", period=5), "crosses_above", ind("ema", period=20))],
            [cond(ind("ema", period=5), "crosses_below", ind("ema", period=20))],
            risk={"stop": {"mode": "none"}},
        )
    ).require_valid()
    signals = spec_signals(candles, spec)
    assert set(signals["signal_type"].unique()) <= {"BUY", "EXIT_LONG", "HOLD"}
    result = run_backtest(candles, signals, spec_backtest_config(spec))
    assert result.trades.height > 0
    assert set(result.trades["direction"].unique()) == {"LONG"}


def test_risk_and_session_map_onto_exit_config() -> None:
    spec = analyse(EXAMPLE_SPEC).require_valid()
    exits = spec_backtest_config(spec).exits
    assert (exits.stop_mode, exits.stop_pct) == ("pct", 0.01)
    assert (exits.target_mode, exits.target_r_multiple) == ("r_multiple", 2.0)
    assert (exits.session_start, exits.session_end, exits.eod_squareoff) == (
        "09:30", "14:30", "15:15")


def test_pct_target_fires() -> None:
    candles = intraday_candles(days=22)
    spec = analyse(
        long_spec([cond({"kind": "price", "field": "close"}, "gt", ind("sma", period=10))],
                  risk={"stop": {"mode": "pct", "value": 0.3},
                        "target": {"mode": "pct", "value": 0.3}})
    ).require_valid()
    result = run_backtest(candles, spec_signals(candles, spec), spec_backtest_config(spec))
    assert "target" in set(result.trades["exit_reason"].to_list())


# ------------------------------------------------------------------ tools


def test_vocabulary_tool_lists_indicators_and_example() -> None:
    vocab = describe_strategy_vocabulary()
    names = {i["name"] for i in vocab["indicators"]}
    assert {"ema", "sma", "rsi", "macd", "bbands", "atr", "ema_angle"} <= names
    assert analyse(vocab["example"]).valid


def test_validate_tool_returns_issues_not_exceptions() -> None:
    bad = StrategySpecV1.model_validate(long_spec([cond(ind("rsi", period=400), "lt", const(30))]))
    out = validate_strategy_spec(bad)
    assert out["valid"] is False and out["summary"] is None
    assert out["errors"][0]["path"] == "/entry/long/all/0/lhs/params/period"


def test_backtest_preview_and_significance_tools(tmp_path) -> None:
    write_processed(tmp_path)
    spec = StrategySpecV1.model_validate(EXAMPLE_SPEC)
    root = str(tmp_path)
    preview = preview_strategy_signals(spec, month="2026-07", count=5, processed_root=root)
    assert preview["counts"]["BUY"] > 0
    bt = backtest_strategy_spec(spec, month="2026-07", include_trades=True, processed_root=root)
    assert bt["metrics"]["total_trades"] == len(bt["trades"])
    assert bt["lot_size"] == 65 and bt["spec_hash"] == preview["spec_hash"]
    sig = strategy_significance(spec, month="2026-07", iterations=50, processed_root=root)
    assert sig["metrics"] == bt["metrics"]


def test_bridge_returns_json_pointer_paths_for_a_bad_spec() -> None:
    client = TestClient(http_bridge.build_app())
    bad = long_spec([cond(ind("ema", offset=-2, period=9), "gt", const(1))])
    res = client.post("/tools/validate_strategy_spec", json={"spec": bad})
    assert res.status_code == 400
    paths = [i["path"] for i in res.json()["issues"]]
    assert any(p.startswith("/spec/entry/long/all/0/lhs") and p.endswith("offset") for p in paths)


def test_bridge_semantic_error_on_backtest_is_a_400_with_issues(tmp_path) -> None:
    client = TestClient(http_bridge.build_app())
    bad = long_spec([cond(ind("rsi", period=400), "lt", const(30))])
    res = client.post("/tools/backtest_strategy_spec", json={"spec": bad, "month": "2026-07"})
    assert res.status_code == 400
    assert res.json()["issues"][0]["path"] == "/entry/long/all/0/lhs/params/period"


def test_bridge_accepts_a_spec_passed_as_a_json_string() -> None:
    import json

    client = TestClient(http_bridge.build_app())
    res = client.post("/tools/validate_strategy_spec", json={"spec": json.dumps(EXAMPLE_SPEC)})
    assert res.status_code == 200
    assert res.json()["result"]["valid"] is True


def test_spec_signals_are_one_row_per_bar() -> None:
    candles = intraday_candles(days=3)
    out = spec_signals(candles, analyse(EXAMPLE_SPEC).require_valid())
    assert out.height == candles.height
    assert out.schema["timestamp"] == pl.Datetime("ms")
