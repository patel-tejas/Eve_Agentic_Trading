# Eve Agentic Trading

Eve is an AI-powered quantitative research and backtesting platform for
Indian equity derivatives (NIFTY futures). You ask questions in natural
language; the LLM interprets your intent and calls deterministic Python
tools that return real numbers. The model never performs financial
calculations itself. Every figure in every answer traces to a function in
`quant/` that is pure, reproducible, and testable. Same input, same
output, always.

This is not a chatbot that guesses at Sharpe ratios. It is a research
environment where the AI orchestrates and Python calculates.

---

## Capabilities

Eve exposes 12 tools through the MCP (Model Context Protocol), covering
the full lifecycle of a quant research session: data acquisition,
signal generation, backtesting, multi-timeframe comparison, parameter
search, and statistical validation.

### Data

| Tool | What it does |
|------|-------------|
| `list_research_months` | List all processed months with bar counts per timeframe. |
| `get_historical_candles` | Read processed OHLCV candles (parquet) for a month and timeframe. Returns schema, date range, and a configurable preview window. |
| `download_month_data` | Fetch a month of NIFTY futures 1m candles from the data provider. Hits the network. |
| `validate_dataset` | Run the full validation suite on a raw 1m dataset: gaps, duplicates, session boundaries, holiday coverage. |
| `process_month_data` | Validate raw 1m data, resample to 5m/15m, and add EMA9/15 + angle indicators. Idempotent. |

### Signals and Backtest

| Tool | What it does |
|------|-------------|
| `generate_signal` | Generate BUY/SELL/HOLD signals for a strategy config on a processed month+timeframe. |
| `run_backtest_signals` | Full backtest with realistic costs and slippage. Returns metrics: net P&L, profit factor, drawdown, Sharpe, Sortino, Calmar, and more. |
| `compare_timeframes` | Run baseline variants (A: crossover-only, B: crossover+angle, C: crossover+angle+trend) across 1m/5m/15m. Returns a side-by-side comparison table. |

### Research and Validation

| Tool | What it does |
|------|-------------|
| `parameter_search` | Grid-search strategy parameters on the training window (first 23 days). Returns the top-N combinations ranked by net P&L. |
| `walk_forward_test` | Calibrate on rolling training windows, evaluate on held-out test windows. The out-of-sample evidence for whether parameters generalize. |
| `backtest_significance` | Bootstrap Sharpe confidence interval + Monte Carlo permutation test for a single backtest. Answers: is this distinguishable from luck? |
| `validate_parameter_search` | Grid search plus deflated Sharpe, bootstrap, permutation test, and PBO. Answers: does the winning configuration survive multiple-testing correction? |

---

## Live examples

The four example prompts that ship in the chat UI, with realistic
tool call sequences and representative responses.

### 1. What research months are available?

**Prompt:** `What research months are available?`

**Tool call:** `list_research_months({})`

**Response shape:**
```json
{
  "months": {
    "2026-06": { "1m": 5023, "5m": 1005, "15m": 336 },
    "2026-07": { "1m": 5220, "5m": 1044, "15m": 348 }
  }
}
```

**Eve's answer:** Two months are processed — June 2026 and July 2026.
Each has 1m, 5m, and 15m candles ready for research. July has slightly
more bars (348 on 15m vs 336 for June).

---

### 2. Backtest EMA 9/15 on July 2026, 15m

**Prompt:** `Backtest EMA 9/15 on July 2026, 15m`

**Tool call:** `run_backtest_signals({ month: "2026-07", timeframe: "15m" })`

Default config: fast_ema=9, slow_ema=15, angle_threshold=30.0,
angle_lookback=1, signal_mode=crossover_and_angle. Execution is
next-candle-open with normal (1-tick) slippage.

**Response shape (metrics):**
```json
{
  "month": "2026-07",
  "timeframe": "15m",
  "config": {
    "fast_ema": 9,
    "slow_ema": 15,
    "angle_threshold": 30.0,
    "angle_lookback": 1,
    "signal_mode": "crossover_and_angle"
  },
  "slippage": "normal",
  "metrics": {
    "total_trades": 12,
    "win_rate": 0.417,
    "gross_pnl": 48200,
    "net_pnl": 39680,
    "profit_factor": 1.89,
    "avg_trade_pnl": 3307,
    "avg_holding_periods": 18.5,
    "max_drawdown_pct": 3.2,
    "max_drawdown_duration_bars": 45,
    "sharpe": 1.32,
    "sortino": 1.87,
    "calmar": 2.15,
    "trading_days": 22
  },
  "equity": {
    "start": 1000000,
    "end": 1039680,
    "bars": 348
  }
}
```

**Eve's answer:** 12 trades on 15m, net P&L +39,680 (after costs and
1-tick slippage). Profit factor 1.89, max drawdown 3.2%. Sharpe 1.32.
Execution assumption: signals fire at candle close, fills at next candle
open.

---

### 3. Compare 1m, 5m and 15m for July 2026

**Prompt:** `Compare 1m, 5m and 15m for July 2026`

**Tool call:** `compare_timeframes({ month: "2026-07" })`

This runs three variants across three timeframes (9 experiments total):
- Variant A: EMA crossover only (no angle filter)
- Variant B: EMA crossover + angle filter (default)
- Variant C: EMA crossover + angle + trend filter

**Response shape (comparison table excerpt):**
```json
{
  "month": "2026-07",
  "experiment_count": 9,
  "comparison_table": [
    {
      "experiment_id": "RE-0001",
      "variant": "A",
      "timeframe": "1m",
      "metrics": { "total_trades": 247, "net_pnl": 18420, "profit_factor": 1.12, "sharpe": 0.41 }
    },
    {
      "experiment_id": "RE-0004",
      "variant": "B",
      "timeframe": "15m",
      "metrics": { "total_trades": 12, "net_pnl": 39680, "profit_factor": 1.89, "sharpe": 1.32 }
    }
  ]
}
```

**Eve's answer:** Variant B on 15m produced the best risk-adjusted
returns (Sharpe 1.32) with only 12 trades. Variant A on 1m generated
247 trades but at a Sharpe of 0.41. Fewer, higher-conviction signals
on the slower timeframe outperformed the noisy 1m feed. All results
include costs and slippage.

---

### 4. Run a parameter search on 15m July and show the top 5

**Prompt:** `Run a parameter search on 15m July and show the top 5`

**Tool call:** `parameter_search({ month: "2026-07", timeframe: "15m" })`

Grid: fast_ema in {5,7,9,12}, slow_ema in {15,18,21,25},
angle_threshold in {20,25,30,35,40}, angle_lookback in {1,2,3,5}.
That is 4 x 4 x 5 x 4 = 320 combinations, evaluated on the training
window only (first 23 days of the month).

**Response shape (summary):**
```json
{
  "month": "2026-07",
  "timeframe": "15m",
  "train_window": ["2026-07-01", "2026-07-23"],
  "combinations": 320,
  "positive_share": 0.43,
  "median_net_pnl": 8200,
  "best": {
    "params": { "fast_ema": 12, "slow_ema": 25, "angle_threshold": 25, "angle_lookback": 2 },
    "net_pnl": 31400,
    "total_trades": 8,
    "profit_factor": 2.41
  },
  "top": [
    { "experiment_id": "PS-0001", "fast_ema": 12, "slow_ema": 25, "angle_threshold": 25, "angle_lookback": 2, "total_trades": 8, "net_pnl": 31400, "profit_factor": 2.41, "win_rate": 0.625, "max_drawdown_pct": 2.1 },
    { "experiment_id": "PS-0002", "fast_ema": 9, "slow_ema": 21, "angle_threshold": 30, "angle_lookback": 1, "total_trades": 11, "net_pnl": 28900, "profit_factor": 2.15, "win_rate": 0.545, "max_drawdown_pct": 2.8 }
  ]
}
```

**Eve's answer:** 320 combinations tested on the training window.
43% were profitable. The best: EMA 12/25, angle 25 degrees, lookback 2
— 8 trades, net +31,400, profit factor 2.41. Note: these are
in-sample results. Use `walk_forward_test` or
`validate_parameter_search` to check whether they generalize.

---

## Architecture

```
+------------------+       +-----------------+       +------------------+
|                  |  HTTP |                 |  MCP  |                  |
|   Chat UI        +------>|   HTTP Bridge   +------>|  quant/ engine   |
|   (Next.js 16)   |       |   (FastAPI)     |       |  (Python,        |
|   apps/web/      |       |   port 8010     |       |   deterministic) |
|                  |       |                 |       |                  |
+------------------+       +-----------------+       +------------------+
       ^                                                   |
       |                                                   v
   User types                                        Parquet files
   natural language                                  (data/processed,
                                                     data/results)
```

The user interacts with a Next.js chat interface. The LLM (Groq, Llama)
interprets the request and emits tool calls. The HTTP bridge receives
these calls, routes them to the corresponding Python function in
`mcp/quant_server/server.py`, and returns JSON results. The engine
reads from and writes to local parquet files. It has no network access,
no LLM calls, and no mutable state.

---

## Why this design

### Deterministic Python for math

LLMs are good at understanding intent, parsing natural language, and
deciding which function to call with which arguments. They are bad at
arithmetic. A Sharpe ratio computed by an LLM is a guess. A Sharpe
ratio computed by `quant/backtest/engine.py` is a reproducible function
of its inputs.

By keeping the LLM out of the calculation path, every number in Eve's
responses is auditable. You can expand any tool call in the UI, see the
exact arguments, and verify the output against the source code. There
is no "temperature" in a Sharpe ratio.

### Auto-generated tool schemas

Tool definitions are derived from Python function signatures, not
hand-written in TypeScript. When a new tool is added to
`server.py`, it automatically appears in the HTTP bridge's `GET /tools`
manifest and becomes available to the chat frontend with zero
TypeScript changes. This eliminates the most common source of
sync-error between backend capabilities and frontend expectations.

### Tool calls are rendered, not hidden

Most AI chat UIs hide tool calls and show only the final answer. Eve
renders every tool call as an expandable card with its input arguments
and raw JSON output. This is a deliberate design choice: if you cannot
see which tool produced a number, you cannot trust it. Transparency
is not a UX preference here; it is a research integrity requirement.

Path arguments like `processed_root` are stripped from the published
schema. The model can ask the engine to compute anything, but it cannot
tell the engine where to write. This prevents accidental data
corruption from a hallucinated path.

---

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
| Live trading (future) | Phase 14 |

---

## Phases

Step-by-step implementation log: see `docs/phases/`.

### Completed

| Phase | What | Status |
|-------|------|--------|
| 00 | Project foundation | Done |
| 01 | Dhan data acquisition | Done |
| 02 | Data validation (Parquet, DuckDB) | Done |
| 03 | Candle processing (1m -> 5m/15m + indicators) | Done |
| 04 | Strategy engine (EMA 9/15 + angle filter) | Done |
| 05 | Backtester (costs, slippage, metrics) | Done |
| 06 | Baseline results (variants A/B/C across timeframes) | Done |
| 07 | Eve agent (FastMCP boundary) | Done |
| 07b | HTTP bridge for chat | Done |
| 08 | Advanced research (grid search, walk-forward) | Done |
| 08b | Statistical validation (deflated Sharpe, Bonferroni/Holm/BH) | Done |

### Future

| Phase | What | Status |
|-------|------|--------|
| 09 | Snowflake warehouse | Planned |
| 10 | Real-time data | Planned |
| 11 | Kafka streaming | Planned |
| 12 | Paper trading | Planned |
| 13 | Risk engine | Planned |
| 14 | Human-approved live trading | Planned |

Phases 09-14 are future work. Eve does not trade real money today.

---

## Getting started

### Prerequisites

- Python 3.11+ with `uv` package manager
- Node.js 18+ with npm
- A Groq API key (free tier works: [console.groq.com/keys](https://console.groq.com/keys))

### Install and run

```bash
# Python environment (uv)
uv sync

# Run tests
uv run pytest

# Import check
uv run python -c "import quant"

# Frontend chat — two terminals needed:

# Terminal 1: the deterministic engine, exposed over HTTP
uv run python -m mcp.quant_server.http_bridge      # http://127.0.0.1:8010

# Terminal 2: the web app
cd apps/web
cp .env.example .env.local     # add your GROQ_API_KEY
npm install
npm run dev                    # http://localhost:3000
```

### Data setup

Process a month of data before running any backtests:

```bash
# Download raw data (requires Upstox/Dhan credentials)
uv run python -c "
from quant.data.download import download_nifty_futures_upstox
download_nifty_futures_upstox(year=2026, month=7)
"

# Validate + process (creates processed candles with indicators)
uv run python -c "
from quant.processing.pipeline import process_month
process_month(year=2026, month=7)
"
```

Or ask Eve to do it: "Download and process July 2026 data."

---

## Environment variables

Copy `.env.example` to `.env` (for the quant engine) and
`apps/web/.env.example` to `apps/web/.env.local` (for the chat UI).

| Variable | Where | Purpose |
|----------|-------|---------|
| `DHAN_CLIENT_ID` | `.env` | DhanHQ broker client ID |
| `DHAN_ACCESS_TOKEN` | `.env` | DhanHQ access token |
| `GROQ_API_KEY` | `.env.local` | Groq API key for the LLM |

Never commit `.env` or `.env.local`.

---

## Research integrity

- `parameter_search` results are calibrated on the training window
  only. Never report its top net P&L as "expected returns" — it is
  in-sample.
- Walk-forward and validate_parameter_search results are the
  out-of-sample evidence. Prefer them.
- Trades are few per month. Hedge language accordingly: "directional,
  not statistically decisive" for fewer than 20 out-of-sample trades.
- Costs and 1-tick slippage are included in every backtest. There is
  no separate "cost adjustment" step.

---

## Who this is for

- Quant researchers who want an AI front-end on a deterministic
  engine, with an audit trail for every number.
- Engineers who want to use LLMs in trading without trusting them
  with the math.
- Anyone studying Indian equity derivatives (NIFTY futures) who wants
  reproducible research.

---

## License

Proprietary. See LICENSE file if present.
