# Phase 07 — Eve Agent

## Goal

Create the AI agent layer using Eve: tools, skills, and subagents that allow natural-language research workflows (e.g., "Backtest NIFTY strategy for July").

## What We're Building

The AI orchestration layer that sits on top of the deterministic quant engine. The agent handles user interaction, tool selection, and workflow orchestration — but never performs financial calculations itself.

## Deliverables

- Eve agent configured with instructions
- MCP tools: `get_futures_contract`, `get_historical_data`, `validate_dataset`, `run_backtest`, `compare_timeframes`
- Skills: market-data, futures-research, ema-strategy, backtesting
- Subagents: data-agent, strategy-agent, research-agent
- Natural-language research workflow working

## Key Concepts

### Agent Architecture

```
User Request
     ↓
Eve Agent (orchestration)
     ↓
Tool Selection (MCP)
     ↓
Deterministic Tool (Python)
     ↓
Verified Result
     ↓
Agent Explanation (LLM)
```

### MCP Tools

**Data Tools:**
- `get_instruments` — List available instruments from DhanHQ
- `get_futures_contract` — Resolve NIFTY Futures contract for a given month
- `get_historical_candles` — Fetch historical candles from DhanHQ
- `validate_dataset` — Run validation checks on a dataset

**Strategy Tools:**
- `calculate_ema` — Calculate EMA for a given period
- `calculate_ema_angle` — Calculate normalized slope → angle
- `generate_signal` — Generate BUY/SELL/HOLD signals

**Research Tools:**
- `run_backtest` — Execute a backtest with given config
- `compare_timeframes` — Compare strategy across timeframes
- `parameter_search` — Grid search over parameter space

### Agent Skills

Skills are domain-specific instruction files that prevent the main agent prompt from becoming huge.

**ema-strategy.md:**
```markdown
Strategy: 9 EMA / 15 EMA
BUY: Bullish crossover AND positive angle >= 30°
SELL: Bearish crossover AND negative angle <= -30°
Signal: Only after candle close
Execution: Next candle open
```

**backtesting.md:**
```markdown
- Use next-candle execution (no look-ahead)
- Include transaction costs
- Apply slippage
- Calculate all metrics
- Store results with experiment ID
```

### Subagent Architecture

```
Main Research Agent
    ├── Data Agent
    │   ├── instrument discovery
    │   ├── contract resolution
    │   ├── historical data retrieval
    │   └── data validation
    ├── Strategy Agent
    │   ├── indicator configuration
    │   ├── strategy definitions
    │   ├── signal generation
    │   └── strategy versioning
    └── Research Agent
        ├── backtesting
        ├── metric calculation
        ├── parameter experiments
        ├── timeframe comparisons
        └── report generation
```

### Example Workflow

```
User: "Backtest NIFTY 9/15 EMA with 30 degree angle on July."

Eve:
1. Resolve NIFTY futures contract → data agent
2. Check whether July data exists → data agent
3. Fetch missing data if required → data agent
4. Validate dataset → data agent
5. Run 1m backtest → research agent
6. Run 5m backtest → research agent
7. Run 15m backtest → research agent
8. Compare metrics → research agent
9. Generate research report → research agent
```

## Data Contracts

### Input
- Natural language user request
- Existing datasets in `data/`
- Strategy configs

### Output
- Tool call results (structured JSON)
- Agent response (natural language)
- Research reports

## Dependencies

- Phase 06 (baseline results — must exist for agent to orchestrate)
- Eve runtime
- MCP protocol

## Definition of Done

- [x] Eve agent configured
- [x] All 5 core MCP tools implemented (10 tools in total)
- [x] Skills created for domain knowledge
- [x] Subagent architecture implemented
- [x] "Backtest NIFTY strategy for July" works end-to-end
- [x] Agent does NOT perform financial calculations itself
- [x] Tool results are deterministic and reproducible

## Implementation Notes (2026-08-09)

Runtime: OpenCode-native. Agent layer in `agent/`, MCP server in
`mcp/quant_server/`, skills in `.opencode/skills/`, subagents in
`.opencode/agent/`. Registered as the `quant` MCP server in `opencode.json`
(command: `uv run python -m mcp.quant_server.server`).

Tools built: `list_research_months`, `get_historical_candles`,
`download_month_data`, `validate_dataset`, `process_month_data`,
`generate_signal`, `run_backtest_signals`, `compare_timeframes`,
`parameter_search`, `walk_forward_test`. Tools are plain sync functions
(unit-tested, network-free) decorated onto the FastMCP app; `parameter_search`
and `walk_forward_test` default to the phase-08 grids and training-window-only
calibration.

Verification:
- 14 new unit tests (`tests/test_phase07_mcp.py`) — tool schema, determinism,
  error hints (missing month -> what to run next). 91 tests total, lint clean.
- `agent/evals/golden_workflow.py` reproduces the documented July baseline
  numbers exactly (B: 1m 2 trades -18,672 / 5m 4 trades -20,225 /
  15m 4 trades +5,737; 9 experiments; 320-combo grid best 5m = 7/21): the
  agent's answers are pinned to the engine, not to the model.

## Open Questions (resolved)

- ~~Does Eve require specific project structure?~~ -> OpenCode-native
  (subagents/skills/MCP) inside the repo.
- ~~How to handle tool failures gracefully?~~ -> structured ValueError with
  hints (available months, next tool to run).
- ~~Agent evaluation: how to test hallucinated data?~~ -> golden workflow
  pytest-style regression pins every number to the engine; agent never
  computes.
- ~~How to handle long-running backtests (timeout)?~~ -> 1m grid is slowest;
  instructions say to narrow grids or prefer 5m/15m first.
- ~~Should agent have access to raw Parquet files or only through tools?~~ ->
  Tools only; subagents get `edit: deny` + no webfetch/websearch and only
  read data through the MCP tools.
