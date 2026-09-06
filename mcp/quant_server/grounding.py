"""Numeric grounding: is every figure in an answer traceable to a tool result?

WHY THIS EXISTS
---------------
The repo's architecture principle is "AI orchestrates; Python calculates", and
the chat's system prompt says so in words: *never compute a figure yourself*.
But a system prompt is an instruction, not an enforcement mechanism -- exactly
the gap we closed for the write tools by moving the check into the bridge. A
model can state a plausible Sharpe ratio it never obtained, and nothing today
would notice.

This module notices. It extracts every numeric claim from a draft answer,
collects every number the run's tool results actually contain, and reports the
claims that trace to nothing.

Ported in spirit from HKUDS/Vibe-Trading's ``src/agent/grounding.py`` (MIT).
That file is ~2,500 lines, most of it identity locking, venue and currency
inference and multi-symbol attribution -- all of which answer "which instrument
does this figure belong to". We hold one instrument, so that question does not
arise and none of it is ported. What is kept is the core: an evidence ledger
and a final-answer numeric check, plus their markdown-ordinal mask, which
exists because ``1.`` in a numbered list was being read as a price.

ADVISORY, NOT A GATE
--------------------
:func:`check_grounding` reports; it does not block. Rejecting a draft means
buffering the answer instead of streaming it, then looping the model through a
correction prompt -- a change that would degrade the streaming UI and, more to
the point, cannot be verified without a working model key. The detector is
verifiable today; the gate is a follow-up.

FALSE POSITIVES ARE THE FAILURE MODE
------------------------------------
A check that flags ``2026-07`` as an unsourced number is worse than no check,
because it gets switched off within a day. Dates, timeframes, list markers and
phase references are masked out *before* extraction, and matching is generous:
a claim counts as grounded if it equals a tool value at any rounding, or that
value scaled to a percentage.
"""

from __future__ import annotations

import hashlib
import math
import re
from collections.abc import Mapping, Sequence
from dataclasses import dataclass, field
from typing import Any

# A number: optional sign, optional thousands separators, optional decimals.
# Bounded by non-word characters so "9" in "EMA9" or "x2" is not a claim.
_NUMBER_RE = re.compile(
    r"(?<![A-Za-z0-9_.])[-+]?(?:\d{1,3}(?:,\d{3})+|\d+)(?:\.\d+)?(?![A-Za-z0-9_])"
)

# ---------------------------------------------------------------- masks
# Each mask blanks a span BEFORE number extraction, so the characters are gone
# but offsets are preserved (replaced with spaces of equal length).

# ISO-ish dates and timestamps: 2026-07, 2026-07-15, 2026-07-15T09:15:00.
_DATE_RE = re.compile(r"\d{4}-\d{2}(?:-\d{2})?(?:[T ]\d{2}:\d{2}(?::\d{2})?)?")
# Bare clock times: 09:15, 15:30:00.
_TIME_RE = re.compile(r"(?<!\d)\d{1,2}:\d{2}(?::\d{2})?")
# Timeframes: 1m, 5m, 15m, 1h, 1d. The digit names a bar size, not a quantity.
_TIMEFRAME_RE = re.compile(r"(?<![A-Za-z0-9])\d+\s*(?:m|min|h|d)\b", re.IGNORECASE)
# Markdown ordered-list markers. Vibe-Trading hit this exact bug: "1." at the
# start of a line was parsed as a float and rejected as an unsourced price.
_MD_LIST_ITEM_RE = re.compile(r"^\s*\d+[.)]\s+", re.MULTILINE)
# Project structure references: "phase 04", "phase-08b".
_PHASE_RE = re.compile(r"phase[\s-]*\d+[a-z]?", re.IGNORECASE)
# Markdown table alignment rows: |---|---:|
_TABLE_RULE_RE = re.compile(r"^\s*\|[\s|:-]+\|\s*$", re.MULTILINE)
# Hyphenated identifiers: this project labels grid experiments "RE-0042", and
# the digits after the hyphen are a name, not a quantity. The number regex's
# lookbehind cannot catch these on its own -- a hyphen is a legal boundary,
# so "RE-0042" yields 42.
_IDENTIFIER_RE = re.compile(r"\b[A-Za-z]{2,}-\d+[A-Za-z]?\b")

_MASKS = (
    _TABLE_RULE_RE,
    _IDENTIFIER_RE,
    _DATE_RE,
    _TIME_RE,
    _TIMEFRAME_RE,
    _MD_LIST_ITEM_RE,
    _PHASE_RE,
)

# Rounding depths tried when matching a claim to a tool value. A model writes
# ₹5,736.64 for 5736.63671700029 and "1.35" for 1.3511033969749748.
_ROUNDINGS = range(0, 7)
# Floats within this relative distance are the same number.
_REL_TOLERANCE = 1e-9


@dataclass(frozen=True)
class NumericClaim:
    """One number asserted in an answer, and what (if anything) backs it."""

    value: float
    text: str
    line: int
    context: str
    grounded: bool = False
    matched: float | None = None
    match_kind: str = "none"

    def to_dict(self) -> dict[str, Any]:
        return {
            "value": self.value,
            "text": self.text,
            "line": self.line,
            "context": self.context,
            "grounded": self.grounded,
            "matched_evidence": self.matched,
            "match_kind": self.match_kind,
        }


@dataclass(frozen=True)
class GroundingReport:
    """Verdict on one draft answer."""

    grounded: bool
    total_claims: int
    grounded_claims: int
    evidence_values: int
    answer_sha256: str
    ungrounded: list[dict[str, Any]] = field(default_factory=list)

    def to_dict(self) -> dict[str, Any]:
        return {
            "grounded": self.grounded,
            "total_claims": self.total_claims,
            "grounded_claims": self.grounded_claims,
            "ungrounded_claims": len(self.ungrounded),
            "evidence_values": self.evidence_values,
            "answer_sha256": self.answer_sha256,
            "ungrounded": self.ungrounded,
        }

    def summary(self) -> str:
        if self.total_claims == 0:
            return "No numeric claims to check."
        if self.grounded:
            return (
                f"All {self.total_claims} numeric claims trace to tool results "
                f"({self.evidence_values} values on record)."
            )
        values = ", ".join(str(c["text"]) for c in self.ungrounded[:5])
        more = "" if len(self.ungrounded) <= 5 else f" (+{len(self.ungrounded) - 5} more)"
        return (
            f"{len(self.ungrounded)} of {self.total_claims} numeric claims do not "
            f"trace to any tool result: {values}{more}"
        )


def _mask(text: str) -> str:
    """Blank non-claim spans, preserving length so line numbers stay right."""
    masked = text
    for pattern in _MASKS:
        masked = pattern.sub(lambda m: " " * len(m.group(0)), masked)
    return masked


def _parse(token: str) -> float | None:
    try:
        return float(token.replace(",", ""))
    except ValueError:
        return None


def extract_claims(answer: str) -> list[NumericClaim]:
    """Every numeric claim in ``answer``, with masks applied.

    Percent signs are not stripped here: a claim written ``25%`` is the number
    25, and :func:`_match` is what knows a tool's ``0.25`` can back it.
    """
    claims: list[NumericClaim] = []
    for line_no, (raw_line, masked_line) in enumerate(
        zip(answer.splitlines(), _mask(answer).splitlines()), start=1
    ):
        for match in _NUMBER_RE.finditer(masked_line):
            value = _parse(match.group(0))
            if value is None:
                continue
            start, end = match.span()
            claims.append(
                NumericClaim(
                    value=value,
                    text=match.group(0),
                    line=line_no,
                    context=raw_line.strip()[:160],
                )
            )
    return claims


def collect_evidence(payload: Any, *, _depth: int = 0) -> list[float]:
    """Every finite number anywhere in the run's tool results.

    Walks nested dicts and lists, because a tool returns metrics, config and
    row previews at different depths and any of them is legitimate evidence.
    Numeric strings count -- some fields serialise that way.
    """
    if _depth > 24:
        return []
    values: list[float] = []
    if isinstance(payload, bool):
        return values
    if isinstance(payload, (int, float)):
        if math.isfinite(float(payload)):
            values.append(float(payload))
        return values
    if isinstance(payload, str):
        parsed = _parse(payload.strip())
        if parsed is not None and math.isfinite(parsed):
            values.append(parsed)
        return values
    if isinstance(payload, Mapping):
        for item in payload.values():
            values.extend(collect_evidence(item, _depth=_depth + 1))
        return values
    if isinstance(payload, Sequence):
        for item in payload:
            values.extend(collect_evidence(item, _depth=_depth + 1))
    return values


def _close(a: float, b: float) -> bool:
    return math.isclose(a, b, rel_tol=_REL_TOLERANCE, abs_tol=1e-12)


def _match(value: float, evidence: Sequence[float]) -> tuple[float | None, str]:
    """Find a tool value that backs ``value``.

    Three ways a claim can legitimately differ from the stored number:
    exact, rounded for display, or scaled to a percentage (a win rate is
    stored as 0.25 and written as 25%).
    """
    for candidate in evidence:
        if _close(value, candidate):
            return candidate, "exact"
    for candidate in evidence:
        for digits in _ROUNDINGS:
            if _close(value, round(candidate, digits)):
                return candidate, "rounded"
    for candidate in evidence:
        scaled = candidate * 100.0
        for digits in _ROUNDINGS:
            if _close(value, round(scaled, digits)):
                return candidate, "percent"
    return None, "none"


def check_grounding(answer: str, tool_results: Any) -> GroundingReport:
    """Report which numeric claims in ``answer`` trace to ``tool_results``.

    ``tool_results`` is anything JSON-shaped -- typically the list of tool
    outputs collected over one chat turn. Deterministic: the same inputs
    always give the same report, and ``answer_sha256`` identifies the draft
    that was checked.

    An answer with no numbers is trivially grounded. An answer with numbers
    and NO evidence is fully ungrounded, which is the case worth catching:
    the model answered without calling anything.
    """
    evidence = collect_evidence(tool_results)
    claims = extract_claims(answer)

    checked: list[NumericClaim] = []
    for claim in claims:
        matched, kind = _match(claim.value, evidence)
        checked.append(
            NumericClaim(
                value=claim.value,
                text=claim.text,
                line=claim.line,
                context=claim.context,
                grounded=matched is not None,
                matched=matched,
                match_kind=kind,
            )
        )

    ungrounded = [c.to_dict() for c in checked if not c.grounded]
    return GroundingReport(
        grounded=not ungrounded,
        total_claims=len(checked),
        grounded_claims=len(checked) - len(ungrounded),
        evidence_values=len(evidence),
        answer_sha256=hashlib.sha256(answer.encode("utf-8")).hexdigest(),
        ungrounded=ungrounded,
    )
