"""Template-rendered plain-English summary of a spec (Phase 15).

Generated from the JSON by code, never by the model, so what the user reads
and approves is exactly what runs. Hisaab's ``lib/eve/spec/describe.ts``
mirrors this wording.
"""

from __future__ import annotations

from quant.strategies.spec.schema import (
    ChangePctOperand,
    Condition,
    ConditionGroup,
    ConstOperand,
    IndicatorOperand,
    LevelOperand,
    PriceOperand,
    StrategySpecV1,
)
from quant.strategies.spec.vocabulary import INDICATORS

_LEVEL_TEXT = {
    "prev_day_high": "yesterday's high",
    "prev_day_low": "yesterday's low",
    "prev_day_close": "yesterday's close",
    "session_open": "today's open",
    "session_high": "today's high so far",
    "session_low": "today's low so far",
    "vwap": "VWAP",
}
_REF_TEXT = {
    "prev_day_close": "yesterday's close",
    "session_open": "today's open",
    "prev_bar_close": "the previous bar's close",
}
_CMP_TEXT = {
    "gt": "is above",
    "gte": "is at or above",
    "lt": "is below",
    "lte": "is at or below",
    "crosses_above": "crosses above",
    "crosses_below": "crosses below",
}
_TF_TEXT = {"1m": "1-minute", "5m": "5-minute", "15m": "15-minute"}


def _num(v: float) -> str:
    return f"{v:g}"


def operand_text(op) -> str:
    if isinstance(op, ConstOperand):
        text = _num(op.value)
    elif isinstance(op, IndicatorOperand):
        definition = INDICATORS[op.name]
        params = definition.resolved_params(op.params)
        args = ",".join(_num(float(v)) for v in params.values())
        base = f"{definition.label}({args})"
        if op.name == "macd":
            out = op.output or "line"
            text = {"line": f"{base} line", "signal": f"{base} signal line",
                    "hist": f"{base} histogram"}[out]
        elif op.name == "bbands":
            out = op.output or "mid"
            text = {"upper": f"upper {base}", "mid": f"middle {base}",
                    "lower": f"lower {base}"}[out]
        else:
            text = base
    elif isinstance(op, PriceOperand):
        text = f"the {op.field}"
    elif isinstance(op, LevelOperand):
        text = _LEVEL_TEXT[op.name]
    elif isinstance(op, ChangePctOperand):
        text = f"the % change vs {_REF_TEXT[op.ref]}"
    else:  # pragma: no cover
        text = str(op)
    offset = getattr(op, "offset", 0)
    if offset:
        text += f" {offset} bar{'s' if offset != 1 else ''} ago"
    return text


def condition_text(cond: Condition) -> str:
    lhs = operand_text(cond.lhs)
    if cond.cmp in ("rising", "falling"):
        n = cond.bars or 1
        verb = "is rising" if cond.cmp == "rising" else "is falling"
        span = "vs the previous bar" if n == 1 else f"over {n} bars"
        return f"{lhs} {verb} {span}"
    rhs = operand_text(cond.rhs)
    if isinstance(cond.lhs, ChangePctOperand) and isinstance(cond.rhs, ConstOperand):
        rhs = f"{_num(cond.rhs.value)}%"
    return f"{lhs} {_CMP_TEXT[cond.cmp]} {rhs}"


def group_text(group: ConditionGroup | None) -> str:
    if group is None or group.empty:
        return ""
    parts = []
    if group.all:
        parts.append(" and ".join(condition_text(c) for c in group.all))
    if group.any:
        anys = [condition_text(c) for c in group.any]
        parts.append(anys[0] if len(anys) == 1 else "any of: " + "; ".join(anys))
    return ", and ".join(parts)


def _risk_text(spec: StrategySpecV1) -> list[str]:
    r = spec.risk
    out = []
    stop = {
        "pct": lambda v: f"Stop-loss {_num(v)}% from entry.",
        "points": lambda v: f"Stop-loss {_num(v)} points from entry.",
        "atr": lambda v: f"Stop-loss {_num(v)} x ATR from entry.",
    }
    target = {
        "pct": lambda v: f"Target {_num(v)}% from entry.",
        "points": lambda v: f"Target {_num(v)} points from entry.",
        "atr": lambda v: f"Target {_num(v)} x ATR from entry.",
        "r_multiple": lambda v: f"Target {_num(v)}R (x the stop distance).",
    }
    out.append(stop[r.stop.mode](r.stop.value) if r.stop.mode != "none" else "No stop-loss.")
    if r.target.mode != "none":
        out.append(target[r.target.mode](r.target.value))
    if r.trail.mode == "atr":
        out.append(f"Trailing stop {_num(r.trail.value)} x ATR.")
    elif r.trail.mode == "breakeven_then_atr":
        out.append(f"Stop moves to breakeven at 1R, then trails {_num(r.trail.value)} x ATR.")
    if r.time_stop_bars:
        out.append(f"Exit after {r.time_stop_bars} bars in the trade.")
    return out


def describe(spec: StrategySpecV1) -> str:
    direction = {"long_only": "Long-only", "short_only": "Short-only",
                 "both": "Long-and-short"}[spec.direction]
    lines = [
        f"{direction} NIFTY futures strategy on {_TF_TEXT[spec.timeframe]} bars.",
    ]
    if "long" in spec.sides:
        lines.append(f"Buy when {group_text(spec.entry.long)}.")
        if spec.exit.long and not spec.exit.long.empty:
            lines.append(f"Exit the long when {group_text(spec.exit.long)}.")
    if "short" in spec.sides:
        lines.append(f"Sell short when {group_text(spec.entry.short)}.")
        if spec.exit.short and not spec.exit.short.empty:
            lines.append(f"Cover the short when {group_text(spec.exit.short)}.")
    lines += _risk_text(spec)
    s = spec.session
    window = f"New entries {s.entry_start}-{s.entry_end}"
    if s.eod_squareoff:
        window += f"; square off at {s.squareoff_time}."
    else:
        window += "; positions may be held overnight."
    lines.append(window)
    lots = spec.sizing.lots
    lines.append(f"{lots} lot{'s' if lots != 1 else ''}, {spec.execution.slippage} slippage.")
    return " ".join(lines)
