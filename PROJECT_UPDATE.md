# AI Quant Trading Platform — Project Update

**Project:** AI-Powered Quantitative Trading Platform (NIFTY Futures)
**Stack:** Python 3.11 · Polars · DuckDB · FastMCP · Next.js 16 · TypeScript · Tailwind CSS
**Status:** Research engine fully operational (Phases 00–08b complete)
**Data:** July & August 2026 NIFTY Futures (1m/5m/15m candles)

---

## Summary

We built a system that downloads real NIFTY Futures stock market data from broker APIs (DhanHQ, Upstox), cleans and validates it, applies a trading strategy (EMA crossover with an angle filter), and then simulates trading on historical data to see if the strategy actually makes money. The system accounts for real-world costs like brokerage fees, taxes, and slippage — so the results reflect what you'd actually see in a real trading account. On top of this, we built an AI agent (named "Eve") that a user can talk to in plain English. You can ask it questions like *"Run a backtest on July 2026"* or *"Which timeframe works best?"* and it will execute the right tools, get real numbers, and explain the results — without ever making up a number.

---

## Practical Example: What Can the System Do Right Now?

Here's a real scenario. We asked the system to test the **EMA 9/15 crossover strategy with a 30° angle filter** on NIFTY Futures data from **July 2026**, using **15-minute candles**.

**What happened:**
1. The system loaded 575 processed 15-minute candles for July 2026
2. It applied the strategy rules: *buy when the 9 EMA crosses above the 15 EMA at an angle ≥ 30°, sell when it crosses below at ≤ -30°*
3. It found **4 trades** during the month
4. It simulated each trade with entry/exit prices, slippage, and all Indian market costs

**Results:**

| Metric | Value |
|--------|-------|
| Starting capital | ₹10,00,000 |
| Ending capital | ₹10,06,076 |
| Net profit (after all costs) | **+₹5,737** |
| Win rate | 1 out of 4 trades (25%) |
| Profit factor | 1.35 |
| Sharpe ratio | 0.95 |
| Max drawdown | 2.63% |

**What each trade looked like:**

| # | Direction | Entry Date | Exit Date | Entry Price | Exit Price | Net P&L |
|---|-----------|------------|-----------|-------------|------------|---------|
| 1 | LONG | Jul 10 | Jul 13 | ₹24,290 | ₹24,135 | -₹8,090 |
| 2 | SHORT | Jul 14 | Jul 15 | ₹24,189 | ₹24,280 | -₹4,891 |
| 3 | SHORT | Jul 15 | Jul 17 | ₹24,140 | ₹24,297 | -₹8,191 |
| 4 | LONG | Jul 24 | Jul 31 | ₹23,885 | ₹24,430 | **+₹26,909** |

**Interpretation:** The strategy lost on 3 small trades but one big winning trade (₹26,909) covered all losses and ended net positive. All brokerage, STT, exchange charges, GST, and slippage were already deducted from these numbers.

**The system can also:**
- Test the same strategy across **1-minute, 5-minute, and 15-minute** candles side-by-side
- Search through **320 different parameter combinations** to find which EMA periods and angle thresholds work best
- Run **walk-forward validation** to check if the strategy works on data it hasn't seen before
- Calculate **statistical significance** to tell you if the results are real or just luck
- Let you **chat with an AI agent** that explains all of this in plain English

---

## Completed Phases

### Phase 00 — Foundation
- Project scaffolding, `pyproject.toml`, config via Pydantic + `.env`
- Package management with `uv`

### Phase 01 — Data Acquisition
- REST clients for **DhanHQ** and **Upstox** brokers
- Instrument discovery, contract selection, 1-minute candle download
- Automatic expiry rollover handling

### Phase 02 — Data Validation
- 7-check validation suite: timestamp integrity, duplicate detection, OHLC consistency, volume checks, open interest continuity, gap detection
- Raw data stored as Parquet

### Phase 03 — Candle Processing
- Resampling: 1m → 5m and 15m candles
- Verification reports cross-checking derived candles against source data

### Phase 04 — Strategy Engine
- EMA 9 / EMA 15 crossover detection
- Angle filter: ±30° threshold on EMA slope
- Three signal modes: `crossover`, `crossover_and_angle`, `crossover_angle_and_trend`
- Signal output: BUY / SELL / HOLD per candle

### Phase 05 — Backtesting Engine
- Position state machine: FLAT → LONG / SHORT → FLAT
- Execution model: signals at candle close, fills at next-candle open
- **Indian futures cost model**: brokerage (₹20 flat), STT (0.0125% sell-side), exchange charges (0.00345%), SEBI fee (0.0001%), stamp duty (0.003% buy-side), GST (18%)
- Slippage: 1 tick (0.05 INR) normal mode
- Metrics: Sharpe, Sortino, Calmar, max drawdown, profit factor, win rate, net P&L, expectancy

### Phase 06 — Baseline Experiments
- 9 experiments: 3 strategy variants (A/B/C) × 3 timeframes (1m/5m/15m)
- Reproducibility metadata, comparison tables

### Phase 07 — AI Agent + MCP Server
- **12 deterministic tools** on FastMCP server
- HTTP bridge (Starlette + uvicorn) for Next.js frontend
- Agent "Eve" with natural-language research interface
- **Grounding checker**: verifies every numeric claim the AI makes against actual tool results

### Phase 08 — Advanced Research
- **Parameter grid search**: 320 combinations (fast EMA × slow EMA × angle threshold × lookback)
- **Walk-forward validation**: anchored 3-step with 1-day embargo between train/test
- **Regime analysis**: classifies days by realized volatility (high/mid/low)

### Phase 08b — Statistical Validation
- Deflated Sharpe ratio (accounts for multiple testing)
- Bootstrap Sharpe confidence intervals
- Monte Carlo permutation tests
- Probability of Backtest Overfitting (PBO via CSCV)
- Benjamini-Hochberg FDR correction
- SHA-256-hashed run cards for audit trail

---

## Data Pipeline

```
Broker API (DhanHQ / Upstox)
    ↓
Raw 1m Candles (.parquet)
    ↓
Validation (7 checks)
    ↓
Resample → 5m / 15m
    ↓
Add Indicators (EMA9, EMA15, angle)
    ↓
Processed Candles → Backtesting → Results Vault (SQLite)
```

Current dataset: **August 2026**, all three timeframes processed, 9 baseline experiments logged.

---

## Key Files

| File | Purpose |
|------|---------|
| `quant/strategies/ema_9_15.py` | Strategy logic (crossover + angle) |
| `quant/backtest/engine.py` | Position state machine + execution |
| `quant/backtest/costs.py` | Indian futures cost model |
| `quant/backtest/metrics.py` | Sharpe, Sortino, drawdown, etc. |
| `quant/research/parameter_search.py` | Grid search (320 combos) |
| `quant/research/walk_forward.py` | Out-of-sample validation |
| `quant/research/significance.py` | Bootstrap CI + permutation test |
| `quant/research/multiple_testing.py` | Deflated Sharpe + PBO + BH FDR |
| `mcp/quant_server/server.py` | MCP tool server (12 tools) |
| `mcp/quant_server/grounding.py` | Numeric claim verification |
| `apps/web/` | Next.js 16 frontend with chat UI |
| `agent/instructions.md` | Agent behavior rules |

---

## Testing

14 test files covering all phases:
- `test_phase00_smoke.py` through `test_phase08b_validation.py`
- Unit + integration tests for data, signals, backtester, MCP, HTTP bridge

---

## What's Left (Future Phases)

| Phase | Description |
|-------|-------------|
| 09 | Snowflake data warehouse integration |
| 10 | Real-time WebSocket data feed |
| 11 | Kafka event streaming |
| 12 | Paper trading mode |
| 13 | Risk management engine |
| 14 | Live trading with human-in-the-loop approval |

---

## Architecture Decisions

1. **Determinism over speed** — every function is pure; same inputs = same outputs
2. **No look-ahead bias** — signals use `t-1` candles; fills at next open
3. **Costs included by default** — no "surprise" deductions in P&L
4. **AI never computes** — Eve calls tools, explains results; grounding checker validates claims
5. **Reproducibility** — run cards, SHA-256 hashes, experiment vault

---

*Built with Python, Polars, DuckDB, FastMCP, Next.js 16, and TypeScript.*

---

## Quick Reference — What a Non-Technical Person Needs to Know

**The problem:** Traders use technical indicators (like EMA crossovers) to decide when to buy or sell stocks. But does a specific combination actually work, or does it just look good in hindsight?

**What we built:** A computer system that:
1. **Downloads** real historical stock data (NIFTY Futures) from broker APIs
2. **Cleans** the data (removes errors, fills gaps)
3. **Tests a trading strategy** on that data and simulates real trades with real costs
4. **Checks if the results are statistically significant** or just random luck
5. **Lets you talk to it** in plain English to run these tests

**Current state:** The system works end-to-end. We have 2 months of data (July & August 2026), 9 completed experiments, and the research engine can run 320 strategy variations automatically. A chatbot interface lets users ask questions in natural language and get real backtest results with explanations.

**What's next:** Real-time data feeds, paper trading mode, and eventually live trading with human approval.
