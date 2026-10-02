"""HTTP surface over the same quant tools the MCP server exposes (Phase 07b).

WHY THIS EXISTS
---------------
The Next.js frontend needs to call the deterministic engine, and a browser or
Node runtime cannot import ``quant/``. FastMCP's HTTP transport is
session-oriented (initialize handshake, SSE stream, session ids), which is a
lot of protocol to re-implement in a route handler for no benefit.

So this module mounts ``server._TOOL_FUNCTIONS`` -- the *same* tuple
``build_server()`` decorates -- as plain JSON endpoints. One source of truth:
a tool added to the MCP server appears here automatically, and cannot drift
between the two surfaces.

The architecture principle is unchanged: this layer validates and serialises,
it never calculates. Every number still comes from ``quant/``.

Phase 15: every call goes through ``gate.Gate.invoke`` -- the same pipeline
the stdio MCP server uses -- so auth, policy tiers, rate limits, validation
and the audit trail are identical on both surfaces. This module only parses
HTTP and maps ``GateError`` to a status code.

Auth headers (see ``auth.py``):
``X-Eve-Internal``  shared service secret, required when EVE_INTERNAL_SECRET is set
``Authorization``   ``Bearer <Supabase access token>`` -> the user
``X-Eve-Surface``   ``ui`` only from Hisaab UI routes (UI-only tools)
``X-Request-Id``    optional, echoed back and written to the audit log

Endpoints
---------
``GET  /health``            liveness + tool count
``GET  /tools``             tool names, descriptions and JSON Schema
``POST /tools/{name}``      call one tool with a JSON object of arguments

Run:
    uv run python -m mcp.quant_server.http_bridge          # port 8010
    uv run python -m mcp.quant_server.http_bridge --port 9000
"""

from __future__ import annotations

import argparse
import json
import uuid
from typing import Any, Callable

from starlette.applications import Starlette
from starlette.middleware import Middleware
from starlette.middleware.cors import CORSMiddleware
from starlette.requests import Request
from starlette.responses import JSONResponse
from starlette.routing import Route

from mcp.quant_server.auth import AuthError, Principal, internal_secret, principal_from_headers
from mcp.quant_server.gate import (
    DEFAULT_TIMEOUT_SECONDS,
    INTERNAL_PARAMS,
    Gate,
    GateError,
    tool_schema,
    write_tools_enabled_from_env,
)
from mcp.quant_server.grounding import check_grounding
from mcp.quant_server.policy import TOOL_POLICY
from mcp.quant_server.server import ALL_TOOL_FUNCTIONS

DEFAULT_PORT = 8010

# Kept as module attributes for callers and tests that predate the gate.
TOOL_TIMEOUT_SECONDS = DEFAULT_TIMEOUT_SECONDS
_INTERNAL_PARAMS = INTERNAL_PARAMS

# Tools with side effects (download_month_data calls the broker API,
# process_month_data OVERWRITES parquet, validate_dataset writes a report).
# The policy table decides; this set is derived from it.
_WRITE_TOOLS = frozenset(n for n, p in TOOL_POLICY.items() if p.tier == "data_write")
WRITE_TOOLS_ENABLED = write_tools_enabled_from_env()

_ALL_TOOLS: dict[str, Callable[..., Any]] = {fn.__name__: fn for fn in ALL_TOOL_FUNCTIONS}

GATE = Gate(tools=_ALL_TOOLS, write_tools_enabled=WRITE_TOOLS_ENABLED)

# What the model is offered: the gate's chat manifest.
_TOOLS: dict[str, Callable[..., Any]] = {name: _ALL_TOOLS[name] for name in GATE.offered("chat")}


def _schema(fn: Callable[..., Any]) -> dict[str, Any]:
    """JSON Schema for a tool's public signature (see ``gate.tool_schema``)."""
    return tool_schema(fn)


def tool_manifest(surface: str = "chat") -> list[dict[str, Any]]:
    """Every offered tool as ``{name, description, parameters, tier}``."""
    return GATE.manifest(surface)  # type: ignore[arg-type]


def _surface(request: Request) -> str:
    # Only the Hisaab server holds the internal secret, and only its UI
    # routes (a human clicked a button) send this header. The chat route
    # never does, so a model cannot reach a UI-only tool.
    return "ui" if request.headers.get("x-eve-surface", "").lower() == "ui" else "chat"


def _principal(request: Request) -> Principal:
    return principal_from_headers(request.headers)


async def health(_: Request) -> JSONResponse:
    return JSONResponse(
        {
            "ok": True,
            "service": "quant-http-bridge",
            "tools": len(_TOOLS),
            "auth": "internal-secret" if internal_secret() else "local",
        }
    )


async def list_tools(request: Request) -> JSONResponse:
    try:
        _principal(request)
    except AuthError as exc:
        return JSONResponse({"error": exc.message}, status_code=exc.status)
    surface = "ui" if request.query_params.get("surface") == "ui" else "chat"
    return JSONResponse({"tools": tool_manifest(surface)})


async def call_tool(request: Request) -> JSONResponse:
    """Parse the request, resolve the caller, and hand the call to the gate."""
    name = request.path_params["name"]
    request_id = request.headers.get("x-request-id") or uuid.uuid4().hex

    try:
        principal = _principal(request)
    except AuthError as exc:
        return JSONResponse({"error": exc.message}, status_code=exc.status)

    try:
        raw = await request.body()
        args = json.loads(raw) if raw.strip() else {}
    except json.JSONDecodeError as exc:
        return JSONResponse({"error": f"invalid JSON body: {exc}"}, status_code=400)
    if not isinstance(args, dict):
        return JSONResponse({"error": "body must be a JSON object"}, status_code=400)

    try:
        payload = await GATE.invoke(
            name,
            args,
            principal,
            surface=_surface(request),  # type: ignore[arg-type]
            request_id=request_id,
            model=request.headers.get("x-eve-model"),
        )
    except GateError as exc:
        headers = {"x-request-id": request_id}
        if exc.status == 429 and "retry_after" in exc.extra:
            headers["retry-after"] = str(int(exc.extra["retry_after"]) + 1)
        return JSONResponse(exc.to_payload(), status_code=exc.status, headers=headers)

    return JSONResponse({"tool": name, **payload}, headers={"x-request-id": request_id})


async def grounding_check(request: Request) -> JSONResponse:
    """Report which numeric claims in an answer trace to this run's tool results.

    Deliberately NOT a member of ``_TOOL_FUNCTIONS``: it is absent from
    ``/tools``, so the model is never offered the ability to call its own
    grader. The chat route invokes it after a turn completes.

    Body: ``{"answer": str, "tool_results": any}``.
    """
    try:
        raw = await request.body()
        body = json.loads(raw) if raw.strip() else {}
    except json.JSONDecodeError as exc:
        return JSONResponse({"error": f"invalid JSON body: {exc}"}, status_code=400)
    if not isinstance(body, dict):
        return JSONResponse({"error": "body must be a JSON object"}, status_code=400)

    answer = body.get("answer")
    if not isinstance(answer, str):
        return JSONResponse(
            {"error": "'answer' must be a string"}, status_code=400
        )

    report = check_grounding(answer, body.get("tool_results", []))
    return JSONResponse({**report.to_dict(), "summary": report.summary()})


def build_app(*, allow_origins: list[str] | None = None) -> Starlette:
    """The Starlette app. CORS is open to localhost dev origins by default."""
    origins = allow_origins or ["http://localhost:3000", "http://127.0.0.1:3000"]
    return Starlette(
        routes=[
            Route("/health", health, methods=["GET"]),
            Route("/tools", list_tools, methods=["GET"]),
            Route("/tools/{name}", call_tool, methods=["POST"]),
            Route("/grounding/check", grounding_check, methods=["POST"]),
        ],
        middleware=[
            Middleware(
                CORSMiddleware,
                allow_origins=origins,
                allow_methods=["GET", "POST"],
                allow_headers=["content-type"],
                # Authorization / X-Eve-Internal are deliberately NOT allowed
                # cross-origin: only the Hisaab server calls with them.
            )
        ],
    )


app = build_app()


def main() -> None:
    parser = argparse.ArgumentParser(description="HTTP bridge for the quant engine")
    parser.add_argument("--host", default="127.0.0.1")
    parser.add_argument("--port", type=int, default=DEFAULT_PORT)
    args = parser.parse_args()

    if args.host not in ("127.0.0.1", "localhost", "::1") and not internal_secret():
        raise SystemExit(
            f"refusing to bind {args.host} without EVE_INTERNAL_SECRET: the bridge "
            "would be reachable by anyone on the network. Set the secret (and give "
            "the same value to Hisaab) or bind 127.0.0.1."
        )

    import uvicorn

    mode = "read+write" if WRITE_TOOLS_ENABLED else "read-only"
    auth = "internal secret + Supabase JWT" if internal_secret() else "local (no secret)"
    print(
        f"quant-http-bridge: {len(_TOOLS)} tools ({mode}, auth: {auth}) "
        f"on http://{args.host}:{args.port}"
    )
    if not WRITE_TOOLS_ENABLED:
        print(f"  withheld: {', '.join(sorted(_WRITE_TOOLS))} "
              f"(set QUANT_ALLOW_WRITE_TOOLS=1 to enable)")
    uvicorn.run(app, host=args.host, port=args.port, log_level="info")


if __name__ == "__main__":
    main()
