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

- [ ] Eve agent configured
- [ ] All 5 core MCP tools implemented
- [ ] Skills created for domain knowledge
- [ ] Subagent architecture implemented
- [ ] "Backtest NIFTY strategy for July" works end-to-end
- [ ] Agent does NOT perform financial calculations itself
- [ ] Tool results are deterministic and reproducible

## Open Questions

- Does Eve require specific project structure?
- How to handle tool failures gracefully?
- Agent evaluation: how to test for hallucinated data?
- How to handle long-running backtests (timeout)?
- Should agent have access to raw Parquet files or only through tools?
