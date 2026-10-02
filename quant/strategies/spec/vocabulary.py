"""The closed indicator vocabulary a spec may use (Phase 15).

Each entry declares typed parameter bounds, its outputs, its warm-up length
and how to compute it as a causal Polars expression. ``describe_strategy_
vocabulary`` publishes this table to the model and the Hisaab form, so the
bounds the model is told about are the bounds the validator enforces.
"""

from __future__ import annotations

from collections.abc import Callable, Mapping
from dataclasses import dataclass, field
from typing import Any

import polars as pl

from quant.indicators.angle import DEGREES_PER_RADIAN
from quant.indicators.atr import atr_expr
from quant.indicators.bollinger import bollinger_exprs
from quant.indicators.macd import macd_exprs
from quant.indicators.rsi import rsi_expr
from quant.indicators.sma import sma_expr


@dataclass(frozen=True)
class ParamDef:
    type: str  # "int" | "float"
    min: float
    max: float
    default: float
    description: str = ""

    def coerce(self, value: float) -> float | int:
        return int(value) if self.type == "int" else float(value)


@dataclass(frozen=True)
class IndicatorDef:
    name: str
    label: str
    description: str
    params: Mapping[str, ParamDef]
    outputs: tuple[str, ...]
    needs: tuple[str, ...]
    warmup: Callable[[Mapping[str, float]], int]
    compute: Callable[[Mapping[str, Any], str | None], pl.Expr]
    examples: tuple[str, ...] = field(default=())

    def resolved_params(self, given: Mapping[str, float]) -> dict[str, float | int]:
        return {
            k: p.coerce(given[k]) if k in given else p.coerce(p.default)
            for k, p in self.params.items()
        }

    def to_public(self) -> dict[str, Any]:
        return {
            "name": self.name,
            "label": self.label,
            "description": self.description,
            "params": {
                k: {
                    "type": p.type,
                    "min": p.min,
                    "max": p.max,
                    "default": p.default,
                    "description": p.description,
                }
                for k, p in self.params.items()
            },
            "outputs": list(self.outputs) or None,
            "examples": list(self.examples),
        }


def _ema(period: int, source: pl.Expr | None = None) -> pl.Expr:
    src = pl.col("close") if source is None else source
    return src.ewm_mean(alpha=2.0 / (period + 1), adjust=False, min_samples=period)


def _ema_angle(p: Mapping[str, Any], _: str | None) -> pl.Expr:
    ema = _ema(int(p["period"]))
    prev = ema.shift(int(p["lookback"]))
    return ((ema - prev) / prev * 1000.0).arctan() * DEGREES_PER_RADIAN


def _macd(p: Mapping[str, Any], output: str | None) -> pl.Expr:
    line, sig, hist = macd_exprs(int(p["fast"]), int(p["slow"]), int(p["signal"]))
    return {"line": line, "signal": sig, "hist": hist}[output or "line"]


def _bbands(p: Mapping[str, Any], output: str | None) -> pl.Expr:
    upper, mid, lower = bollinger_exprs(int(p["period"]), float(p["stddev"]))
    return {"upper": upper, "mid": mid, "lower": lower}[output or "mid"]


_PERIOD = ParamDef("int", 2, 400, 20, "lookback in bars")

INDICATORS: dict[str, IndicatorDef] = {
    "ema": IndicatorDef(
        name="ema",
        label="EMA",
        description="Exponential moving average of the close.",
        params={"period": ParamDef("int", 2, 400, 20, "lookback in bars")},
        outputs=(),
        needs=("close",),
        warmup=lambda p: int(p["period"]),
        compute=lambda p, _: _ema(int(p["period"])),
        examples=("9 EMA crosses above 21 EMA", "close above the 200 EMA"),
    ),
    "sma": IndicatorDef(
        name="sma",
        label="SMA",
        description="Simple moving average of the close.",
        params={"period": _PERIOD},
        outputs=(),
        needs=("close",),
        warmup=lambda p: int(p["period"]),
        compute=lambda p, _: sma_expr(int(p["period"])),
        examples=("golden cross = SMA 50 crosses above SMA 200",),
    ),
    "rsi": IndicatorDef(
        name="rsi",
        label="RSI",
        description="Wilder RSI, 0-100. Oversold < 30, overbought > 70 by convention.",
        params={"period": ParamDef("int", 2, 100, 14, "lookback in bars")},
        outputs=(),
        needs=("close",),
        warmup=lambda p: int(p["period"]) + 1,
        compute=lambda p, _: rsi_expr(int(p["period"])),
        examples=("RSI(14) below 30 = oversold",),
    ),
    "macd": IndicatorDef(
        name="macd",
        label="MACD",
        description="MACD line, signal line and histogram (line - signal).",
        params={
            "fast": ParamDef("int", 2, 100, 12, "fast EMA"),
            "slow": ParamDef("int", 3, 200, 26, "slow EMA"),
            "signal": ParamDef("int", 2, 50, 9, "signal EMA of the line"),
        },
        outputs=("line", "signal", "hist"),
        needs=("close",),
        warmup=lambda p: int(p["slow"]) + int(p["signal"]),
        compute=_macd,
        examples=("MACD line crosses above its signal line", "MACD hist above 0"),
    ),
    "bbands": IndicatorDef(
        name="bbands",
        label="Bollinger Bands",
        description="SMA(period) +/- stddev x population standard deviation.",
        params={
            "period": ParamDef("int", 2, 200, 20, "lookback in bars"),
            "stddev": ParamDef("float", 0.5, 5.0, 2.0, "band width in standard deviations"),
        },
        outputs=("upper", "mid", "lower"),
        needs=("close",),
        warmup=lambda p: int(p["period"]),
        compute=_bbands,
        examples=("close crosses below the lower band",),
    ),
    "atr": IndicatorDef(
        name="atr",
        label="ATR",
        description="Wilder average true range, in points.",
        params={"period": ParamDef("int", 2, 100, 14, "lookback in bars")},
        outputs=(),
        needs=("high", "low", "close"),
        warmup=lambda p: int(p["period"]) + 1,
        compute=lambda p, _: atr_expr(int(p["period"])),
    ),
    "ema_angle": IndicatorDef(
        name="ema_angle",
        label="EMA angle",
        description="Steepness of an EMA in degrees (the incumbent Eve filter). "
        "Positive = rising. 30 deg is the house default threshold.",
        params={
            "period": ParamDef("int", 2, 400, 9, "EMA period"),
            "lookback": ParamDef("int", 1, 20, 1, "bars used for the slope"),
        },
        outputs=(),
        needs=("close",),
        warmup=lambda p: int(p["period"]) + int(p["lookback"]),
        compute=_ema_angle,
        examples=("9 EMA angle above 30 degrees",),
    ),
}

PRICE_FIELDS = ("open", "high", "low", "close", "volume")
LEVELS = {
    "prev_day_high": "Previous completed session's high",
    "prev_day_low": "Previous completed session's low",
    "prev_day_close": "Previous completed session's close",
    "session_open": "Today's first open",
    "session_high": "Today's high so far (up to this bar)",
    "session_low": "Today's low so far (up to this bar)",
    "vwap": "Session-anchored VWAP",
}
CHANGE_REFS = {
    "prev_day_close": "percent change of the close vs yesterday's close",
    "session_open": "percent change of the close vs today's open",
    "prev_bar_close": "percent change of the close vs the previous bar's close",
}
COMPARATORS = {
    "gt": "lhs > rhs",
    "gte": "lhs >= rhs",
    "lt": "lhs < rhs",
    "lte": "lhs <= rhs",
    "crosses_above": "lhs was <= rhs on the previous bar and is > rhs now",
    "crosses_below": "lhs was >= rhs on the previous bar and is < rhs now",
    "rising": "lhs is higher than `bars` bars ago",
    "falling": "lhs is lower than `bars` bars ago",
}


def public_vocabulary() -> dict[str, Any]:
    return {
        "schema_version": "eve.strategy/1",
        "indicators": [d.to_public() for d in INDICATORS.values()],
        "price_fields": list(PRICE_FIELDS),
        "levels": LEVELS,
        "change_refs": CHANGE_REFS,
        "comparators": COMPARATORS,
        "timeframes": ["1m", "5m", "15m"],
        "directions": ["long_only", "short_only", "both"],
        "stop_modes": {"pct": "percent of entry", "points": "index points", "atr": "ATR x value"},
        "target_modes": {
            "pct": "percent of entry",
            "points": "index points",
            "atr": "ATR x value",
            "r_multiple": "multiple of the stop distance",
        },
        "trail_modes": {"atr": "trail by ATR x value", "breakeven_then_atr": "breakeven at 1R"},
        "limits": {
            "max_conditions_per_list": 8,
            "max_offset_bars": 50,
            "max_lots": 50,
        },
    }
