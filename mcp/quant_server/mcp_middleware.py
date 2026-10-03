"""FastMCP middleware that routes every stdio tool call through the gate.

Without this, the stdio server registered the write tools unconditionally and
let any MCP client set ``processed_root``. Now ``tools/list`` shows only what
the gate offers, with internal parameters removed, and ``tools/call`` never
reaches FastMCP's own dispatch: the gate validates, authorises, runs, audits
and returns the result itself. A refusal comes back as a tool error
(``isError``) the client can read, or an ``AuthorizationError`` for auth.
"""

from __future__ import annotations

from collections.abc import Sequence
from typing import Any

import mcp.types as mt
from fastmcp.exceptions import AuthorizationError, ToolError
from fastmcp.server.middleware import CallNext, Middleware, MiddlewareContext
from fastmcp.tools.base import Tool, ToolResult

from mcp.quant_server.auth import Principal, principal_from_env
from mcp.quant_server.gate import IDENTITY_PARAMS, INTERNAL_PARAMS, Gate, GateError


def _strip_params(tool: Tool) -> Tool:
    params = dict(tool.parameters or {})
    props = {
        k: v
        for k, v in (params.get("properties") or {}).items()
        if k not in INTERNAL_PARAMS and k not in IDENTITY_PARAMS
    }
    params["properties"] = props
    if "required" in params:
        params["required"] = [r for r in params["required"] if r in props]
    return tool.model_copy(update={"parameters": params})


class TradingGateMiddleware(Middleware):
    def __init__(self, gate: Gate, principal: Principal | None = None) -> None:
        self.gate = gate
        self._principal = principal

    def principal(self) -> Principal:
        return self._principal or principal_from_env()

    async def on_list_tools(
        self,
        context: MiddlewareContext[mt.ListToolsRequest],
        call_next: CallNext[mt.ListToolsRequest, Sequence[Tool]],
    ) -> Sequence[Tool]:
        tools = await call_next(context)
        return [_strip_params(t) for t in tools if self.gate.is_offered(t.name, "mcp")]

    async def on_call_tool(
        self,
        context: MiddlewareContext[mt.CallToolRequestParams],
        call_next: CallNext[mt.CallToolRequestParams, ToolResult],
    ) -> ToolResult:
        name = context.message.name
        args: dict[str, Any] = dict(context.message.arguments or {})
        try:
            payload = await self.gate.invoke(name, args, self.principal(), surface="mcp")
        except GateError as exc:
            if exc.status in (401, 403):
                raise AuthorizationError(exc.message) from exc
            raise ToolError(exc.message) from exc
        result = payload["result"]
        structured = result if isinstance(result, dict) else {"result": result}
        if payload.get("ignored_arguments"):
            structured = {**structured, "ignored_arguments": payload["ignored_arguments"]}
        return ToolResult(structured_content=structured)
