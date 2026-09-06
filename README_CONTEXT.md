# Eve Agentic Trading — Context for README rewrite

## What the project is (one-line)
Eve is an AI-powered quant research & backtesting platform for NIFTY futures. The agent
orchestrates work in natural language; a deterministic Python engine does all the math.

## Core architecture principle (THE most important thing)
"AI orchestrates; Python calculates." The LLM NEVER does financial calculations.
Every number in any answer traces to a `quant/` module that's pure functions of its inputs.
This is enforced structurally — the engine has no network access, no LLM calls, no
state. Same input -> same output. Ever.

## The 12 MCP tools (deterministic, exposed to both the chat frontend AND any MCP client)
1. `list_research_months` — List processed research months and their bar counts per timeframe.
2. `get_historical_candles` — Read processed OHLCV candles for a month+timeframe (deterministic parquet).
3. `download_month_data` — Fetch a research month of NIFTY futures 1m candles from the data provider (Upstox/Dhan).
4. `validate_dataset` — Run the full phase-02 validation suite on a raw 1m dataset.
5. `process_month_data` — Validate raw 1m, resample to 5m/15m, add EMA9/15 + angle indicators.
6. `generate_signal` — Generate BUY/SELL/HOLD signals for a processed month+timeframe.
7. `run_backtest_signals` — Run a full backtest with realistic costs & slippage on a processed month+timeframe.
8. `compare_timeframes` — Run baseline variants A/B/C across timeframes (phase-06).
9. `parameter_search` — Grid-search strategy parameters on the TRAINING windows (phase-08).
10. `walk_forward_test` — Walk-forward validation: calibrate on training windows, test on out-of-sample.
11. `backtest_significance` — Bootstrap Sharpe CI + Monte-Carlo permutation test (deflated Sharpe, multiple-testing correction).
12. `validate_parameter_search` — Statistical validation of grid search results (Bonferroni / Holm / BH).

## HTTP bridge (the chat frontend's surface)
- `GET /health` — service health + number of available tools
- `GET /tools` — tool manifest (auto-derived from each tool's Python signature, never hand-written)
- `POST /tools/{name}` — invoke any tool with JSON body

## The chat UX (the user's actual experience)
- Next.js 16 frontend at `apps/web/`
- Groq (Llama) is the LLM; it calls the engine via the HTTP bridge
- Tool definitions are auto-generated from Python signatures — adding a tool in `mcp/quant_server/server.py` makes it appear in the chat with ZERO TypeScript change
- **Every tool call is shown, not hidden.** Each one renders as an expandable card with its input args and raw JSON output. The user can expand to see the exact computation that produced any number
- The header shows engine reachability + model-key presence, so failures are legible before you ask
- Path arguments (e.g. `processed_root`) are STRIPPED from the published schema — the model can't tell the engine where to write, only what to compute

## The 4 example prompts that ship in the UI (from apps/web/app/page.tsx)
```javascript
const EXAMPLES = [
  "What research months are available?",
  "Backtest EMA 9/15 on July 2026, 15m",
  "Compare 1m, 5m and 15m for July 2026",
  "Run a parameter search on 15m July and show the top 5",
];
```

## Tech stack
| Layer | Tech |
|-------|------|
| Quant engine | Python (Polars, DuckDB, PyArrow, NumPy) — `quant/` |
| Agent / orchestration | Groq (Llama) via AI SDK — `apps/web/app/api/chat/` |
| Tool protocol | MCP — `mcp/quant_server/server.py` (FastMCP, Phase 07) |
| Tool transport (web) | HTTP bridge — `mcp/quant_server/http_bridge.py` (Phase 07b) |
| Frontend | Next.js 16 + TypeScript + Tailwind — `apps/web/` |
| Broker / data | DhanHQ + Upstox (multi-broker data layer) |
| Local storage | Parquet (`data/raw`, `data/processed`, `data/results`) + DuckDB |
| Warehouse (future) | Snowflake (Phase 09) |
| Streaming (future) | Kafka (Phase 11) |
| Paper trading (future) | Phase 12 |
| Risk engine (future) | Phase 13 |
| Human-approved live trading (future) | Phase 14 |

## Phases (current state)
Done:
- Phase 00 — Project foundation
- Phase 01 — Dhan data acquisition
- Phase 02 — Data validation (Parquet, DuckDB)
- Phase 03 — Candle processing (1m -> 5m/15m + indicators)
- Phase 04 — Strategy engine (EMA 9/15 + angle filter)
- Phase 05 — Backtester (costs, slippage, metrics)
- Phase 06 — Baseline results (variants A/B/C across timeframes)
- Phase 07 — Eve agent (FastMCP boundary)
- Phase 07b — HTTP bridge for chat
- Phase 08 — Advanced research (grid search, walk-forward)
- Phase 08b — Statistical validation (deflated Sharpe, Bonferroni/Holm/BH)

Future:
- Phase 09 — Snowflake warehouse
- Phase 10 — Real-time data
- Phase 11 — Kafka streaming
- Phase 12 — Paper trading
- Phase 13 — Risk engine
- Phase 14 — Human-approved live trading

## Recent commits (showing momentum)
- `7422291` feat(validation): add backtest significance and parameter validation tools to MCP and HTTP bridge
- `f3a728d` Add unit tests for HTTP bridge and statistical validation
- `110e003` EVE MCP IS LIVE! Refactor code structure for improved readability
- `54627ce` feat(research): implement Phase 08 parameter grid search, walk-forward, regime analysis
- `cc3e042` Add build system and package finding settings in pyproject.toml

## Who this is for
- Quant researchers who want an AI front-end on a deterministic engine (no more asking an LLM "what's the Sharpe" and getting a confident number with no audit trail)
- Engineers who want to use LLMs in trading without trusting them with the math
- Anyone studying Indian equity derivatives (NIFTY futures specifically) who wants reproducible research

## What NOT to do in the README
- Don't claim this trades real money — Phases 12-14 are future
- Don't add emojis unless they aid scannability
- Don't bury the "AI orchestrates; Python calculates" principle — it's the key differentiator
- Don't include fake screenshots — describe UI honestly instead
- Don't pad with marketing fluff — keep it engineer-honest
