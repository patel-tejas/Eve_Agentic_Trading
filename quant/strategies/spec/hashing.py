"""Canonical hash of a spec's *logic* (Phase 15).

Name, description and ``meta`` (source, prompt, defaulted) are excluded: the
same rules built in chat and in the form must hash identically, and renaming
a strategy is not a new strategy. Hash the *normalised* spec (defaults
filled) so an omitted ``period: 14`` and an explicit one agree.
"""

from __future__ import annotations

import hashlib
import json

from quant.strategies.spec.schema import StrategySpecV1

_NON_LOGIC = {"name", "description", "meta"}


def canonical_logic(spec: StrategySpecV1) -> dict:
    return spec.model_dump(mode="json", exclude=_NON_LOGIC)


def spec_hash(spec: StrategySpecV1) -> str:
    payload = json.dumps(canonical_logic(spec), sort_keys=True, separators=(",", ":"))
    return hashlib.sha256(payload.encode()).hexdigest()
