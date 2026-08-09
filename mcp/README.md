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

Design rules (see `server.py` docstring): the server validates arguments,
calls `quant/`, and serializes JSON-safe results. **No financial logic
lives here**; tools are plain functions (unit-tested) decorated onto the
FastMCP app.

## Run

```bash
uv run python -m mcp.quant_server.server
```

`opencode.json` registers it as the local `quant` MCP server, spawned from
the repository root.

## Test

```bash
uv run pytest tests/test_phase07_mcp.py -q
```