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

### Strategy builder (Phase 15)

| Tool | Tier | What it does |
|---|---|---|
| `describe_strategy_vocabulary` | read | indicators, levels, comparators, limits, months |
| `validate_strategy_spec` | read | checks an `eve.strategy/1` spec; JSON-Pointer errors, summary, hash |
| `preview_strategy_signals` | compute | when the rules fire on one month, no P&L |
| `backtest_strategy_spec` | compute | the spec through the normal engine |
| `strategy_significance` | compute_heavy | bootstrap Sharpe CI and permutation test |
| `list_my_strategies` / `get_my_strategy` | user_read | the caller's saved strategies, versions, backtests |
| `save_strategy` / `revise_strategy` | user_write | version 1 / version N+1 (immutable, diffed, counted as trials) |
| `backtest_saved_strategy` | user_write | recorded against the exact version |
| `evaluate_saved_strategy` | user_write | holdout month, trials-adjusted Sharpe, buy-and-hold, verdict |
| `paper_results` | user_write | forward test on bars after promotion |
| `trading_controls` | user_read | kill switch state |
| `engage_kill_switch` | safety | stops every paper run; the only thing chat may do to trading |
| `archive_strategy`, `stop_paper`, `release_kill_switch` | user_write, UI only | Hisaab buttons, never chat |
| `promote_to_paper` | trade_paper, UI only | blocked by the kill switch |

A spec is data, never code: one registered strategy (`rule_spec`) interprets
every spec through the same engine as everything else. No tool is in the
`trade_live` tier and nothing places an order.

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

## The common gate

Every call, from either surface, goes through `gate.Gate.invoke`:

1. look up the tool's row in `policy.TOOL_POLICY` (a tool without one cannot be served);
2. authorise its tier: `trade_live` is denied; `data_write` needs
   `QUANT_ALLOW_WRITE_TOOLS`; UI-only tools need `X-Eve-Surface: ui`; user
   tiers need a verified user; trading tiers check the kill switch
   (`EVE_KILL_SWITCH` and `algo_trading_controls`, failing closed);
3. strip internal path parameters and identity arguments (`user_id` is never
   taken from a caller);
4. validate arguments with pydantic (errors carry JSON Pointers);
5. rate-limit per user and tier; run with a timeout; check the output size;
6. write an audit record (JSONL, plus `algo_tool_audit` when configured).

Callers identify themselves to the bridge with `X-Eve-Internal`
(`EVE_INTERNAL_SECRET`) and `Authorization: Bearer <Supabase access token>`.
Saved strategies are read and written through PostgREST *as that user*, so
Supabase row-level security applies as a second line. `EVE_LOCAL_DEV=1` with
`EVE_LOCAL_USER_ID` gives a local research console a user and a SQLite store.

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
uv run pytest tests/test_phase15_*.py -q   # gate, spec, store, evaluation, paper
```