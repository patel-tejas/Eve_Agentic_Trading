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
import asyncio
import inspect
import json
import os
import traceback
from typing import Any, Callable

from starlette.applications import Starlette
from starlette.middleware import Middleware
from starlette.middleware.cors import CORSMiddleware
from starlette.requests import Request
from starlette.responses import JSONResponse
from starlette.routing import Route

from mcp.quant_server.grounding import check_grounding
from mcp.quant_server.server import _TOOL_FUNCTIONS

DEFAULT_PORT = 8010

# A tool call runs synchronous Polars work in a worker thread; this bounds it
# so a pathological grid cannot pin a request forever. The full 320-combination
# search over a month of 15m bars takes ~3s, so this is generous by ~100x.
TOOL_TIMEOUT_SECONDS = float(os.environ.get("QUANT_TOOL_TIMEOUT", "300"))

# Arguments the model must never set: they point at on-disk roots, and letting
# a generated payload choose them would turn a chat turn into arbitrary path
# access. They keep their defaults from server.py.
_INTERNAL_PARAMS = frozenset(
    {"processed_root", "raw_root", "results_root", "out_dir"}
)

# Tools with side effects: download_month_data calls the broker API,
# process_month_data OVERWRITES parquet under data/processed/. A system-prompt
# instruction to "ask first" is not enforcement -- a model that ignores it can
# destroy a processed month -- so they are withheld from the manifest and
# refused at the endpoint unless explicitly enabled.
_WRITE_TOOLS = frozenset({"download_month_data", "process_month_data"})

WRITE_TOOLS_ENABLED = os.environ.get("QUANT_ALLOW_WRITE_TOOLS", "").lower() in {
    "1",
    "true",
    "yes",
}

_ALL_TOOLS: dict[str, Callable[..., Any]] = {fn.__name__: fn for fn in _TOOL_FUNCTIONS}
_TOOLS: dict[str, Callable[..., Any]] = {
    name: fn
    for name, fn in _ALL_TOOLS.items()
    if WRITE_TOOLS_ENABLED or name not in _WRITE_TOOLS
}

_JSON_TYPES: dict[Any, str] = {
    str: "string",
    int: "integer",
    float: "number",
    bool: "boolean",
}


def _describe(fn: Callable[..., Any]) -> str:
    """Full docstring, whitespace-normalised -- the model reads this."""
    doc = inspect.getdoc(fn) or ""
    return " ".join(doc.split())


def _schema(fn: Callable[..., Any]) -> dict[str, Any]:
    """JSON Schema for a tool's callable signature.

    Derived from the annotations rather than hand-written, so a signature
    change in ``server.py`` cannot silently desynchronise the tool the model
    is offered from the function that runs.
    """
    properties: dict[str, Any] = {}
    required: list[str] = []

    for name, param in inspect.signature(fn).parameters.items():
        if name in _INTERNAL_PARAMS:
            continue
        prop: dict[str, Any] = {"type": _JSON_TYPES.get(param.annotation, "string")}
        if param.default is inspect.Parameter.empty:
            required.append(name)
        else:
            prop["default"] = param.default
        properties[name] = prop

    return {
        "type": "object",
        "properties": properties,
        "required": required,
        "additionalProperties": False,
    }


def tool_manifest() -> list[dict[str, Any]]:
    """Every tool as ``{name, description, parameters}``."""
    return [
        {"name": name, "description": _describe(fn), "parameters": _schema(fn)}
        for name, fn in _TOOLS.items()
    ]


async def health(_: Request) -> JSONResponse:
    return JSONResponse({"ok": True, "service": "quant-http-bridge", "tools": len(_TOOLS)})


async def list_tools(_: Request) -> JSONResponse:
    return JSONResponse({"tools": tool_manifest()})


async def call_tool(request: Request) -> JSONResponse:
    name = request.path_params["name"]
    fn = _TOOLS.get(name)
    if fn is None:
        if name in _WRITE_TOOLS:
            return JSONResponse(
                {
                    "error": (
                        f"{name} modifies data and is disabled. Set "
                        "QUANT_ALLOW_WRITE_TOOLS=1 and restart the bridge to "
                        "enable it."
                    )
                },
                status_code=403,
            )
        return JSONResponse(
            {"error": f"unknown tool {name!r}", "available": sorted(_TOOLS)},
            status_code=404,
        )

    try:
        raw = await request.body()
        args = json.loads(raw) if raw.strip() else {}
    except json.JSONDecodeError as exc:
        return JSONResponse({"error": f"invalid JSON body: {exc}"}, status_code=400)
    if not isinstance(args, dict):
        return JSONResponse({"error": "body must be a JSON object"}, status_code=400)

    # Drop path-valued parameters and anything the signature does not accept,
    # so a hallucinated argument name is a no-op rather than a 500.
    accepted = set(inspect.signature(fn).parameters) - _INTERNAL_PARAMS
    ignored = sorted(set(args) - accepted)
    kwargs = {k: v for k, v in args.items() if k in accepted}

    try:
        result = await asyncio.wait_for(
            asyncio.to_thread(fn, **kwargs), timeout=TOOL_TIMEOUT_SECONDS
        )
    except asyncio.TimeoutError:
        return JSONResponse(
            {
                "error": (
                    f"{name} exceeded {TOOL_TIMEOUT_SECONDS:.0f}s. Retry with a "
                    "smaller grid or a coarser timeframe."
                )
            },
            status_code=504,
        )
    except (ValueError, FileNotFoundError, TypeError) as exc:
        # Expected, actionable failures: bad month, absent parquet, wrong
        # argument shape. The model can correct these on its own, so the
        # message matters more than the status code.
        return JSONResponse({"error": f"{type(exc).__name__}: {exc}"}, status_code=400)
    except Exception as exc:  # pragma: no cover - genuine server fault
        traceback.print_exc()
        return JSONResponse(
            {"error": f"internal error in {name}: {type(exc).__name__}: {exc}"},
            status_code=500,
        )

    payload: dict[str, Any] = {"tool": name, "result": result}
    if ignored:
        payload["ignored_arguments"] = ignored
    return JSONResponse(payload)


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
            )
        ],
    )


app = build_app()


def main() -> None:
    parser = argparse.ArgumentParser(description="HTTP bridge for the quant engine")
    parser.add_argument("--host", default="127.0.0.1")
    parser.add_argument("--port", type=int, default=DEFAULT_PORT)
    args = parser.parse_args()

    import uvicorn

    mode = "read+write" if WRITE_TOOLS_ENABLED else "read-only"
    print(
        f"quant-http-bridge: {len(_TOOLS)} tools ({mode}) "
        f"on http://{args.host}:{args.port}"
    )
    if not WRITE_TOOLS_ENABLED:
        print(f"  withheld: {', '.join(sorted(_WRITE_TOOLS))} "
              f"(set QUANT_ALLOW_WRITE_TOOLS=1 to enable)")
    uvicorn.run(app, host=args.host, port=args.port, log_level="info")


if __name__ == "__main__":
    main()
