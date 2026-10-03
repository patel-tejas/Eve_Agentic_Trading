"""``eve.strategy/1``: declarative user strategies (Phase 15).

Public surface::

    parse_spec(raw)            -> StrategySpecV1 (pydantic, structural checks)
    analyse(spec)              -> SpecAnalysis (normalised spec, issues, summary, hash)
    spec_signals(candles, spec)-> standard signal frame
    spec_backtest_config(spec) -> BacktestConfig with the spec's exits
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any

from quant.strategies.spec.compile import (
    NIFTY_LOT_SIZE,
    spec_backtest_config,
    spec_condition_frame,
    spec_exit_config,
    spec_signals,
)
from quant.strategies.spec.describe import describe
from quant.strategies.spec.hashing import spec_hash
from quant.strategies.spec.schema import SCHEMA_VERSION, StrategySpecV1
from quant.strategies.spec.semantic import Issue, SpecError, check, normalize, warmup_bars
from quant.strategies.spec.vocabulary import INDICATORS, public_vocabulary


def parse_spec(raw: Any) -> StrategySpecV1:
    if isinstance(raw, StrategySpecV1):
        return raw
    return StrategySpecV1.model_validate(raw)


@dataclass
class SpecAnalysis:
    spec: StrategySpecV1
    issues: list[Issue] = field(default_factory=list)

    @property
    def errors(self) -> list[Issue]:
        return [i for i in self.issues if i.severity == "error"]

    @property
    def warnings(self) -> list[Issue]:
        return [i for i in self.issues if i.severity == "warning"]

    @property
    def valid(self) -> bool:
        return not self.errors

    def to_dict(self) -> dict[str, Any]:
        return {
            "valid": self.valid,
            "errors": [i.to_dict() for i in self.errors],
            "warnings": [i.to_dict() for i in self.warnings],
            "spec": self.spec.model_dump(mode="json"),
            "summary": describe(self.spec) if self.valid else None,
            "spec_hash": spec_hash(self.spec),
            "defaulted": list(self.spec.meta.defaulted),
            "warmup_bars": warmup_bars(self.spec) if self.valid else None,
        }

    def require_valid(self) -> StrategySpecV1:
        if self.errors:
            raise SpecError(self.errors)
        return self.spec


def analyse(raw: Any) -> SpecAnalysis:
    spec = parse_spec(raw)
    issues = check(spec)
    if not [i for i in issues if i.severity == "error"]:
        spec = normalize(spec)
    return SpecAnalysis(spec=spec, issues=issues)


__all__ = [
    "INDICATORS",
    "NIFTY_LOT_SIZE",
    "SCHEMA_VERSION",
    "Issue",
    "SpecAnalysis",
    "SpecError",
    "StrategySpecV1",
    "analyse",
    "describe",
    "parse_spec",
    "public_vocabulary",
    "spec_backtest_config",
    "spec_condition_frame",
    "spec_exit_config",
    "spec_hash",
    "spec_signals",
]
