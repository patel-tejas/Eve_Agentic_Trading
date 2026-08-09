# Agent (Eve)

Orchestration layer for the AI agent. **Skeleton only — implemented in Phase 07.**

Structure per proposal §11:

```
agent/
├── instructions.md   ← main agent instructions
├── tools/            ← MCP-backed tools (get_futures_contract, run_backtest, ...)
├── skills/           ← domain instructions (ema-strategy, backtesting, ...)
├── subagents/        ← data-agent, strategy-agent, research-agent
├── evals/            ← agent evaluation tests
└── connections/      ← MCP connections
```

Principle: the agent orchestrates tool calls but never performs financial
calculations itself. See `docs/phases/phase-07_eve-agent.md`.