"""Run card: a hashed, self-describing receipt for one research run (Phase 08b).

``README.md`` states the architecture principle -- *the quant engine is the
deterministic source of truth*. A run card is what makes that claim checkable
after the fact rather than merely asserted. Each card records, for one run:

* the config that produced it, plus a stable hash of that config;
* the headline scalar metrics;
* the statistical validation verdicts (permutation p-values, bootstrap Sharpe
  interval, deflated Sharpe) when they were computed;
* a SHA-256 of every artifact file in the run directory.

Two runs claiming the same numbers must carry the same ``config_hash``; if the
parquet files were touched after the fact, the artifact digests stop matching.

The hash is taken over canonical JSON (sorted keys, no insignificant
whitespace), so key insertion order never changes it -- the same config built
two different ways hashes identically. This extends the existing
:func:`quant.research.baseline.config_hash`, which hashes a pydantic model;
here the input is any JSON-serialisable mapping.
"""

from __future__ import annotations

import hashlib
import json
import math
from collections.abc import Mapping, Sequence
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

SCHEMA_VERSION = "0.1"
_HASH_CHUNK = 1 << 20  # 1 MiB, so a large parquet is not read into memory whole.

# Ordered so the markdown table reads the way a reviewer scans a result.
HEADLINE_METRICS = (
    "net_pnl",
    "total_trades",
    "win_rate",
    "profit_factor",
    "sharpe",
    "sortino",
    "max_drawdown_pct",
    "total_return_pct",
)


def canonical_json(value: Any) -> str:
    """Deterministic JSON text: sorted keys, compact separators, no NaN."""
    return json.dumps(
        _json_safe(value),
        sort_keys=True,
        separators=(",", ":"),
        ensure_ascii=False,
        allow_nan=False,
    )


def hash_mapping(value: Mapping[str, Any]) -> str:
    """SHA-256 of a mapping's canonical JSON form."""
    return hashlib.sha256(canonical_json(value).encode("utf-8")).hexdigest()


def hash_file(path: Path) -> str:
    """SHA-256 of a file's bytes, read in chunks."""
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for chunk in iter(lambda: handle.read(_HASH_CHUNK), b""):
            digest.update(chunk)
    return digest.hexdigest()


def _json_safe(value: Any) -> Any:
    """Coerce to something ``json.dumps`` accepts, deterministically.

    Non-finite floats become ``None`` rather than ``NaN``/``Infinity``: those
    are not valid JSON, and a card that cannot be re-read is not a receipt.
    """
    if isinstance(value, Mapping):
        return {str(k): _json_safe(v) for k, v in value.items()}
    if isinstance(value, (list, tuple)):
        return [_json_safe(v) for v in value]
    if isinstance(value, bool) or value is None or isinstance(value, (str, int)):
        return value
    if isinstance(value, float):
        return value if math.isfinite(value) else None
    if isinstance(value, datetime):
        return value.isoformat()
    if isinstance(value, Path):
        return str(value)
    if hasattr(value, "to_dict"):
        return _json_safe(value.to_dict())
    return str(value)


def _artifacts(run_dir: Path) -> list[dict[str, Any]]:
    """Every file under ``run_dir`` with its size and digest, path-sorted.

    The card itself is skipped -- a file cannot contain its own hash.
    """
    rows: list[dict[str, Any]] = []
    for path in sorted(run_dir.rglob("*")):
        if not path.is_file() or path.name in {"run_card.json", "run_card.md"}:
            continue
        rows.append(
            {
                "path": path.relative_to(run_dir).as_posix(),
                "bytes": path.stat().st_size,
                "sha256": hash_file(path),
            }
        )
    return rows


def build_run_card(
    *,
    run_id: str,
    config: Mapping[str, Any],
    metrics: Mapping[str, Any] | None = None,
    validation: Mapping[str, Any] | None = None,
    run_dir: Path | None = None,
    notes: Sequence[str] | None = None,
) -> dict[str, Any]:
    """Assemble the run card mapping (no I/O beyond hashing ``run_dir`` files).

    ``validation`` is the place for the phase-08b verdicts -- pass the
    ``to_dict()`` of a :class:`~quant.research.significance.PermutationResult`,
    :class:`~quant.research.significance.BootstrapResult` and/or
    :class:`~quant.research.multiple_testing.DeflatedSharpeResult`, keyed
    however the caller likes.
    """
    card: dict[str, Any] = {
        "schema_version": SCHEMA_VERSION,
        "run_id": run_id,
        "created_at": datetime.now(timezone.utc).isoformat(timespec="seconds"),
        "config": _json_safe(config),
        "config_hash": hash_mapping(config),
        "metrics": _json_safe(metrics or {}),
        "validation": _json_safe(validation or {}),
        "notes": list(notes or []),
        "artifacts": _artifacts(run_dir) if run_dir is not None else [],
    }
    return card


def render_run_card_markdown(card: Mapping[str, Any]) -> str:
    """Human-readable rendering of a run card."""
    lines: list[str] = [
        f"# Run card — {card['run_id']}",
        "",
        f"**Created:** {card['created_at']}  ",
        f"**Schema:** {card['schema_version']}  ",
        f"**Config hash:** `{card['config_hash']}`",
        "",
        "## Config",
        "",
        "```json",
        json.dumps(card["config"], indent=2, sort_keys=True),
        "```",
        "",
    ]

    metrics = card.get("metrics") or {}
    if metrics:
        lines += ["## Metrics", "", "| Metric | Value |", "|---|---|"]
        ordered = [k for k in HEADLINE_METRICS if k in metrics]
        ordered += [k for k in sorted(metrics) if k not in HEADLINE_METRICS]
        for key in ordered:
            lines.append(f"| {key} | {_fmt(metrics[key])} |")
        lines.append("")

    validation = card.get("validation") or {}
    if validation:
        lines += ["## Statistical validation", ""]
        for name, payload in sorted(validation.items()):
            lines.append(f"**{name}**")
            lines.append("")
            if isinstance(payload, Mapping):
                for key in sorted(payload):
                    lines.append(f"- {key}: {_fmt(payload[key])}")
            else:
                lines.append(f"- {_fmt(payload)}")
            lines.append("")

    artifacts = card.get("artifacts") or []
    if artifacts:
        lines += ["## Artifacts", "", "| File | Bytes | SHA-256 |", "|---|---|---|"]
        for row in artifacts:
            lines.append(f"| `{row['path']}` | {row['bytes']:,} | `{row['sha256'][:16]}…` |")
        lines.append("")

    notes = card.get("notes") or []
    if notes:
        lines += ["## Notes", ""] + [f"- {n}" for n in notes] + [""]

    return "\n".join(lines) + "\n"


def _fmt(value: Any) -> str:
    if isinstance(value, bool):
        return "yes" if value else "no"
    if isinstance(value, float):
        if not math.isfinite(value):
            return "n/a"
        return f"{value:,.4f}" if abs(value) < 1000 else f"{value:,.0f}"
    if isinstance(value, Mapping):
        return ", ".join(f"{k}={_fmt(v)}" for k, v in sorted(value.items()))
    if isinstance(value, (list, tuple)):
        return ", ".join(_fmt(v) for v in value)
    return str(value)


def write_run_card(
    run_dir: Path,
    *,
    run_id: str,
    config: Mapping[str, Any],
    metrics: Mapping[str, Any] | None = None,
    validation: Mapping[str, Any] | None = None,
    notes: Sequence[str] | None = None,
) -> dict[str, Any]:
    """Build the card for ``run_dir`` and write ``run_card.json`` + ``.md``.

    Returns the card mapping. ``run_dir`` is created if absent, and its
    existing files are hashed into the card before it is written.
    """
    run_dir = Path(run_dir)
    run_dir.mkdir(parents=True, exist_ok=True)

    card = build_run_card(
        run_id=run_id,
        config=config,
        metrics=metrics,
        validation=validation,
        run_dir=run_dir,
        notes=notes,
    )
    (run_dir / "run_card.json").write_text(
        json.dumps(card, indent=2, sort_keys=True, allow_nan=False) + "\n",
        encoding="utf-8",
    )
    (run_dir / "run_card.md").write_text(render_run_card_markdown(card), encoding="utf-8")
    return card


def verify_run_card(run_dir: Path) -> dict[str, Any]:
    """Re-hash ``run_dir`` and report any artifact that no longer matches.

    Returns ``{"ok": bool, "config_hash": str, "mismatched": [...],
    "missing": [...], "unexpected": [...]}``. ``unexpected`` lists files
    present now but absent from the card, which is how a silently added
    output surfaces.
    """
    run_dir = Path(run_dir)
    card_path = run_dir / "run_card.json"
    if not card_path.exists():
        raise FileNotFoundError(f"no run card at {card_path}")

    card = json.loads(card_path.read_text(encoding="utf-8"))
    recorded = {row["path"]: row["sha256"] for row in card.get("artifacts", [])}
    current = {row["path"]: row["sha256"] for row in _artifacts(run_dir)}

    mismatched = sorted(p for p, h in recorded.items() if p in current and current[p] != h)
    missing = sorted(p for p in recorded if p not in current)
    unexpected = sorted(p for p in current if p not in recorded)

    return {
        "ok": not (mismatched or missing or unexpected),
        "config_hash": card.get("config_hash"),
        "mismatched": mismatched,
        "missing": missing,
        "unexpected": unexpected,
    }
