"""Semantic checks and normalisation for ``eve.strategy/1`` (Phase 15).

The pydantic model (``schema.py``) guarantees the *shape*. This module
checks the *meaning*: indicator parameters inside their bounds, outputs that
exist, contradictory ranges, a way out of every position, a sane session.

Every issue carries a JSON Pointer into the spec and a message that says how
to fix it, so the model (or the Hisaab form) can correct exactly that field.
``errors`` block a backtest; ``warnings`` are shown but do not.

``normalize`` fills every omitted indicator parameter with its default so
two specs that mean the same thing serialise -- and hash -- the same, whether
they came from chat or from the form.
"""

from __future__ import annotations

import json
from dataclasses import asdict, dataclass
from typing import Any, Literal

from quant.strategies.spec.schema import (
    Condition,
    ConditionGroup,
    ConstOperand,
    IndicatorOperand,
    StrategySpecV1,
)
from quant.strategies.spec.vocabulary import INDICATORS

Severity = Literal["error", "warning"]

# Dhan's auto square-off for index derivatives is 15:25; after the Closing
# Auction Session change (Aug 2026) brokers moved theirs earlier still. A
# squareoff later than this would be overtaken by the broker in real trading.
BROKER_SQUAREOFF = "15:25"
MAX_WARMUP_BARS = 300


@dataclass(frozen=True)
class Issue:
    path: str
    message: str
    severity: Severity = "error"
    kind: str = "invalid"

    def to_dict(self) -> dict[str, str]:
        return asdict(self)


class SpecError(ValueError):
    """A spec the engine refuses to run. ``issues`` reach the caller intact."""

    def __init__(self, issues: list[Issue]) -> None:
        self.issues = [i.to_dict() for i in issues]
        head = "; ".join(f"{i.path}: {i.message}" for i in issues[:6])
        more = f" (+{len(issues) - 6} more)" if len(issues) > 6 else ""
        super().__init__(f"strategy spec has {len(issues)} error(s): {head}{more}")


def _key(obj: Any) -> str:
    if hasattr(obj, "model_dump"):
        obj = obj.model_dump(mode="json")
    return json.dumps(obj, sort_keys=True)


def normalize(spec: StrategySpecV1) -> StrategySpecV1:
    """Copy of ``spec`` with every indicator's parameters fully resolved."""
    data = spec.model_dump(mode="json")

    def fix(operand: dict[str, Any] | None) -> None:
        if not operand or operand.get("kind") != "indicator":
            return
        definition = INDICATORS.get(operand["name"])
        if definition is None:
            return
        given = {k: v for k, v in (operand.get("params") or {}).items() if k in definition.params}
        operand["params"] = {k: float(v) for k, v in definition.resolved_params(given).items()}
        if definition.outputs and not operand.get("output"):
            operand["output"] = definition.outputs[0]

    for block in ("entry", "exit"):
        for side in ("long", "short"):
            group = data[block].get(side)
            if not group:
                continue
            for lst in ("all", "any"):
                for cond in group.get(lst, []):
                    fix(cond.get("lhs"))
                    fix(cond.get("rhs"))
    return StrategySpecV1.model_validate(data)


def _iter_conditions(spec: StrategySpecV1):
    for block in ("entry", "exit"):
        rules = getattr(spec, block)
        for side in ("long", "short"):
            group: ConditionGroup | None = getattr(rules, side)
            if group is None:
                continue
            for lst in ("all", "any"):
                for i, cond in enumerate(getattr(group, lst)):
                    yield f"/{block}/{side}/{lst}/{i}", cond


def _check_indicator(path: str, op: IndicatorOperand) -> list[Issue]:
    issues: list[Issue] = []
    definition = INDICATORS[op.name]
    for key, value in op.params.items():
        pdef = definition.params.get(key)
        if pdef is None:
            issues.append(
                Issue(
                    f"{path}/params/{key}",
                    f"{op.name} has no parameter '{key}' "
                    f"(allowed: {', '.join(definition.params) or 'none'})",
                    kind="unknown_reference",
                )
            )
            continue
        if pdef.type == "int" and float(value) != int(value):
            issues.append(
                Issue(f"{path}/params/{key}", f"{op.name}.{key} must be a whole number")
            )
        if not pdef.min <= float(value) <= pdef.max:
            issues.append(
                Issue(
                    f"{path}/params/{key}",
                    f"{op.name}.{key} = {value:g} is outside {pdef.min:g}..{pdef.max:g}",
                    kind="out_of_range",
                )
            )
    if definition.outputs:
        if op.output is not None and op.output not in definition.outputs:
            issues.append(
                Issue(
                    f"{path}/output",
                    f"{op.name} output must be one of {', '.join(definition.outputs)}",
                    kind="unknown_reference",
                )
            )
    elif op.output is not None:
        issues.append(Issue(f"{path}/output", f"{op.name} has a single output; set output to null"))
    if op.name == "macd":
        p = definition.resolved_params(op.params)
        if p["fast"] >= p["slow"]:
            issues.append(
                Issue(f"{path}/params/fast", "MACD fast period must be shorter than slow")
            )
    return issues


def _bounds(cond: Condition) -> tuple[str, str, float] | None:
    """(lhs key, 'lo'|'hi', value) for a lhs-vs-constant inequality."""
    if not isinstance(cond.rhs, ConstOperand):
        return None
    value = cond.rhs.value
    if cond.cmp in ("gt", "gte"):
        return _key(cond.lhs), "lo", value
    if cond.cmp in ("lt", "lte"):
        return _key(cond.lhs), "hi", value
    return None


def check(spec: StrategySpecV1) -> list[Issue]:
    """All semantic issues, errors first."""
    issues: list[Issue] = []
    max_warmup = 0

    for path, cond in _iter_conditions(spec):
        for side_name, operand in (("lhs", cond.lhs), ("rhs", cond.rhs)):
            if isinstance(operand, IndicatorOperand):
                issues += _check_indicator(f"{path}/{side_name}", operand)
                definition = INDICATORS[operand.name]
                try:
                    warm = definition.warmup(definition.resolved_params(operand.params))
                    max_warmup = max(max_warmup, warm + operand.offset)
                except (KeyError, ValueError):
                    pass
                if operand.name == "rsi" and isinstance(cond.rhs, ConstOperand):
                    if not 0 <= cond.rhs.value <= 100:
                        issues.append(
                            Issue(f"{path}/rhs/value", "RSI is always between 0 and 100",
                                  severity="warning")
                        )
        if cond.rhs is not None and _key(cond.lhs) == _key(cond.rhs):
            issues.append(Issue(path, "lhs and rhs are the same operand; this never changes"))

    # Contradictory ranges inside one AND list: RSI > 70 AND RSI < 30.
    for block in ("entry", "exit"):
        for side in ("long", "short"):
            group = getattr(getattr(spec, block), side)
            if group is None:
                continue
            lo: dict[str, float] = {}
            hi: dict[str, float] = {}
            for cond in group.all:
                bound = _bounds(cond)
                if bound is None:
                    continue
                key, which, value = bound
                if which == "lo":
                    lo[key] = max(lo.get(key, value), value)
                else:
                    hi[key] = min(hi.get(key, value), value)
            for key in lo.keys() & hi.keys():
                if lo[key] >= hi[key]:
                    issues.append(
                        Issue(
                            f"/{block}/{side}/all",
                            f"contradictory conditions: the same value must be above "
                            f"{lo[key]:g} and below {hi[key]:g} at once",
                            kind="inconsistent_field",
                        )
                    )

    # Every position needs a way out.
    risk = spec.risk
    has_bracket = (
        risk.stop.mode != "none"
        or risk.target.mode != "none"
        or risk.trail.mode != "none"
        or risk.time_stop_bars is not None
    )
    for side in spec.sides:
        exit_group = getattr(spec.exit, side)
        # In a two-sided spec the opposite entry closes the position too
        # (the engine's "opposite signal exits" rule).
        has_rule_exit = (exit_group is not None and not exit_group.empty) or (
            spec.direction == "both"
        )
        if not has_rule_exit and not has_bracket and not spec.session.eod_squareoff:
            issues.append(
                Issue(
                    f"/exit/{side}",
                    f"a {side} position has no way to close: add an exit condition, "
                    "a stop/target, or end-of-day square-off",
                )
            )
        elif not has_rule_exit and not has_bracket:
            issues.append(
                Issue(
                    f"/exit/{side}",
                    f"{side} trades only close at the end-of-day square-off",
                    severity="warning",
                )
            )
    if risk.stop.mode == "none":
        issues.append(
            Issue("/risk/stop", "no stop-loss: a single bad day is unbounded", severity="warning")
        )
    if risk.stop.mode == "pct" and (risk.stop.value or 0) > 10:
        issues.append(Issue("/risk/stop/value", "a stop wider than 10% is unusual for intraday",
                            severity="warning"))

    session = spec.session
    if session.entry_end <= session.entry_start:
        issues.append(Issue("/session/entry_end", "entry window ends before it starts"))
    if session.entry_start < "09:15" or session.entry_end > "15:30":
        issues.append(
            Issue("/session", "entries must fall inside the NSE session 09:15-15:30")
        )
    if session.eod_squareoff:
        if session.entry_end > session.squareoff_time:
            issues.append(
                Issue("/session/entry_end", "entry window runs past the square-off time")
            )
        if session.squareoff_time > BROKER_SQUAREOFF:
            issues.append(
                Issue(
                    "/session/squareoff_time",
                    f"brokers auto square-off index derivatives by {BROKER_SQUAREOFF}",
                    severity="warning",
                )
            )

    if max_warmup > MAX_WARMUP_BARS:
        issues.append(
            Issue(
                "/entry",
                f"indicators need {max_warmup} bars to warm up; early sessions will "
                "produce no signals",
                severity="warning",
            )
        )

    issues.sort(key=lambda i: 0 if i.severity == "error" else 1)
    return issues


def warmup_bars(spec: StrategySpecV1) -> int:
    longest = 1
    for _, cond in _iter_conditions(spec):
        for operand in (cond.lhs, cond.rhs):
            if isinstance(operand, IndicatorOperand):
                definition = INDICATORS[operand.name]
                longest = max(
                    longest,
                    definition.warmup(definition.resolved_params(operand.params)) + operand.offset,
                )
    return longest


def errors(issues: list[Issue]) -> list[Issue]:
    return [i for i in issues if i.severity == "error"]
