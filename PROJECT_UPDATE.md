# AI Quant Trading Platform — Project Update

**Project:** AI-Powered Quantitative Trading Platform
**Stack:** Python 3.11 · Polars · DuckDB · FastMCP · Next.js 16 · React 19 · TypeScript · Tailwind CSS v4 · Supabase · Groq LLM
**Status:** Research engine, trading journal, and AI agent fully operational
**Data:** July & August 2026 NIFTY Futures (1m/5m/15m candles)

---

## What We Built

> A complete platform that helps you figure out if a trading idea actually
> works — and then helps you track, analyze, and improve every trade you take.

Most traders lose money — not because they're bad, but because they never
tested their ideas properly. They see a pattern on a chart, "feel" like the
market is going up, and trade based on that. Meanwhile, hedge funds run
thousands of simulations before they place a single trade.

**We're building that — for everyone.**

The platform has two sides that work together:

1. **The Research Engine** — test any strategy on real historical data with
   real costs before you risk a single rupee
2. **The Trading Journal** — log every trade, track your psychology, get
   AI-powered coaching on your behavioral patterns, and see exactly where
   you're leaving money on the table

You can talk to the system in plain English. Type *"Run a backtest on July
2026"* or *"Show me my worst trading days this month"* and get real answers
with real numbers — not guesses.

---

## The Two Sides of the Platform

### Side 1: The Research Engine (Backtesting)

Test strategies on real NIFTY Futures data before going live.

**A real example:** We tested the **EMA 9/15 crossover strategy with a 30°
angle filter** on July 2026 data using 15-minute candles.

| Metric | Value |
|--------|-------|
| Starting capital | ₹10,00,000 |
| Ending capital | ₹10,06,076 |
| Net profit (after all costs) | **+₹5,737** |
| Win rate | 1 out of 4 trades (25%) |
| Profit factor | 1.35 |
| Sharpe ratio | 0.95 |
| Max drawdown | 2.63% |

| # | Direction | Entry Date | Exit Date | Entry Price | Exit Price | Net P&L |
|---|-----------|------------|-----------|-------------|------------|---------|
| 1 | LONG | Jul 10 | Jul 13 | ₹24,290 | ₹24,135 | -₹8,090 |
| 2 | SHORT | Jul 14 | Jul 15 | ₹24,189 | ₹24,280 | -₹4,891 |
| 3 | SHORT | Jul 15 | Jul 17 | ₹24,140 | ₹24,297 | -₹8,191 |
| 4 | LONG | Jul 24 | Jul 31 | ₹23,885 | ₹24,430 | **+₹26,909** |

The strategy lost on 3 small trades but one big winning trade covered all
losses. All brokerage, STT, exchange charges, GST, and slippage were already
deducted.

### Side 2: The Trading Journal

Log every trade you take. Track not just the numbers — but *why* you took
the trade, how you *felt*, and what *mistakes* you made.

- **Manual trade logging** — symbol, prices, direction, quantity, strategy,
  outcome, emotional state, confidence level, satisfaction rating, mistakes,
  rich text notes via Tiptap editor
- **Broker auto-sync** — connect your Dhan broker account and automatically
  import trades with FIFO-based BUY+SELL pairing
- **Psychology tracking** — emotional state (Calm, Overconfident, Impatient,
  Frustrated, Anxious), confidence slider (1-10), satisfaction slider (1-10)
- **Revenge trade detection** — automated algorithm identifying rapid re-entry
  within 30 minutes of a loss, with severity levels
- **AI Trading Coach** — Groq LLM analyzes your full trade history and
  generates personalized behavioral insights:
  - Skill radar (risk, psychology, consistency, edge, discipline)
  - Confidence calibration — are you overconfident on losing trades?
  - Overtrading detection and tilt meter
  - What-if scenario analysis
  - Actionable playbook with priority items
- **Analytics & Reports** — 4-tab deep dive:
  - *Performance*: equity curve, daily/monthly P&L, win/loss breakdown, strategy comparison
  - *Psychology*: emotion trends, confidence vs P&L scatter, mistake cost analysis
  - *Risk*: drawdown from peak, position sizing, risk/reward analysis
  - *Journal*: chronological trade log with notes and emotions

---

## The MCP Server — The Brain Behind the AI

We built a **Model Context Protocol (MCP) server** — a bridge between the
AI agent and the quant engine. This is what makes the AI able to "call"
real tools instead of guessing numbers.

**12 deterministic tools** exposed over MCP:

| Tool | What It Does |
|------|-------------|
| `list_research_months` | Shows which months have processed data |
| `get_historical_candles` | Preview candles for a month/timeframe |
| `download_month_data` | Fetch raw data from broker APIs |
| `validate_dataset` | Run 7-check quality audit on raw data |
| `process_month_data` | Resample + add EMA/angle indicators |
| `generate_signal` | Get BUY/SELL/HOLD counts for a strategy |
| `run_backtest_signals` | Full backtest with all costs and metrics |
| `compare_timeframes` | Test variants A/B/C across 1m/5m/15m |
| `parameter_search` | Grid-search 320 parameter combinations |
| `walk_forward_test` | Out-of-sample validation with embargo |
| `backtest_significance` | Bootstrap CI + permutation tests |
| `validate_parameter_search` | Check if the winner survives multiple testing |

**The grounding checker** verifies every numeric claim the AI makes against
actual tool results. Eve literally cannot lie about numbers — if it tries,
the checker catches it.

---

## Real People, Real Use Cases

### Rahul (21, Engineering Student, ₹50K savings)
His friend told him to "buy NIFTY when the 9 EMA crosses above the 15
EMA." He runs the backtest and learns it only made 4 trades in a month —
not enough to be sure. He saves his ₹50,000.

### Priya (IT Professional, busy schedule)
She has a strategy idea but no time to learn Python. She types it into the
app. The AI runs the test over lunch. What used to take a week of coding
takes 10 minutes of conversation.

### Vikram (Lost ₹2 Lakhs trading options)
He thinks the market is "rigged." The AI shows him his old strategy had a
17% win rate — essentially flipping a coin where the losing side costs more.
He realizes it wasn't rigged, it was untested. He starts logging his trades
and the AI coach points out he revenge-trades after losses.

### Anita (Working professional, wants to track her trading)
She trades part-time and never knows if she's actually improving. She
connects her Dhan broker, syncs 3 months of trades, and the AI coach shows
her: *"Your win rate is 45% but your average loss is 2x your average win.
You're making money on frequency but losing on structure."* She adjusts
her position sizing and her P&L improves by 30% the next month.

---

## What We've Built

### Foundation & Data Pipeline
- Project scaffolding with `pyproject.toml`, Pydantic config, `uv` package manager
- REST clients for **DhanHQ** and **Upstox** brokers
- Automatic instrument discovery, contract selection, expiry rollover
- 1-minute candle download → Parquet storage
- **7-check validation suite**: timestamps, duplicates, OHLC consistency, volume, open interest, gaps
- Resampling: 1m → 5m / 15m with verification reports

### Strategy & Backtesting Engine
- EMA 9/15 crossover detection with angle filter (±30° threshold)
- Three signal modes: `crossover`, `crossover_and_angle`, `crossover_angle_and_trend`
- Position state machine: FLAT → LONG / SHORT → FLAT
- Execution model: signals at candle close, fills at next-candle open
- **Indian futures cost model**: brokerage (₹20 flat), STT (0.0125%), exchange charges (0.00345%), SEBI fee, stamp duty, GST (18%)
- Slippage: 1 tick (0.05 INR) normal mode
- 9 baseline experiments: 3 variants (A/B/C) × 3 timeframes (1m/5m/15m)
- Metrics: Sharpe, Sortino, Calmar, max drawdown, profit factor, win rate, expectancy

### Advanced Research
- **Parameter grid search**: 320 combinations (fast EMA × slow EMA × angle threshold × lookback)
- **Walk-forward validation**: anchored 3-step with 1-day embargo between train/test
- **Regime analysis**: classifies days by realized volatility (high/mid/low)
- **Statistical validation**: Deflated Sharpe ratio, bootstrap confidence intervals, Monte Carlo permutation tests, PBO via CSCV, Benjamini-Hochberg FDR correction
- SHA-256-hashed run cards for audit trail

### AI Agent & MCP Server
- **12 deterministic tools** on FastMCP server
- HTTP bridge (Starlette + uvicorn) for Next.js frontend
- Agent "Eve" with natural-language research interface
- **Grounding checker**: verifies every numeric claim against tool results
- Next.js 16 frontend with chat UI

### Trading Journal & Analytics
- **Trade logging** — manual entry with rich metadata (emotions, confidence, mistakes, notes via Tiptap editor)
- **Broker auto-sync** — Dhan integration with AES-256-GCM encrypted token storage, FIFO trade pairing
- **Psychology tracking** — emotional state, confidence/satisfaction sliders, multi-select mistake tags
- **Revenge trade detection** — identifies rapid re-entry within 30 minutes of a loss
- **AI Trading Coach** — Groq LLM (Llama 3.3 70B) generating behavioral analysis, skill radar, actionable playbook
- **4-tab analytics** — Performance, Psychology, Risk, Journal with date range and per-chart filters
- **Calendar view** — P&L heatmap, weekly/monthly stats, streak detection
- **Trading tools** — Position size calculator, risk/reward calculator, stop loss calculator, profit target calculator
- **Strategy backtester** — compare multiple strategies side-by-side with charts and tables

### Authentication & Security
- **Supabase Auth** — email/password signup with middleware-based route protection
- **Multi-tenant RLS** — Row-Level Security policies ensure complete data isolation per user
- **Encrypted broker tokens** — AES-256-GCM encryption for all stored API credentials
- **Profile management** — username, name, email, password change

---

## Data Pipeline

```
Broker API (DhanHQ / Upstox)
    ↓
Raw 1m Candles (.parquet)          ←── Trade Sync (Dhan) ──→  Supabase DB
    ↓                                                             ↓
Validation (7 checks)                                    Trade Journal
    ↓                                                             ↓
Resample → 5m / 15m                                    AI Coach (Groq)
    ↓                                                             ↓
Add Indicators (EMA9, EMA15, angle)                    Analytics & Reports
    ↓
Processed Candles → Backtesting → Results Vault
    ↓
MCP Server (12 tools) → AI Agent "Eve" → Chat UI
```

---

## Key Files

### Quant Engine (`quant/`)
| File | Purpose |
|------|---------|
| `strategies/ema_9_15.py` | Strategy logic (crossover + angle) |
| `backtest/engine.py` | Position state machine + execution |
| `backtest/costs.py` | Indian futures cost model |
| `backtest/metrics.py` | Sharpe, Sortino, drawdown, etc. |
| `research/parameter_search.py` | Grid search (320 combos) |
| `research/walk_forward.py` | Out-of-sample validation |
| `research/significance.py` | Bootstrap CI + permutation test |
| `research/multiple_testing.py` | Deflated Sharpe + PBO + BH FDR |

### MCP & Agent (`mcp/`, `agent/`)
| File | Purpose |
|------|---------|
| `mcp/quant_server/server.py` | MCP tool server (12 tools) |
| `mcp/quant_server/grounding.py` | Numeric claim verification |
| `agent/instructions.md` | Agent behavior rules |

### Web App (`apps/web/`)
| File | Purpose |
|------|---------|
| `app/dashboard/` | Main dashboard, trades, reports, AI insights |
| `app/api/` | Server-side API routes (trades, AI, broker, strategies) |
| `lib/ai/insights/` | AI coaching engine (Groq + metrics) |
| `lib/brokers/dhan.ts` | Dhan broker API integration |
| `lib/encryption.ts` | AES-256-GCM token encryption |
| `components/` | 36+ reusable UI components |

---

## Testing

14+ test files covering all modules:
- Unit + integration tests for data pipeline, signals, backtester, MCP, HTTP bridge
- Trade CRUD, broker sync, AI insights, auth flows

---

## What's Done vs What's Left

| Part | Status |
|------|--------|
| Data download from broker APIs (DhanHQ, Upstox) | ✅ Done |
| Data quality validation (7-check suite) | ✅ Done |
| Candle resampling (1m → 5m / 15m) | ✅ Done |
| Strategy engine (EMA 9/15 + angle filter) | ✅ Done |
| Backtesting engine with Indian market costs | ✅ Done |
| Baseline experiments (3 variants × 3 timeframes) | ✅ Done |
| MCP server with 12 deterministic tools | ✅ Done |
| AI agent "Eve" with grounding checker | ✅ Done |
| Parameter grid search (320 combos) | ✅ Done |
| Walk-forward validation | ✅ Done |
| Statistical significance tests | ✅ Done |
| Trading journal with manual trade logging | ✅ Done |
| Dhan broker auto-sync with encrypted tokens | ✅ Done |
| Psychology tracking (emotions, confidence, mistakes) | ✅ Done |
| Revenge trade detection | ✅ Done |
| AI Trading Coach (Groq LLM) | ✅ Done |
| Analytics & Reports (4 tabs) | ✅ Done |
| Calendar view with P&L heatmap | ✅ Done |
| Trading calculators (position size, R:R, etc.) | ✅ Done |
| Strategy comparison backtester | ✅ Done |
| Authentication & multi-user (Supabase) | ✅ Done |
| Next.js 16 frontend with dark theme | ✅ Done |
| Support for other strategies (RSI, MACD, etc.) | ❌ Not yet |
| Paper trading mode (fake money practice) | ❌ Not yet |
| Real-time WebSocket data feed | ❌ Not yet |
| Kafka event streaming | ❌ Not yet |
| Risk management engine | ❌ Not yet |
| Live trading with human-in-the-loop approval | ❌ Not yet |
| Additional broker integrations (Zerodha, AngelOne, Upstox) | ❌ Not yet |

**In simple terms:** The research engine, trading journal, AI coaching, and
all analytics are fully built and working needs refinement. The data pipeline is solid. What's
left is going from "backtesting on historical data" to "trading with real
money" — which requires paper trading, risk management, and live execution.

---

## The Big Picture

> Think of it like **Google Maps for trading** — except instead of showing
> you the fastest route, it shows you whether your trading idea will make
> money or lose money, using real historical data.
>
> And once you start trading, it becomes your **flight recorder** — tracking
> every move, analyzing your patterns, and coaching you to improve.
>
> You don't need to know how GPS works to use Google Maps.
> You don't need to know how backtesting works to use our platform.
>
> You just tell it where you want to go, and it shows you the way.


*Built with Python, FastMCP, Next.js 16, React 19, Supabase, Groq, and TypeScript.*
