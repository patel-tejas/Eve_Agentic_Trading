"""Semantic diff between two spec versions (Phase 15).

Compares the *logic* (``hashing.canonical_logic``) of two normalised specs
and lists every leaf that changed as a JSON Pointer with before/after values,
plus the template summaries of both sides. Used by ``revise_strategy`` and the
Hisaab version timeline.
"""

from __future__ import annotations

from typing import Any

from quant.strategies.spec.describe import describe
from quant.strategies.spec.hashing import canonical_logic
from quant.strategies.spec.schema import StrategySpecV1

_MISSING = object()


def _walk(a: Any, b: Any, path: str, out: list[dict[str, Any]]) -> None:
    if isinstance(a, dict) and isinstance(b, dict):
        for key in sorted(set(a) | set(b)):
            _walk(a.get(key, _MISSING), b.get(key, _MISSING), f"{path}/{key}", out)
        return
    if isinstance(a, list) and isinstance(b, list):
        for i in range(max(len(a), len(b))):
            _walk(
                a[i] if i < len(a) else _MISSING,
                b[i] if i < len(b) else _MISSING,
                f"{path}/{i}",
                out,
            )
        return
    if a != b:
        out.append(
            {
                "path": path or "/",
                "before": None if a is _MISSING else a,
                "after": None if b is _MISSING else b,
                "op": "add" if a is _MISSING else "remove" if b is _MISSING else "replace",
            }
        )


def spec_diff(before: StrategySpecV1, after: StrategySpecV1) -> dict[str, Any]:
    changes: list[dict[str, Any]] = []
    _walk(canonical_logic(before), canonical_logic(after), "", changes)
    return {
        "changes": changes,
        "changed": bool(changes),
        "summary_before": describe(before),
        "summary_after": describe(after),
    }
