"""The common gate: one pipeline every tool call passes through (Phase 15, P0).

Before this module the only control layer was the HTTP bridge's
``call_tool``. The stdio MCP server bypassed it entirely -- it registered the
write tools unconditionally and let any client set ``processed_root``. Now
both surfaces call ``Gate.invoke``:

* the Starlette bridge (``http_bridge.call_tool``) with a principal resolved
  from request headers;
* the FastMCP stdio server through ``TradingGateMiddleware``, with a
  principal resolved from the environment.

The pipeline, in fixed order:

1. look the tool up in ``TOOL_POLICY`` (unknown -> 404)
2. authorise the tier: denied tiers, operator-only data tools, UI-only
   tools, user tiers without a user (401), kill switch (423)
3. strip internal arguments (filesystem roots, any model-supplied
   ``user_id``) and drop unknown ones, reporting them back
4. validate and coerce the rest against the tool's signature with pydantic
   (``"5"`` becomes ``5``; a bad nested spec returns JSON-Pointer paths)
5. per-user, per-tier rate limit (429)
6. run in a worker thread under the tool's timeout (504), with the
   principal bound to a context variable the tool can read
7. check the output is JSON-serialisable and not oversized
8. write one audit record, whatever happened
9. map failures to a status and a message the model can act on

Policy is data (``policy.py``); this module is the only code that reads it.
"""

from __future__ import annotations

import asyncio
import inspect
import json
import os
import time
import typing
from collections.abc import Callable, Mapping
from dataclasses import dataclass, field
from typing import Any

from pydantic import BaseModel, ConfigDict, ValidationError, create_model

from mcp.quant_server.audit import (
    AuditRecord,
    AuditSink,
    args_hash,
    default_audit_sink,
    redact,
)
from mcp.quant_server.auth import (
    AuthError,
    Principal,
    require_user_everywhere,
    reset_current_principal,
    set_current_principal,
)
from mcp.quant_server.policy import (
    DENIED_TIERS,
    KILL_SWITCH_TIERS,
    TOOL_POLICY,
    ToolPolicy,
)
from mcp.quant_server.ratelimit import RateLimiter

# Arguments the model must never set. Filesystem roots keep their defaults
# from server.py; identity always comes from the verified principal.
INTERNAL_PARAMS: frozenset[str] = frozenset(
    {"processed_root", "raw_root", "results_root", "out_dir"}
)
IDENTITY_PARAMS: frozenset[str] = frozenset({"user_id", "owner", "owner_id"})

DEFAULT_TIMEOUT_SECONDS = float(os.environ.get("QUANT_TOOL_TIMEOUT", "300"))
MAX_RESULT_BYTES = int(os.environ.get("EVE_MAX_RESULT_BYTES", str(2_000_000)))

Surface = typing.Literal["chat", "ui", "mcp"]

_JSON_TYPES: dict[Any, str] = {str: "string", int: "integer", float: "number", bool: "boolean"}


def write_tools_enabled_from_env() -> bool:
    return os.environ.get("QUANT_ALLOW_WRITE_TOOLS", "").lower() in {"1", "true", "yes"}


class GateError(Exception):
    """A refused or failed call, with the status the bridge should return."""

    def __init__(self, status: int, message: str, **extra: Any) -> None:
        super().__init__(message)
        self.status = status
        self.message = message
        self.extra = extra

    def to_payload(self) -> dict[str, Any]:
        return {"error": self.message, **self.extra}


class Controls:
    """Kill-switch lookups. P0 reads ``EVE_KILL_SWITCH``; P5 adds the database."""

    def kill_switch_reason(self, principal: Principal) -> str | None:
        if os.environ.get("EVE_KILL_SWITCH", "").lower() in {"1", "true", "yes"}:
            return "the global kill switch is engaged (EVE_KILL_SWITCH)"
        return None


# ------------------------------------------------------------------ signatures


def _type_hints(fn: Callable[..., Any]) -> dict[str, Any]:
    try:
        return typing.get_type_hints(fn)
    except Exception:  # pragma: no cover - unresolvable forward refs
        return {}


def public_params(fn: Callable[..., Any]) -> list[inspect.Parameter]:
    """The parameters a caller may supply (internal and identity ones removed)."""
    return [
        p
        for name, p in inspect.signature(fn).parameters.items()
        if name not in INTERNAL_PARAMS
        and name not in IDENTITY_PARAMS
        and p.kind in (p.POSITIONAL_OR_KEYWORD, p.KEYWORD_ONLY)
    ]


def _unwrap_optional(tp: Any) -> tuple[Any, bool]:
    args = typing.get_args(tp)
    if args and type(None) in args:
        rest = [a for a in args if a is not type(None)]
        if len(rest) == 1:
            return rest[0], True
    return tp, False


def _is_model(tp: Any) -> bool:
    return inspect.isclass(tp) and issubclass(tp, BaseModel)


def _strip_titles(schema: Any) -> Any:
    if isinstance(schema, dict):
        return {k: _strip_titles(v) for k, v in schema.items() if k != "title"}
    if isinstance(schema, list):
        return [_strip_titles(v) for v in schema]
    return schema


def model_schema(model: type[BaseModel]) -> dict[str, Any]:
    """Compact JSON Schema for a pydantic model, ``$defs`` kept as references.

    Inlining the references would repeat the operand union for every
    condition slot and grow the spec schema from ~7 KB to ~50 KB -- tokens the
    model pays for on every turn.
    """
    return _strip_titles(model.model_json_schema())


# A nested-model parameter gets its full schema only on tools that opt in
# with ``fn.__eve_full_schema__ = True``. Every other tool taking the same
# model advertises a plain object, so the chat pays for the spec schema once.
FULL_SCHEMA_ATTR = "__eve_full_schema__"


def tool_schema(fn: Callable[..., Any]) -> dict[str, Any]:
    """JSON Schema for a tool's public signature.

    Derived from the annotations (resolved with ``get_type_hints`` -- the
    modules use ``from __future__ import annotations``, so raw annotations are
    strings), so a signature change cannot desynchronise the tool the model is
    offered from the function that runs.
    """
    hints = _type_hints(fn)
    properties: dict[str, Any] = {}
    required: list[str] = []
    for param in public_params(fn):
        tp, _ = _unwrap_optional(hints.get(param.name, str))
        if _is_model(tp):
            if getattr(fn, FULL_SCHEMA_ATTR, False):
                prop = model_schema(tp)
            else:
                prop = {
                    "type": "object",
                    "description": f"A {tp.__name__} object. Build it with the schema of "
                    "validate_strategy_spec and validate it there first.",
                }
        else:
            prop = {"type": _JSON_TYPES.get(tp, "string")}
        if param.default is inspect.Parameter.empty:
            required.append(param.name)
        else:
            prop["default"] = param.default
        properties[param.name] = prop
    return {
        "type": "object",
        "properties": properties,
        "required": required,
        "additionalProperties": False,
    }


def _coerce_json_strings(value: Any) -> Any:
    """Weaker models sometimes pass a nested object as a JSON string."""
    if isinstance(value, str) and value.strip().startswith("{"):
        try:
            return json.loads(value)
        except json.JSONDecodeError:
            return value
    return value


def _args_model(fn: Callable[..., Any]) -> type[BaseModel]:
    hints = _type_hints(fn)
    fields: dict[str, Any] = {}
    for param in public_params(fn):
        tp = hints.get(param.name, Any)
        default = ... if param.default is inspect.Parameter.empty else param.default
        fields[param.name] = (tp, default)
    return create_model(  # type: ignore[call-overload]
        f"{fn.__name__}_args",
        __config__=ConfigDict(extra="ignore", arbitrary_types_allowed=True),
        **fields,
    )


def json_pointer(loc: tuple[Any, ...]) -> str:
    return "/" + "/".join(str(part) for part in loc)


def validation_issues(exc: ValidationError) -> list[dict[str, str]]:
    return [
        {"path": json_pointer(err["loc"]), "message": err["msg"]}
        for err in exc.errors(include_url=False)
    ]


# ------------------------------------------------------------------ gate


@dataclass
class _Prepared:
    kwargs: dict[str, Any]
    ignored: list[str]
    redacted: Any
    hash: str


@dataclass
class Gate:
    tools: Mapping[str, Callable[..., Any]]
    policy: Mapping[str, ToolPolicy] = field(default_factory=lambda: TOOL_POLICY)
    audit: AuditSink = field(default_factory=default_audit_sink)
    limiter: RateLimiter = field(default_factory=RateLimiter)
    controls: Controls = field(default_factory=Controls)
    write_tools_enabled: bool = field(default_factory=write_tools_enabled_from_env)
    default_timeout_s: float = DEFAULT_TIMEOUT_SECONDS

    def __post_init__(self) -> None:
        missing = sorted(set(self.tools) - set(self.policy))
        if missing:
            raise ValueError(f"tools without a policy row: {missing}")
        self._models = {name: _args_model(fn) for name, fn in self.tools.items()}

    # ---------------------------------------------------------- visibility

    def is_offered(self, name: str, surface: Surface) -> bool:
        """Whether ``name`` appears in the manifest for ``surface``."""
        policy = self.policy.get(name)
        if policy is None or name not in self.tools:
            return False
        if policy.tier in DENIED_TIERS:
            return False
        if policy.tier == "data_write" and not self.write_tools_enabled:
            return False
        if surface != "ui" and not policy.chat_visible:
            return False
        return True

    def offered(self, surface: Surface) -> list[str]:
        return [name for name in self.tools if self.is_offered(name, surface)]

    def manifest(self, surface: Surface = "chat") -> list[dict[str, Any]]:
        out = []
        for name in self.offered(surface):
            fn = self.tools[name]
            policy = self.policy[name]
            out.append(
                {
                    "name": name,
                    "description": " ".join((inspect.getdoc(fn) or "").split()),
                    "parameters": tool_schema(fn),
                    "tier": policy.tier,
                }
            )
        return out

    # ---------------------------------------------------------- pipeline

    def _authorize(
        self, name: str, policy: ToolPolicy, principal: Principal, surface: Surface
    ) -> None:
        if policy.tier in DENIED_TIERS:
            raise GateError(403, f"{name} is in the {policy.tier} tier, which is disabled")
        if policy.tier == "data_write" and not self.write_tools_enabled:
            raise GateError(
                403,
                f"{name} modifies data and is disabled. Set QUANT_ALLOW_WRITE_TOOLS=1 "
                "and restart the engine to enable it.",
            )
        if not policy.chat_visible and surface != "ui":
            raise GateError(
                403,
                f"{name} can only be run from the Hisaab app by the user, not from chat.",
            )
        if (policy.needs_user or require_user_everywhere()) and not principal.is_user:
            raise GateError(401, f"{name} needs a signed-in user")
        if policy.tier in KILL_SWITCH_TIERS:
            reason = self.controls.kill_switch_reason(principal)
            if reason:
                raise GateError(423, f"{name} is blocked: {reason}")

    def _prepare(self, name: str, raw_args: Mapping[str, Any]) -> _Prepared:
        fn = self.tools[name]
        accepted = {p.name for p in public_params(fn)}
        ignored = sorted(k for k in raw_args if k not in accepted)
        supplied = {k: _coerce_json_strings(v) for k, v in raw_args.items() if k in accepted}
        validated = self._models[name].model_validate(supplied)
        # Keep nested pydantic models as models: tools that take a spec get
        # the validated object, not a re-serialised dict.
        kwargs = {k: getattr(validated, k) for k in supplied}
        return _Prepared(
            kwargs=kwargs,
            ignored=ignored,
            redacted=redact(dict(raw_args)),
            hash=args_hash(raw_args),
        )

    @staticmethod
    def _run(fn: Callable[..., Any], kwargs: dict[str, Any], principal: Principal) -> Any:
        token = set_current_principal(principal)
        try:
            return fn(**kwargs)
        finally:
            reset_current_principal(token)

    @staticmethod
    def _check_output(name: str, result: Any) -> Any:
        try:
            encoded = json.dumps(result, default=str)
        except (TypeError, ValueError) as exc:
            raise GateError(500, f"{name} returned a non-JSON result: {exc}") from exc
        if len(encoded) > MAX_RESULT_BYTES:
            raise GateError(
                413,
                f"{name} returned {len(encoded):,} bytes, over the "
                f"{MAX_RESULT_BYTES:,} limit. Narrow the request.",
            )
        return result

    async def invoke(
        self,
        name: str,
        raw_args: Mapping[str, Any] | None,
        principal: Principal,
        *,
        surface: Surface = "chat",
        request_id: str | None = None,
        model: str | None = None,
    ) -> dict[str, Any]:
        """Run one tool through the full pipeline.

        Returns ``{"result": ..., "ignored_arguments": [...]}``. Raises
        ``GateError`` for every refusal or failure.
        """
        started = time.perf_counter()
        raw_args = dict(raw_args or {})
        policy = self.policy.get(name)
        tier = policy.tier if policy else "unknown"
        prepared: _Prepared | None = None

        def record(status: str, http_status: int, error: str | None = None) -> None:
            self.audit.write(
                AuditRecord(
                    tool=name,
                    tier=tier,
                    decision="allow" if status != "denied" else "deny",
                    result_status=status,
                    http_status=http_status,
                    user_id=principal.user_id,
                    principal_kind=principal.kind,
                    surface=surface,
                    args_hash=prepared.hash if prepared else args_hash(raw_args),
                    args_redacted=prepared.redacted if prepared else redact(raw_args),
                    latency_ms=int((time.perf_counter() - started) * 1000),
                    request_id=request_id,
                    model=model,
                    error=error,
                )
            )

        try:
            if policy is None or name not in self.tools:
                raise GateError(
                    404, f"unknown tool {name!r}", available=sorted(self.offered(surface))
                )
            self._authorize(name, policy, principal, surface)
            try:
                prepared = self._prepare(name, raw_args)
            except ValidationError as exc:
                issues = validation_issues(exc)
                summary = "; ".join(f"{i['path']}: {i['message']}" for i in issues[:8])
                raise GateError(400, f"invalid arguments for {name}: {summary}", issues=issues)
            allowed, retry = self.limiter.allow(principal.key, policy.tier, policy.rate)
            if not allowed:
                raise GateError(
                    429,
                    f"rate limit for {policy.tier} tools reached; retry in {retry:.0f}s",
                    retry_after=round(retry, 1),
                )
        except GateError as exc:
            record("denied", exc.status, exc.message)
            raise

        timeout = policy.timeout_s or self.default_timeout_s
        try:
            result = await asyncio.wait_for(
                asyncio.to_thread(self._run, self.tools[name], prepared.kwargs, principal),
                timeout=timeout,
            )
            result = self._check_output(name, result)
        except asyncio.TimeoutError:
            exc = GateError(
                504,
                f"{name} exceeded {timeout:.0f}s. Retry with a smaller grid or a "
                "coarser timeframe.",
            )
            record("error", exc.status, exc.message)
            raise exc from None
        except GateError as exc:
            record("error", exc.status, exc.message)
            raise
        except AuthError as exc:
            record("denied", exc.status, exc.message)
            raise GateError(exc.status, exc.message) from exc
        except ValidationError as exc:
            issues = validation_issues(exc)
            summary = "; ".join(f"{i['path']}: {i['message']}" for i in issues[:8])
            record("error", 400, summary)
            raise GateError(400, f"ValidationError: {summary}", issues=issues) from exc
        except (ValueError, FileNotFoundError, TypeError, KeyError, PermissionError) as exc:
            # Expected, actionable failures: bad month, absent parquet, a spec
            # the engine cannot run. The model can correct these on its own.
            status = 403 if isinstance(exc, PermissionError) else 400
            message = f"{type(exc).__name__}: {exc}"
            issues = getattr(exc, "issues", None)
            record("error", status, message)
            raise GateError(status, message, **({"issues": issues} if issues else {})) from exc
        except Exception as exc:  # pragma: no cover - genuine server fault
            message = f"internal error in {name}: {type(exc).__name__}: {exc}"
            record("error", 500, message)
            raise GateError(500, message) from exc

        record("ok", 200)
        payload: dict[str, Any] = {"result": result}
        if prepared.ignored:
            payload["ignored_arguments"] = prepared.ignored
        return payload
