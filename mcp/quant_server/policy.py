"""Per-tool policy for the common gate (Phase 15, P0).

Every tool the engine exposes -- on the MCP stdio server and on the HTTP
bridge alike -- has exactly one row here. The gate (``gate.py``) reads this
table to decide who may call a tool, how often, for how long, and whether the
model is even shown it. Both manifests are *derived* from this table, so the
two surfaces cannot drift apart.

Tiers, from least to most consequential:

``read``          reads processed data; no side effects
``compute``       runs the engine (signals, backtests); bounded CPU
``compute_heavy`` resampling tests and grid searches; tighter rate limit
``user_read``     reads the caller's own saved strategies (needs a user)
``user_write``    writes the caller's own saved strategies (needs a user)
``safety``        may only *stop* things (engage a kill switch)
``data_write``    downloads or overwrites research data; operator-only,
                  withheld unless ``QUANT_ALLOW_WRITE_TOOLS`` is set
``trade_paper``   paper-trading state changes; UI route only, never chat
``trade_live``    real orders. Hard-denied: no tool in this tier exists,
                  and the gate refuses the tier even if one is added.

Tool annotations such as ``readOnlyHint`` are hints a client may ignore; the
MCP spec says servers MUST enforce access control themselves. This table is
that enforcement, not a label.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Literal

Tier = Literal[
    "read",
    "compute",
    "compute_heavy",
    "user_read",
    "user_write",
    "safety",
    "data_write",
    "trade_paper",
    "trade_live",
]

# Tiers whose tools act on one user's own rows. An anonymous caller is
# refused with 401 before validation even runs.
USER_TIERS: frozenset[str] = frozenset({"user_read", "user_write", "safety", "trade_paper"})

# Tiers a kill switch blocks. Research (read/compute) keeps working while
# trading-adjacent state changes stop.
KILL_SWITCH_TIERS: frozenset[str] = frozenset({"trade_paper", "trade_live"})

# Never callable, whatever the flags say.
DENIED_TIERS: frozenset[str] = frozenset({"trade_live"})

# Calls per minute per (user, tier). A token bucket refills continuously, so
# a burst up to the limit is fine and a sustained loop is not.
DEFAULT_RATE_PER_MINUTE: dict[str, int] = {
    "read": 120,
    "compute": 30,
    "compute_heavy": 6,
    "user_read": 60,
    "user_write": 20,
    "safety": 10,
    "data_write": 5,
    "trade_paper": 5,
    "trade_live": 0,
}


@dataclass(frozen=True)
class ToolPolicy:
    """How the gate treats one tool."""

    tier: Tier
    # False keeps a tool out of every model-facing manifest. It stays
    # callable only from the Hisaab UI routes (``X-Eve-Surface: ui``), where
    # a human clicked a button. This is the structural form of "ask the user
    # first": the model cannot call what it is never offered.
    chat_visible: bool = True
    # None -> the bridge-wide default (QUANT_TOOL_TIMEOUT).
    timeout_s: float | None = None
    rate_per_minute: int | None = None

    @property
    def rate(self) -> int:
        if self.rate_per_minute is not None:
            return self.rate_per_minute
        return DEFAULT_RATE_PER_MINUTE[self.tier]

    @property
    def needs_user(self) -> bool:
        return self.tier in USER_TIERS


TOOL_POLICY: dict[str, ToolPolicy] = {
    # --- Phase 07/08 research tools ---------------------------------------
    "list_research_months": ToolPolicy("read"),
    "get_historical_candles": ToolPolicy("read"),
    "generate_signal": ToolPolicy("compute"),
    "run_backtest_signals": ToolPolicy("compute"),
    # Writes only into the engine's own results cache (never a caller path).
    "compare_timeframes": ToolPolicy("compute"),
    "parameter_search": ToolPolicy("compute_heavy"),
    "walk_forward_test": ToolPolicy("compute_heavy"),
    "backtest_significance": ToolPolicy("compute_heavy"),
    "validate_parameter_search": ToolPolicy("compute_heavy"),
    # --- operator-only data tools -----------------------------------------
    "download_month_data": ToolPolicy("data_write"),
    "process_month_data": ToolPolicy("data_write"),
    # Writes validation_report.json next to the raw data, so it is a write
    # tool even though its name reads like a check.
    "validate_dataset": ToolPolicy("data_write"),
    # --- Phase 15 strategy builder: stateless spec tools (P1) -------------
    "describe_strategy_vocabulary": ToolPolicy("read"),
    "validate_strategy_spec": ToolPolicy("read"),
    "preview_strategy_signals": ToolPolicy("compute"),
    "backtest_strategy_spec": ToolPolicy("compute"),
    "strategy_significance": ToolPolicy("compute_heavy"),
    # --- Phase 15 strategy builder: the user's saved strategies (P2) ------
    "list_my_strategies": ToolPolicy("user_read"),
    "get_my_strategy": ToolPolicy("user_read"),
    "save_strategy": ToolPolicy("user_write"),
    "revise_strategy": ToolPolicy("user_write"),
    "backtest_saved_strategy": ToolPolicy("user_write", rate_per_minute=10),
    "evaluate_saved_strategy": ToolPolicy("user_write", rate_per_minute=10),
    # Destructive-ish: a human clicks it in Hisaab; never offered to chat.
    "archive_strategy": ToolPolicy("user_write", chat_visible=False),
    # Paper trading and the kill switch (P5). No tool is in trade_live.
    "promote_to_paper": ToolPolicy("trade_paper", chat_visible=False),
    "stop_paper": ToolPolicy("user_write", chat_visible=False),
    "paper_results": ToolPolicy("user_write", rate_per_minute=10),
    "trading_controls": ToolPolicy("user_read"),
    # Eve may stop trading; only a click in Hisaab can resume it.
    "engage_kill_switch": ToolPolicy("safety"),
    "release_kill_switch": ToolPolicy("user_write", chat_visible=False),
}


def register_policy(name: str, policy: ToolPolicy) -> None:
    """Add a tool's policy row. Later phases register their tools here."""
    if name in TOOL_POLICY and TOOL_POLICY[name] != policy:
        raise ValueError(f"conflicting policy for tool {name!r}")
    TOOL_POLICY[name] = policy


def policy_for(name: str) -> ToolPolicy | None:
    return TOOL_POLICY.get(name)
