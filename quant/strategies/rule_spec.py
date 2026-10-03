"""``rule_spec``: the one registered strategy that runs every user spec (Phase 15).

User strategies are data (``eve.strategy/1``), interpreted here. Registering
one id instead of one per user avoids the global registry's duplicate-id
collisions, keeps sweep worker processes (which only see import-time
registrations) able to run user specs, and lets ``run_trial`` rows, param
hashes and run cards work unchanged -- the spec is just ``params["spec"]``.

Note that a spec's exits live in the spec's ``risk``/``session`` blocks; a
caller running ``rule_spec`` through the sweep must pass
``spec_exit_config(spec)`` as the trial's exits.
"""

from __future__ import annotations

from collections.abc import Mapping
from typing import Any

import polars as pl

from quant.strategies.base import StrategySpec, register_strategy
from quant.strategies.spec import analyse, spec_signals


def generate_signals(frame: pl.DataFrame, params: Mapping[str, Any]) -> pl.DataFrame:
    if "spec" not in params:
        raise ValueError("rule_spec needs params={'spec': {...}}")
    spec = analyse(params["spec"]).require_valid()
    return spec_signals(frame, spec)


register_strategy(
    StrategySpec(
        id="rule_spec",
        requires_volume=False,
        default_timeframes=("5m", "15m"),
        param_space={},
        generate_signals=generate_signals,
        description="Interprets a declarative eve.strategy/1 spec built in chat or the form.",
    )
)
