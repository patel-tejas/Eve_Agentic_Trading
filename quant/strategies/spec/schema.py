"""``eve.strategy/1``: the declarative strategy spec (Phase 15).

A user's strategy -- built by chatting with Eve or by filling in Hisaab's
form -- is *data* in this shape, never code. One registered strategy,
``rule_spec``, interprets every spec, so the model's job is "fill a typed
form", not "write trading code".

Design rules
- Closed vocabularies everywhere: indicator names, comparators, operand
  kinds, price fields and levels are enums. Indicator parameters are bounded
  by ``vocabulary.py``, not here, so the bounds live next to the code that
  computes them.
- Conditions are a FIXED-DEPTH group per side: an ``all`` list (AND) and an
  ``any`` list (at least one, if non-empty). No nesting -- this keeps tool
  schemas small for Groq, caps complexity, and makes diffs trivial.
- Every operand carries an ``offset`` of bars BACK, constrained ``>= 0``, so
  look-ahead is not expressible at all.
- The shape mirrors what the engine already supports: one instrument, one
  position, bar-close signals filled at the next bar's open, and the
  ``ExitConfig`` bracket exits. ``risk`` and ``session`` map 1:1 onto it.

Structural rules live in the model validators below. Semantic checks
(parameter bounds, contradictions, "no way to exit") live in ``semantic.py``
and come back as a list of issues with JSON-Pointer paths.
"""

from __future__ import annotations

import re
from typing import Annotated, Literal, Union

from pydantic import BaseModel, ConfigDict, Field, field_validator, model_validator

SCHEMA_VERSION = "eve.strategy/1"

IndicatorName = Literal["ema", "sma", "rsi", "macd", "bbands", "atr", "ema_angle"]
PriceField = Literal["open", "high", "low", "close", "volume"]
LevelName = Literal[
    "prev_day_high",
    "prev_day_low",
    "prev_day_close",
    "session_open",
    "session_high",
    "session_low",
    "vwap",
]
ChangeRef = Literal["prev_day_close", "session_open", "prev_bar_close"]
Comparator = Literal[
    "gt", "gte", "lt", "lte", "crosses_above", "crosses_below", "rising", "falling"
]
Timeframe = Literal["1m", "5m", "15m"]
Direction = Literal["long_only", "short_only", "both"]

MAX_OFFSET = 50
MAX_CONDITIONS_PER_LIST = 8

_HHMM = re.compile(r"^([01]\d|2[0-3]):[0-5]\d$")


class _Strict(BaseModel):
    model_config = ConfigDict(extra="forbid")


# ------------------------------------------------------------------ operands


class IndicatorOperand(_Strict):
    kind: Literal["indicator"]
    name: IndicatorName
    params: dict[str, float] = Field(
        default_factory=dict,
        description="Indicator parameters, e.g. {'period': 14}. Omitted ones take defaults.",
    )
    output: str | None = Field(
        default=None,
        description="For multi-output indicators: macd -> line|signal|hist; "
        "bbands -> upper|mid|lower. Null for single-output ones.",
    )
    offset: int = Field(default=0, ge=0, le=MAX_OFFSET, description="Bars back; 0 = this bar.")


class PriceOperand(_Strict):
    kind: Literal["price"]
    field: PriceField
    offset: int = Field(default=0, ge=0, le=MAX_OFFSET)


class LevelOperand(_Strict):
    kind: Literal["level"]
    name: LevelName
    offset: int = Field(default=0, ge=0, le=MAX_OFFSET)


class ConstOperand(_Strict):
    kind: Literal["const"]
    value: float


class ChangePctOperand(_Strict):
    """Percent move of the close from a reference, e.g. -2 = 2% below it."""

    kind: Literal["change_pct"]
    ref: ChangeRef
    offset: int = Field(default=0, ge=0, le=MAX_OFFSET)


Operand = Annotated[
    Union[IndicatorOperand, PriceOperand, LevelOperand, ConstOperand, ChangePctOperand],
    Field(discriminator="kind"),
]


class Condition(_Strict):
    lhs: Operand
    cmp: Comparator
    rhs: Operand | None = Field(
        default=None, description="Required except for rising/falling."
    )
    bars: int | None = Field(
        default=None,
        ge=1,
        le=MAX_OFFSET,
        description="rising/falling only: lhs higher/lower than `bars` bars ago.",
    )

    @model_validator(mode="after")
    def _shape(self) -> Condition:
        if self.cmp in ("rising", "falling"):
            if self.rhs is not None:
                raise ValueError(f"'{self.cmp}' compares lhs with its own past; drop rhs")
            if self.bars is None:
                self.bars = 1
        else:
            if self.rhs is None:
                raise ValueError(f"'{self.cmp}' needs an rhs operand")
            if self.bars is not None:
                raise ValueError("'bars' is only used with rising/falling")
        if isinstance(self.lhs, ConstOperand) and (
            self.rhs is None or isinstance(self.rhs, ConstOperand)
        ):
            raise ValueError("a condition needs at least one market operand, not only constants")
        return self


class ConditionGroup(_Strict):
    all: list[Condition] = Field(default_factory=list, max_length=MAX_CONDITIONS_PER_LIST)
    any: list[Condition] = Field(default_factory=list, max_length=MAX_CONDITIONS_PER_LIST)

    @property
    def empty(self) -> bool:
        return not self.all and not self.any


class SideRules(_Strict):
    long: ConditionGroup | None = None
    short: ConditionGroup | None = None


# ------------------------------------------------------------------ blocks


class Instrument(_Strict):
    symbol: Literal["NIFTY"] = "NIFTY"
    segment: Literal["FUT"] = "FUT"
    contract: Literal["near_month"] = "near_month"


class Stop(_Strict):
    mode: Literal["none", "pct", "points", "atr"] = "none"
    value: float | None = Field(
        default=None, description="pct: percent (1 = 1%); points; atr: ATR multiple."
    )


class Target(_Strict):
    mode: Literal["none", "pct", "points", "atr", "r_multiple"] = "none"
    value: float | None = None


class Trail(_Strict):
    mode: Literal["none", "atr", "breakeven_then_atr"] = "none"
    value: float | None = Field(default=None, description="ATR multiple for the trail.")


class Risk(_Strict):
    stop: Stop = Field(default_factory=Stop)
    target: Target = Field(default_factory=Target)
    trail: Trail = Field(default_factory=Trail)
    time_stop_bars: int | None = Field(default=None, ge=1, le=500)

    @model_validator(mode="after")
    def _values(self) -> Risk:
        for name, block in (("stop", self.stop), ("target", self.target), ("trail", self.trail)):
            if block.mode != "none" and (block.value is None or block.value <= 0):
                raise ValueError(f"{name}.value must be > 0 when {name}.mode is '{block.mode}'")
        if self.target.mode == "r_multiple" and self.stop.mode == "none":
            raise ValueError("an r_multiple target needs a stop to measure R from")
        return self


class Session(_Strict):
    entry_start: str = "09:15"
    entry_end: str = "15:00"
    eod_squareoff: bool = True
    squareoff_time: str = "15:15"

    @field_validator("entry_start", "entry_end", "squareoff_time")
    @classmethod
    def _hhmm(cls, v: str) -> str:
        if not _HHMM.match(v):
            raise ValueError(f"time must be HH:MM (24h), got {v!r}")
        return v


class Sizing(_Strict):
    lots: int = Field(default=1, ge=1, le=50)


class Execution(_Strict):
    slippage: Literal["ideal", "normal", "stress"] = "normal"


class Meta(_Strict):
    source: Literal["chat", "form", "import"] = "form"
    parent_version: int | None = None
    # JSON Pointers of every value Eve filled in without the user saying so.
    # The UI highlights them: never invent a stop silently.
    defaulted: list[str] = Field(default_factory=list, max_length=40)
    user_prompt: str | None = Field(default=None, max_length=2000)


# ------------------------------------------------------------------ spec


class StrategySpecV1(_Strict):
    """A complete, engine-runnable strategy. See the module docstring."""

    schema_version: Literal["eve.strategy/1"] = SCHEMA_VERSION
    name: str = Field(min_length=1, max_length=80)
    description: str | None = Field(default=None, max_length=500)
    instrument: Instrument = Field(default_factory=Instrument)
    timeframe: Timeframe = "15m"
    direction: Direction = "long_only"
    entry: SideRules
    exit: SideRules = Field(default_factory=SideRules)
    risk: Risk = Field(default_factory=Risk)
    session: Session = Field(default_factory=Session)
    sizing: Sizing = Field(default_factory=Sizing)
    execution: Execution = Field(default_factory=Execution)
    meta: Meta = Field(default_factory=Meta)

    @model_validator(mode="after")
    def _sides(self) -> StrategySpecV1:
        wants_long = self.direction in ("long_only", "both")
        wants_short = self.direction in ("short_only", "both")
        for side, wanted in (("long", wants_long), ("short", wants_short)):
            entry = getattr(self.entry, side)
            exit_ = getattr(self.exit, side)
            if wanted and (entry is None or entry.empty):
                raise ValueError(
                    f"direction is {self.direction!r} but entry.{side} has no conditions"
                )
            if not wanted and entry is not None and not entry.empty:
                raise ValueError(
                    f"direction is {self.direction!r} but entry.{side} has conditions"
                )
            if not wanted and exit_ is not None and not exit_.empty:
                raise ValueError(f"direction is {self.direction!r} but exit.{side} has conditions")
        return self

    @property
    def sides(self) -> tuple[str, ...]:
        return {"long_only": ("long",), "short_only": ("short",), "both": ("long", "short")}[
            self.direction
        ]
