"""Every tool both surfaces serve, in one tuple (Phase 15).

``server._TOOL_FUNCTIONS`` holds the Phase 07/08 research tools; the
strategy-builder tools are appended here. The stdio server and the HTTP
bridge both mount ``ALL_TOOL_FUNCTIONS`` through the gate, and every entry
must have a row in ``policy.TOOL_POLICY`` (the gate refuses to start
otherwise).
"""

from __future__ import annotations

from mcp.quant_server.paper_tools import PAPER_TOOL_FUNCTIONS
from mcp.quant_server.server import _TOOL_FUNCTIONS
from mcp.quant_server.store_tools import STORE_TOOL_FUNCTIONS
from mcp.quant_server.strategy_tools import STRATEGY_TOOL_FUNCTIONS

ALL_TOOL_FUNCTIONS: tuple = (
    *_TOOL_FUNCTIONS,
    *STRATEGY_TOOL_FUNCTIONS,
    *STORE_TOOL_FUNCTIONS,
    *PAPER_TOOL_FUNCTIONS,
)
ALL_TOOL_NAMES = tuple(fn.__name__ for fn in ALL_TOOL_FUNCTIONS)
