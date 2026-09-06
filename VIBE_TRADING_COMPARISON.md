# Vibe-Trading vs Our EMA Strategy — Feature & Capability Comparison

**Date:** September 2026
**Purpose:** Understand what Vibe-Trading (HKUDS) offers vs what we built

---

## What is Vibe-Trading?

Vibe-Trading is an open-source project by **HKU Data Science Lab (HKUDS)**. It's a full-stack AI-powered quantitative finance platform. Think of it as a "ChatGPT for finance" — you talk to it in plain English, and it actually executes backtests, analyzes options, benchmarks alpha factors, extracts your trading patterns from broker exports, and even connects to real brokers.

It's built on the same core idea as our project (AI orchestrates, Python calculates), but it's **much broader in scope** — covering multiple markets, hundreds of data sources, and dozens of pre-built strategies.

---

## Side-by-Side Comparison

| Feature | Our EMA Strategy | Vibe-Trading |
|---------|------------------|--------------|
| **Focus** | NIFTY Futures only | Global (US, India, China, HK, Korea, Crypto, Forex) |
| **Backtest engines** | 1 (custom) | 9 (India, US, China, Korea, Crypto, Forex, Options, Futures) |
| **Data sources** | 2 (DhanHQ, Upstox) | 25 (Yahoo, AKShare, Binance, CCXT, MT5, Futu, etc.) |
| **Alpha factors** | 0 (custom EMA strategy) | 462 pre-built (Qlib158, Alpha101, GTJA191, academic) |
| **MCP tools** | 12 | 70 |
| **AI agent** | Custom (Eve) | LangChain/ReAct with 20+ LLM providers |
| **Multi-agent swarm** | No | 30 team presets (investment committee, quant desk, etc.) |
| **Broker connectors** | 2 (read-only) | 14 (IBKR, Robinhood, Alpaca, Binance, Dhan, etc.) |
| **Options support** | No | Yes (Black-Scholes, Greeks, multi-leg payoffs) |
| **Web UI** | Next.js 16 chat | React 19 full dashboard (charts, options lab, alpha zoo) |
| **Desktop app** | No | Yes (Electron/Windows) |
| **Finance math library** | No | 265 functions (VaR, CVaR, EVT, bonds, credit) |
| **Memory system** | No | Persistent memory with Ebbinghaus decay |
| **Scheduled research** | No | Cron-based automation |
| **Shadow Account** | No | Extract trading patterns from broker CSV exports |
| **Knowledge skills** | 5 custom | 89 pre-built (technical analysis, quant methods, risk, options) |
| **IM delivery** | No | 16 channels (Telegram, Slack, Discord, WhatsApp, etc.) |
| **Tests** | 14 files | 457 files |
| **Languages** | English | 6 (EN, CN, JP, KR, AR, ES) |

---

## Real Examples: What Vibe-Trading Can Do

### 1. Shadow Account — Extract Your Trading DNA

**What it does:** You upload your broker trade export (CSV), and the system:
1. Parses every trade (symbol, direction, size, entry/exit, P&L)
2. Extracts your personal trading patterns as if-then rules
3. Backtests those rules across different markets and timeframes
4. Shows you where your rules would have worked and where they failed

**Example prompt:**
> "Analyze my trade journal at ~/Downloads/dhan_trades.csv, extract my trading rules, backtest them on NIFTY for the last 6 months, and show me where I left money on the table"

**What you get back:**
- Your top 5 trading patterns (e.g., "I always buy after 3 red days", "I cut winners too early")
- Backtest results of each rule
- A report showing: "Your stop-loss rule would have saved ₹45,000 in March alone"

---

### 2. Multi-Agent Investment Committee

**What it does:** Instead of one AI, you get a team of specialized AI workers that collaborate:
- **Analyst** — gathers data and news
- **Quant** — runs backtests and factor analysis
- **Risk Manager** — checks drawdown, position sizing, correlations
- **Portfolio Manager** — makes the final call

**Example prompt:**
> "Use run_swarm with investment_committee to evaluate whether to go long on RELIANCE this week"

**What you get back:**
- Each agent provides its analysis
- The committee votes (buy/sell/hold)
- A structured report with dissenting opinions

---

### 3. Alpha Factor Zoo — 462 Pre-Built Factors

**What it does:** Browse, benchmark, and compare 462 alpha factors across markets.

**Example prompt:**
> "Run factor_analysis on NIFTY 50 stocks using the momentum factor (20-day return) from Jan to Aug 2026"

**What you get back:**
- Factor returns over time
- Sharpe, IC, turnover of the factor
- Sector breakdown
- Correlation with other factors

**Example CLI:**
```
vibe-trading alpha bench --zoo gtja191 --universe nifty50 --period 2024-2026
```

---

### 4. Options Lab

**What it does:** Full options analysis with Black-Scholes pricing, Greeks, and multi-leg payoff diagrams.

**Example prompt:**
> "Analyze options: NIFTY at 24800, strike 25000 call, 30 days to expiry, volatility 18%, risk-free rate 6%. Show me the payoff diagram for a bull call spread (25000/25500)"

**What you get back:**
- Theoretical price, delta, gamma, theta, vega
- Payoff diagram (visual)
- Break-even points
- P&L at different NIFTY levels

---

### 5. Multi-Market Backtesting

**What it does:** Run the same strategy across different markets with market-specific cost models.

**Example prompt:**
> "Backtest a MACD crossover strategy on: (1) NIFTY Futures, (2) S&P 500 ETF, (3) Bitcoin perpetual — all for 2025, and compare the Sharpe ratios"

**What you get back:**
| Market | Sharpe | Net P&L | Max DD | Trades |
|--------|--------|---------|--------|--------|
| NIFTY Futures | 1.2 | +₹1.8L | -4.2% | 34 |
| S&P 500 | 0.9 | +$12,400 | -6.1% | 28 |
| BTC Perp | 0.6 | +$8,200 | -18.3% | 45 |

---

### 6. Broker Integration — Real Account Access

**What it does:** Connect to 14 brokers and query real positions, orders, and balances.

**Example prompts:**
> "Show me my current positions in Dhan"
> "What's my account balance in IBKR?"
> "Place a limit order to buy 50 shares of TCS at ₹3,800" (with mandate approval)

**Safety:** Live orders require a **mandate** — you pre-define symbol universe, order size, exposure limits, and daily caps. The system refuses orders outside the mandate.

---

### 7. Scheduled Research

**What it does:** Set up cron jobs that run research automatically.

**Example prompt:**
> "Schedule a daily scan of NIFTY momentum factors at 9:15 AM IST, and send the top 3 to my Telegram"

**What you get:**
- Automated daily execution
- Results delivered to your chosen channel (Telegram, Slack, email, etc.)

---

### 8. Document Analysis

**What it does:** Read PDFs, SEC filings, annual reports, and extract key information.

**Example prompt:**
> "Read this annual report at ~/Downloads/RELIANCE_AR2026.pdf and summarize the risk factors and management guidance"

---

### 9. Cross-Asset Correlation

**What it does:** Build correlation matrices across assets and identify regime changes.

**Example prompt:**
> "Show me the 60-day rolling correlation between NIFTY, Gold, and USD/INR for 2026, and highlight any regime shifts"

---

### 10. Generate Strategy from Scratch

**What it does:** Describe a strategy in English, and the agent writes the code, validates it, and backtests it.

**Example prompt:**
> "Create a strategy that buys when RSI drops below 30 and the 20-day moving average is rising, and sells when RSI goes above 70. Backtest it on ACC.NS for 2025."

**What happens:**
1. Agent writes `signal_engine.py`
2. AST-level validation (no circular imports, correct interface)
3. Backtest runs with full cost model
4. Results returned with metrics

---

### 11. Finance Math Library (quantlib)

**What it does:** 265 tested functions across 19 modules — the building blocks for any quant work.

| Module | Functions | Examples |
|--------|-----------|----------|
| Options | 30+ | Black-Scholes, Greeks, binomial tree, implied vol |
| Bonds | 20+ | Duration, convexity, yield curve, BOOTSTRAP |
| Credit | 15+ | CDS pricing, recovery rates, default probability |
| VaR/CVaR/EVT | 25+ | Historical VaR, parametric CVaR, GPD tails |
| Econometrics | 30+ | GARCH, cointegration, VAR, Granger causality |
| Event Studies | 15+ | CAR, BHAR, abnormal volume |
| Attribution | 10+ | Brinson, factor attribution |

---

### 12. Web Dashboard

Full React 19 UI with:
- **Chat page** — primary interaction with AI agent
- **Runtime page** — live status and model config
- **Reports page** — search and compare past research runs
- **Compare page** — head-to-head strategy comparison
- **Alpha Zoo** — browse and benchmark 462 factors
- **Options Lab** — interactive payoff diagrams
- **Correlation page** — cross-asset correlation matrix
- **Scheduled page** — manage cron jobs
- **Settings** — LLM providers, API keys, channels

---

## What Our Project Does Better (or Differently)

| Aspect | Our Advantage |
|--------|---------------|
| **Depth on NIFTY** | We know Indian futures deeply — realistic cost model with every statutory charge (STT, SEBI, stamp duty, GST) |
| **Statistical rigor** | Deflated Sharpe, PBO (CSCV), Benjamini-Hochberg FDR, bootstrap CI — Vibe-Trading doesn't have this |
| **Walk-forward validation** | We have anchored walk-forward with embargo; Vibe-Trading doesn't emphasize this |
| **Grounding checker** | We verify every numeric claim the AI makes; Vibe-Trading has a simpler approach |
| **Reproducibility** | SHA-256-hashed run cards, experiment vault — our audit trail is tighter |
| **Determinism** | Same inputs always produce same outputs — no floating-point surprises |
| **Simplicity** | 14 test files, focused scope vs 457 tests, massive codebase — easier to understand and maintain |

---

## What Vibe-Trading Does Better

| Aspect | Their Advantage |
|--------|-----------------|
| **Breadth** | 9 markets, 25 data sources, 462 factors — we're NIFTY-only |
| **Broker integration** | 14 live brokers with safety gates; we have 2 read-only |
| **Multi-agent** | 30 swarm teams for collaborative research; we have a single agent |
| **Options** | Full options pricing and Greeks; we don't touch options |
| **Web UI** | Full dashboard with charts, options lab, alpha zoo; we have a basic chat |
| **Desktop app** | Electron packaging for Windows |
| **Scheduled research** | Cron-based automation; we don't have this |
| **Shadow Account** | Extract your trading DNA; we don't have this |
| **Finance math** | 265 tested functions; we have a minimal stats module |
| **IM delivery** | 16 channels; we have none |
| **Community** | Open-source, 457 tests, CI/CD pipeline |

---

## Bottom Line

**Our project** is a **deep, focused research engine** for NIFTY Futures with strong statistical validation. It's great at answering: *"Does this specific EMA strategy work on NIFTY, and can we prove it statistically?"*

**Vibe-Trading** is a **broad, general-purpose AI quant platform** that covers every market, every asset class, every strategy type. It's great at answering: *"Help me research anything in finance, from any market, using any approach."*

They share the same core philosophy (AI orchestrates, Python calculates) but differ in scope vs depth.

---

*Generated from analysis of both codebases — `D:\Trading\EMA_Strategy` and `D:\Trading\Vibe-Trading`*
