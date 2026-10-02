"""Append-only audit trail of every gated tool call (Phase 15).

One record per call, allowed or denied: who, which tool and tier, a hash of
the arguments plus a redacted copy, the decision, the outcome and latency.
Tokens never reach a record.

P0 writes JSONL to ``data/audit/tool_audit.jsonl`` (``EVE_AUDIT_PATH``
overrides; ``EVE_AUDIT_PATH=off`` disables). P2 adds a Supabase sink that
inserts into ``public.algo_tool_audit`` with the service role.
"""

from __future__ import annotations

import hashlib
import json
import os
import threading
from collections.abc import Iterable, Mapping
from dataclasses import asdict, dataclass, field
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Protocol

PROJECT_ROOT = Path(__file__).resolve().parents[2]
DEFAULT_AUDIT_PATH = PROJECT_ROOT / "data" / "audit" / "tool_audit.jsonl"

_SECRET_KEYS = ("token", "secret", "password", "authorization", "apikey", "api_key")
_MAX_STRING = 200


def canonical_json(value: Any) -> str:
    return json.dumps(value, sort_keys=True, separators=(",", ":"), default=str)


def args_hash(args: Mapping[str, Any]) -> str:
    return hashlib.sha256(canonical_json(dict(args)).encode()).hexdigest()


def redact(value: Any, depth: int = 0) -> Any:
    """Copy of ``value`` that is safe and small enough to store."""
    if depth > 6:
        return "…"
    if isinstance(value, Mapping):
        out = {}
        for k, v in value.items():
            if any(s in str(k).lower() for s in _SECRET_KEYS):
                out[k] = "[redacted]"
            else:
                out[k] = redact(v, depth + 1)
        return out
    if isinstance(value, (list, tuple)):
        items = [redact(v, depth + 1) for v in list(value)[:50]]
        if len(value) > 50:
            items.append(f"… {len(value) - 50} more")
        return items
    if isinstance(value, str) and len(value) > _MAX_STRING:
        return value[:_MAX_STRING] + "…"
    return value


@dataclass
class AuditRecord:
    tool: str
    tier: str
    decision: str  # "allow" | "deny"
    result_status: str  # "ok" | "error" | "denied"
    http_status: int
    user_id: str | None
    principal_kind: str
    surface: str
    args_hash: str
    args_redacted: Any
    latency_ms: int
    request_id: str | None = None
    model: str | None = None
    error: str | None = None
    created_at: str = field(
        default_factory=lambda: datetime.now(timezone.utc).isoformat()
    )

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)


class AuditSink(Protocol):
    def write(self, record: AuditRecord) -> None: ...


class NullAuditSink:
    def write(self, record: AuditRecord) -> None:  # noqa: D401 - protocol
        return None


class MemoryAuditSink:
    """For tests."""

    def __init__(self) -> None:
        self.records: list[AuditRecord] = []

    def write(self, record: AuditRecord) -> None:
        self.records.append(record)


class JsonlAuditSink:
    def __init__(self, path: str | Path) -> None:
        self.path = Path(path)
        self._lock = threading.Lock()

    def write(self, record: AuditRecord) -> None:
        line = canonical_json(record.to_dict())
        with self._lock:
            self.path.parent.mkdir(parents=True, exist_ok=True)
            with self.path.open("a", encoding="utf-8") as fh:
                fh.write(line + "\n")


class CompositeAuditSink:
    """Fan out to several sinks. One failing sink never blocks the others or the call."""

    def __init__(self, sinks: Iterable[AuditSink]) -> None:
        self.sinks = list(sinks)

    def write(self, record: AuditRecord) -> None:
        for sink in self.sinks:
            try:
                sink.write(record)
            except Exception as exc:  # pragma: no cover - logged, never raised
                print(f"audit sink {type(sink).__name__} failed: {exc}")


def default_audit_sink() -> AuditSink:
    configured = os.environ.get("EVE_AUDIT_PATH", "").strip()
    sinks: list[AuditSink] = []
    if configured.lower() != "off":
        sinks.append(JsonlAuditSink(configured or DEFAULT_AUDIT_PATH))
    # P2: mirror to Supabase when the engine has a service-role key.
    try:
        from mcp.quant_server.store import supabase_audit_sink

        remote = supabase_audit_sink()
        if remote is not None:
            sinks.append(remote)
    except ImportError:  # pragma: no cover - store.py ships in P2
        pass
    if not sinks:
        return NullAuditSink()
    return CompositeAuditSink(sinks)
