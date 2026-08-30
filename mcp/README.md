# quant-server (MCP)

MCP server exposing the deterministic quant engine (`quant/`) as tools for
the Eve agent. **Implemented in Phase 07.**

## Tools

| Tool | Wraps |
|---|---|
| `list_research_months` | metadata scan of `data/processed/` |
| `get_historical_candles` | processed parquet reader |
| `download_month_data` | `quant.data.download` (network) |
| `validate_dataset` | `quant.data.validation` |
| `process_month_data` | `quant.processing.pipeline` |
| `generate_signal` | `quant.strategies.ema_9_15` |
| `run_backtest_signals` | `quant.backtest.engine` |
| `compare_timeframes` | `quant.research.baseline` |
| `parameter_search` | `quant.research.parameter_search` |
| `walk_forward_test` | `quant.research.walk_forward` |
| `backtest_significance` | `quant.research.significance` (phase 08b) |
| `validate_parameter_search` | `quant.research.validate` (phase 08b) |

`parameter_search` reports the best of ~320 combinations; `validate_parameter_search`
runs the same grid and adds the corrections that number needs (deflated Sharpe,
bootstrap interval, PBO). Prefer the latter whenever a search result is going to
be acted on.

Design rules (see `server.py` docstring): the server validates arguments,
calls `quant/`, and serializes JSON-safe results. **No financial logic
lives here**; tools are plain functions (unit-tested) decorated onto the
FastMCP app.

## Two surfaces, one tool set

`server.py` defines the tools once, in `_TOOL_FUNCTIONS`. Both surfaces mount
that same tuple, so they cannot drift apart:

| Surface | Module | Consumer |
|---|---|---|
| MCP (stdio) | `quant_server/server.py` | Claude Code, opencode, any MCP client |
| HTTP/JSON | `quant_server/http_bridge.py` | the Next.js chat in `apps/web/` |

The bridge exists because a Node runtime cannot import `quant/`, and FastMCP's
HTTP transport is session-oriented (handshake, SSE, session ids) — a lot of
protocol to reimplement in a route handler for no benefit. It derives JSON
Schema from each function signature by introspection, and strips
filesystem-valued parameters (`processed_root`, `raw_root`, `results_root`,
`out_dir`) so a generated payload can never choose a path.

### Bridge endpoints

| Method | Path | Returns |
|---|---|---|
| GET | `/health` | liveness + tool count |
| GET | `/tools` | name, description, JSON Schema per tool |
| POST | `/tools/{name}` | `{tool, result}`, or `{error}` with a 4xx |

An engine error (bad month, missing parquet) comes back as a 400 with an
actionable message rather than a 500, because the model can correct those on
its own.

## Run

```bash
# MCP (stdio)
uv run python -m mcp.quant_server.server

# HTTP bridge for the web app
uv run python -m mcp.quant_server.http_bridge          # port 8010
```

`opencode.json` registers it as the local `quant` MCP server, spawned from
the repository root.

## Test

```bash
uv run pytest tests/test_phase07_mcp.py tests/test_phase07b_http_bridge.py -q
```