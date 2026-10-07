# Eve — Market Research: Natural-Language Strategy → Code → Real-Data Backtest

**Date:** 7 October 2026
**Question:** Who else lets a trader describe a strategy in plain language,
turns it into a testable strategy, and tests it on real market data? Which
open-source projects can we use? Where can Eve be better, and what would make
it unique?

**Method.** Three parallel research passes (global commercial products, the
Indian market and SEBI regulation, open-source projects and academic papers),
plus a review of this repository. Most vendor sites and sebi.gov.in /
nseindia.com / arxiv.org could not be fetched directly from the research
environment, so many facts come from search-result summaries of vendor docs,
press releases and review sites. Anything marked **[unverified]** rests on a
single secondary source. Check primary sources before making legal, pricing
or partnership decisions.

---

## Contents

1. [Executive summary](#1-executive-summary)
2. [What Eve covers today](#2-what-eve-covers-today)
3. [Indian competitors](#3-indian-competitors)
4. [Global competitors](#4-global-competitors)
5. [Open-source projects](#5-open-source-projects)
6. [What the research literature says](#6-what-the-research-literature-says)
7. [Feature comparison matrix](#7-feature-comparison-matrix)
8. [Regulation (SEBI / NSE) and what it means for Eve](#8-regulation-sebi--nse-and-what-it-means-for-eve)
9. [Market size](#9-market-size)
10. [Gaps in the market](#10-gaps-in-the-market)
11. [What we should adopt from others](#11-what-we-should-adopt-from-others)
12. [USPs — how Eve becomes unique](#12-usps--how-eve-becomes-unique)
13. [Positioning and pricing](#13-positioning-and-pricing)
14. [Risks and threats](#14-risks-and-threats)
15. [Recommended roadmap](#15-recommended-roadmap)
16. [Open questions to verify](#16-open-questions-to-verify)
17. [Sources](#17-sources)

---

## 1. Executive summary

- **The core idea is no longer rare.** "Type your strategy in English →
  backtest → deploy" exists in at least **10 Indian products** and many
  global ones. In India the most direct rivals are **FYERS Automate + FIA**
  (broker-native, launched 28 Aug 2026), **AlgoTest Signals AI**, **uTrade AI
  Strategy Builder** (English *and Hindi*), **AlgoBulls Phoenix Copilot** and
  **INDfolio AI**. Globally: **Composer** (acquired by SoFi, June 2026),
  **QuantConnect Mia**, **NinjaTrader AI Strategy Builder** (Sept 2026),
  **TrendSpider**, **LuxAlgo**, Pine Script generators, and startups such as
  **Horizon Trade** and **Conviction (YC S25)**. The strongest open-source
  rival is **HKUDS Vibe-Trading** (~35k★, MIT), which even has an India
  equity engine and a Dhan connector.
- **NL → strategy alone is not a moat.** Dhan, Upstox, Fyers, Zerodha,
  Alpaca, IBKR, Robinhood and Coinbase all now publish MCP servers, so any
  general AI assistant can drive a broker account. The translation step is
  becoming a commodity.
- **What almost nobody does is tell the truth about the result.** No
  consumer product we found, in India or abroad, ships deflated Sharpe, PBO,
  a trial-counted verdict, or a holdout that can only be used once. Several
  products make overfitting *worse* (LuxAlgo lets you search 6M precomputed
  strategies by net profit; TrendSpider's AI "suggests improvements";
  Composer ranks its community library by backtest return; NexusTrade runs
  genetic optimisation). Most Indian platforms use a slippage number the user
  types in.
- **Most competitors generate free code; Eve fills a typed spec.** Generated
  code fails often (QuantConnect says Mia works in ~75% of cases; Pineify
  claims ~85% first pass) and fails silently: code that compiles but does not
  do what the user said, or that peeks into the future. Vibe-Trading's own
  changelog keeps fixing look-ahead and fill bugs in generated strategies.
  Eve's closed-vocabulary spec, where look-ahead cannot be expressed,
  is the safer design, and 2026 research backs it (§6).
- **India-specific timing favours Eve's positioning:**
  - SEBI's FY26 study: 87.7% of 78.6 lakh F&O traders lost money.
    **Transaction costs alone turned ~4.4 lakh traders from gross profit to
    net loss.**
  - STT on futures rose from 0.02% to 0.05% on 1 April 2026.
  - SEBI fined ~10 brokers ₹16 lakh in total (March 2026) for linking to
    Tradetron, whose strategies implied assured returns.

  A tool whose job is to say "this does not survive costs and statistics" is
  both a selling point and a compliance advantage.
- **Recommended positioning:** *"Eve is the honest strategy checker for
  Indian F&O. Describe your idea; Eve shows you exactly what it will run,
  tests it with every rupee of real charges, and tells you plainly whether
  it's an edge or luck — before you risk money."*

---

## 2. What Eve covers today

From this repository (README, `docs/phases/`, `plans/PROGRESS.md`,
`FINAL_RESULTS.md`, Phase 15):

| Area | What exists |
|---|---|
| **NL → strategy** | Phase 15: the LLM fills an `eve.strategy/1` typed spec (closed indicator vocabulary with bounded params; `quant/strategies/spec/`). **The model never writes code.** Offsets are bars back and must be ≥ 0, so look-ahead cannot be expressed. Chat and a form build the same spec (Hisaab strategy builder). |
| **What you read is what runs** | The human-readable summary is rendered from the spec by code (`describe.py`), not written by the model; pinned on the Hisaab side by `npm run verify:spec`. Spec diffing and hashing exist. |
| **Data** | Dhan and Upstox; NIFTY futures 1m/5m/15m; NIFTY, BANKNIFTY and SENSEX index spot 1m backfilled 2022-01 → 2026-09 (171 months, ~1.3M rows); validation suite (gaps, duplicates, sessions, holidays); Parquet + DuckDB + Polars. |
| **Backtest realism** | Next-bar-open fills, tick slippage, **full Indian cost model with a dated STT schedule (0.05% from 1 Apr 2026 already in)**, stamp duty, exchange, SEBI, GST; live instrument-master lot/tick sizes (NIFTY 65); bracket exits (SL, TP, trailing, time stop, EOD square-off). |
| **Statistical validation** | Walk-forward (anchored, embargo), bootstrap Sharpe CI, Monte Carlo permutation test, deflated Sharpe, PBO (CSCV), Benjamini–Hochberg FDR, pre-registered discovery/confirm splits with seal/unseal. |
| **Honest verdict** | Labels: `too_few_trades`, `failed_holdout`, `not_significant`, `lags_buy_and_hold`, `survived_holdout`. Never says "proven". **Every new version and every recorded backtest raises the trial count**, which deflates the Sharpe. A holdout month that was already backtested is refused. |
| **Agent / tooling** | Eve agent over MCP (FastMCP), 12+ research tools plus spec/store/paper tools; one gate for every tool call (policy tiers, auth, validation, rate limits, audit); grounding checker that verifies numeric claims; SHA-256 run cards. |
| **Product surface** | Next.js chat UI; integrated with **Hisaab** (Supabase), which adds a trading journal and behavioural coaching. Per-user saved strategies with immutable versions. |
| **Paper trading** | Paper trading with a kill switch. Eve can engage the kill switch; releasing it, promoting to paper, and archiving are UI-only. **No live trading** (no tool in the `trade_live` tier). |
| **Engineering** | ~390 tests; pre-registration documents; published negative results (`FINAL_RESULTS.md`: no tested family cleared the bar). |

**Honest weaknesses today:** a single instrument family (index futures, no
options yet); a small indicator vocabulary compared with rivals (EMA, SMA,
RSI, MACD, ATR, Bollinger, Heikin-Ashi, patterns, structure); English only;
one agent rather than multi-agent; no live execution; no mobile app; no
community, and no brand yet.

---

## 3. Indian competitors

### 3.1 Direct rivals: plain-language → strategy → backtest

| Product | How NL is handled | Backtest realism | Overfitting protection | Deploy | Price (INR) | Notes |
|---|---|---|---|---|---|---|
| **FYERS Automate + FIA** | FIA builds an automation on a visual canvas from plain English, edits it in conversation, and explains errors. Flow: Describe → Backtest → Deploy. Launched **28 Aug 2026**. Also Fyers MCP and "AI Skills" for Claude Code/Cursor. | Backtest added 2026; cost/slippage details not found | None found | Native (broker-hosted, framework-compliant) | Not found | Closest model to Eve, but locked to Fyers customers. |
| **AlgoTest** (YC S22) | "Signals AI": describe an indicator strategy in English → visual builder → backtest → paper → deploy | ~7.5 years of options data; brokerage/charges optional; **slippage typed in by the user** | No walk-forward, DSR or PBO found | 60+ brokers; Upstox and Groww partner with it | ~₹1/backtest; unlimited ₹599/week or ₹1,499/28 days; Signals ₹1,299/28 days | $500K pre-seed (2022). ~13k active traders (2024) **[unverified]**. Strong in options. |
| **uTrade Algos** (AI Strategy Builder) | Prompt in **English or Hindi** (goals, risk appetite, rules) → ready-to-deploy strategy with risk controls | Not found | Not found | Multi-broker; iOS app | From ~₹999/month; AI builder in every plan incl. free trial | Already has Hindi — a planned Eve feature. |
| **AlgoBulls** (Phoenix Copilot) | English ("Buy Nifty futures when 9 EMA crosses 21 EMA on 15m, 0.5% trailing SL") → configured strategy | Not found | Not found | NSE-empanelled white-box provider **[snippet]** | Phoenix ₹1,600–8,300; Pro Build from ₹20,000; marketplace ₹499–3,999/month | Example prompt is almost exactly Eve's demo. |
| **INDfolio AI** (2024) | English → strategy → backtest → paper on live data → deploy | **7 years NSE minute data, brokerage + taxes + slippage** | **Parameter optimisation, walk-forward, Monte Carlo** (claimed) | 7 brokers incl. Zerodha, Fyers, Dhan | From ₹999 + GST | **The pitch closest to Eve's.** Size/empanelment unknown. |
| **Algoshastra** | English → **Python code** for backtesting | Models STT, slippage, brokerage, GST | Claims "overfitting detection" (method unknown) | Verification-focused **[unverified]** | Free: 5 prompts/day; paid tiers | Positions on "verification" — overlaps with Eve's angle. |
| **AlgoRaider** (indie) | Prompt ("Iron Condor when IV high, 30% SL") → deterministic multi-leg rules | Tick-level with slippage (claimed) | Not found | BYO key: Dhan, Zerodha, Angel, 5paisa, Fyers, Shoonya | Free tier | Early stage. Empanelment doubtful. |
| **Tradetron** | Claims one-click connect to Claude/ChatGPT to describe → build → backtest → deploy **[unverified]** | Users complain of "bogus backtests" on marketplace strategies | None | Creator marketplace, many brokers | Free → ₹300 → ₹1,200 → ₹2,500 → up to ₹15,000/month | **Regulatory cautionary tale** (March 2026 SEBI orders; see §8). Execution/exit failures reported. |
| **Arthalab, Snipy, EdgeTest, AlgoTradersLab** | All advertise plain-English building. EdgeTest: 10-year Nifty 500 backtests; AlgoTradersLab: 2 years NIFTY/SENSEX options tick data with Greeks | Varies | Not found | Varies | Not found | Small/early. |

### 3.2 Brokers — partners and potential competitors

| Broker | AI / algo assets | Implication for Eve |
|---|---|---|
| **Dhan** (Raise Financial) | DhanHQ API (free); **MCP server + open SKILL.md skills** (12 categories incl. backtesting, ScanX); asks for confirmation before every order. **Acquired Stratzy in April 2026** (NSE-empanelled, 100+ exchange-approved algos, claims 500k+ users). Raise raised $120M in 2025. | Our primary broker is building its own algo marketplace. **Partner or competitor — decide early.** Eve's honesty layer could be pitched to Dhan as a validation service. |
| **Upstox** | **Algoverse** (NSE/BSE-registered; ready-made + DIY no-code with 80+ indicators + backtest; ₹10/day per active strategy, ₹20 with premium). Upstox MCP + agent skills. Waives fees on partner platforms incl. AlgoTest. No AI builder in Algoverse found **[unverified]**. | Proven route for running DIY strategies under the SEBI framework; possible distribution partner. |
| **Zerodha / Streak** | New Streak (beta 2026) **free for all Zerodha users**; visual condition builder; **no LLM builder found**. Kite MCP (read + GTT). API ₹500/month. Won't run a strategy marketplace. Nithin Kamath: AI "can't turn a bad strategy into a good one". | Largest broker has no NL builder — opening for Eve via Kite API. Their stated philosophy matches Eve's. |
| **Groww** | Trade API, **Groww Cloud** (hosted algos, Oct 2025), AlgoTest partnership | Distribution, not an NL competitor yet. |
| **Angel One** | SmartAPI (static IP + 10 OPS from 1 Apr 2026); ARQ Prime is a recommendation engine | No NL builder. |
| **Kotak Neo** | Zero-brokerage, zero-fee trade APIs since Nov 2025 | Cheapest execution rail for users. |

### 3.3 Options analytics and no-code tools (no NL builder found)

**Sensibull** (Pro ₹800, Ultimate ~₹1,600/month; "Sensibull AI" ₹999
**[unverified]**), **Opstra/Definedge**, **StockMock** (from ₹349),
**Quantman** (~₹1,300/month), **TradeSmart** (with Modern Algos / KEEV),
**Sahi** ($33M Series B, Apr 2026 — AI insights, no builder), **Univest**,
**INDmoney**, **smallcase**. All are adjacent; none combine NL building with
rigorous validation.

---

## 4. Global competitors

### 4.1 Closest analogues

| Product | NL handling | Markets | Realism | Validation | Deploy | Price | Status |
|---|---|---|---|---|---|---|---|
| **Composer** (now "Composer by SoFi") | "Create/Trade with AI" → a **symphony**: a tree of rule blocks you can then edit visually. **Structured DSL, not code** — closest to Eve's spec. Deliberately "not agentic". | US equities, ETFs, crypto | SEC/FINRA fees; **default slippage only 1 bp** | **None formal**; their docs say the only real out-of-sample test is going live. 2,000+ community strategies ranked by backtest return (selection bias) | Yes (in-house broker-dealer) | $40/month | **Acquired by SoFi, 23 June 2026.** ~$11M raised before. Trustpilot: strategies "dramatically underperformed immediately after funding". |
| **QuantConnect** (Mia V2, LEAN, MCP) | Agent **writes free Python/C#**, runs backtests, reads errors, iterates. ~75% working code vs 25% for o3 (their claim). Official MCP server (64 tools). | US equities, options, futures, FX, crypto | **Best in class** (fee, slippage, fill, margin models) | Optimiser + sensitivity; walk-forward/Monte Carlo DIY; **no DSR/PBO**; free agent iteration invites data-snooping | Yes, many brokers | Credits; serious users ~$200–300/month | Active, ~280k users. |
| **NinjaTrader AI Strategy Builder** | NL entry/exit/risk/filter rules → **compiled NinjaScript (C#)** → Strategy Analyzer | US futures | Commission/slippage settings; whether the AI applies them by default **[unverified]** | Has optimiser + walk-forward tools | Native live futures | — | **Launched 9 Sept 2026**, beta. The most direct futures analogue (US). |
| **TrendSpider** (Sidekick, Strategy Tester) | "AI" button turns text/voice into point-and-click conditions; "AI Explain" suggests improvements | US stocks, ETFs, crypto, FX | **Weak** — docs admit "you always get your fill" | None; AI tuning is an overfitting loop | Bots/alerts | ~$82–321/month; 25 AI messages/month | Active. |
| **LuxAlgo** (Quant, AI Backtesting Assistant) | Pine coding agent; NL **search across 6M+ precomputed strategies** on 93 assets ("highest net profit on BTCUSD 5m") | Multi | Whatever the script sets | **None** — ranking millions by net profit is textbook multiple-testing bias | Via TradingView | From $39.99/month | Active. |
| **Pine generators** (Pineify, PineGen, PineGPT) | NL → Pine v6 code | TradingView | Script defaults, often zero cost | None | TradingView | Pineify one-time ~$99–259 | Main source of documented hallucinations (invented functions, v5/v6 confusion). TradingView's own AI Chart Copilot (beta Apr 2026) is not a reliable Pine generator. |

### 4.2 New entrants 2025–2026 ("vibe trading")

| Startup | What it does | Note |
|---|---|---|
| **Horizon Trade** | NL → generated code → backtest → risk analysis → one-click deploy (Binance, Coinbase, Kraken, IBKR) | $2M pre-seed July 2026; 23k waitlist; from $99/month |
| **Conviction** (YC S25) | NL → "structured, rules-based AI agent" → backtest + **stress tests on simulated crashes** → deploy | Funded; structured approach |
| **TradeZella** | Trading journal that added NL-rule backtests over 11+ years | From $29/month. **Journal + backtest overlap with Eve + Hisaab.** |
| **NexusTrade Aurora** | Agent researches, builds, backtests, **genetic optimisation**, trades autonomously | Optimisation amplifies overfitting |
| **NeuroBacktest** | NL → backtest with walk-forward, Monte Carlo, Bayesian optimisation, PDF reports | Only 80+ US/HK symbols; early |
| **3Commas QuantPilot**, **Cryptohopper AI Designer** | Agentic NL → crypto bots, with optimisation | Crypto only; no out-of-sample controls found |
| **Capitalise.ai** | IF/THEN English grammar → rules | **Acquired by Kraken, Aug 2025**; now crypto-only inside Kraken Pro |
| VIBTRA, Nodlow.ai, Stralgo, Backtrex, Elastics | Very early NL-to-backtest products | — |

### 4.3 Validation-first tools (not NL-first — the rigour benchmark)

- **StrategyQuant X** — genetic programming, Walk-Forward Matrix, 9+ Monte
  Carlo types, automatic rejection filters; exports to MT4/5, NinjaTrader and
  others. $11–269/month or lifetime. Steep learning curve; no DSR/PBO.
- **Build Alpha** — rule generator with noise tests vs random strategies.
  Not NL.

### 4.4 Brokers and AI labs adding agent rails (mostly no backtesting)

Robinhood Agentic Trading (May 2026; user bears all responsibility), IBKR MCP
(July 2026), Alpaca MCP v2 (61 actions; API trading up ~4× in Q1 2026),
Coinbase for Agents (June 2026), Public.com Generated Assets (prompt → AI
basket → simple backtest vs S&P 500; likely look-ahead and survivorship bias),
eToro Tori agent portfolios, Wealthsimple (Fey), Trade Ideas AI Assistant.
OpenAI (ChatGPT for Financial Services, Sept 2026), Anthropic (financial
services agents, May 2026) and Perplexity Finance do **not** offer
backtesting.

**Takeaway:** the industry is building *execution plumbing* that lets an LLM
trade directly, with no validation step in between. That makes an
independent "is this real?" layer more valuable, not less.

---

## 5. Open-source projects

### 5.1 Doing roughly the same thing

| Project | ★ / License | What it does | Use for Eve |
|---|---|---|---|
| **[HKUDS/Vibe-Trading](https://github.com/HKUDS/Vibe-Trading)** | ~34.9k / MIT | NL research workspace; multi-agent teams; **the LLM writes strategy code**; engines for A/HK/US/UK/**India**/Korea equities, futures, FX, crypto, options; Monte Carlo, bootstrap, walk-forward, "deflated significance", purged CV, run cards; MCP plugin; 462-factor Alpha Zoo; Shadow Account; `IndiaEquityEngine` with STT/stamp/exchange/SEBI/GST (added July 2026); Dhan and Shoonya connectors (paper/read-only). | **Main open-source rival. Benchmark and borrow; do not depend on it.** Read their India cost config as a cross-check. Their changelog is a list of generated-code bugs to cite. It is equity-focused for India; no NSE index-futures lots, rollover or expiry costs found. (Already compared in `VIBE_TRADING_COMPARISON.md`.) |
| **[fidetolabs/qanat](https://github.com/fidetolabs/qanat)** | 296 / MIT (Sept 2026) | DuckDB + MCP server with **scoped tool sets** (6/19/31 tools); **trial counting** raises the significance bar; a gate blocks "live" status | Closest to Eve's philosophy. **Borrow scoped tool sets**; compare trial-count logic. |
| **[claude-enterprise-openclaw-trading](https://github.com/jerrylearnscoding/claude-enterprise-openclaw-trading)** | 41 / MIT | NL → deterministic YAML if-else strategy tree → backtest → "iterate until targets met" | Schema ideas only. Its iterate-until-target loop is exactly the overfitting trap Eve avoids. |
| **[moss-trade-bot-skills](https://github.com/moss-site/moss-trade-bot-skills)** | 387 | NL → fixed five-pillar, 30+-parameter strategy; backtest/live parity (crypto) | Parameterised-template idea. |
| **[marketcalls/openalgo](https://github.com/marketcalls/openalgo)** | 2.8k / **AGPL-3.0** (SDK is MIT) | Self-hosted Indian algo platform: **36 broker plugins**, Analyzer (₹1 Cr sandbox), **Flow** no-code JSON node builder, `/agent` (Agno + LiteLLM), MCP server, Historify (DuckDB history). No backtester found **[unverified]**. | **Integrate over its HTTP API / MIT SDK, never embed** (AGPL). A ready broker bridge for paper → live across 36 brokers. Study the Flow JSON schema. |
| **[TauricResearch/TradingAgents](https://github.com/TauricResearch/TradingAgents)** | ~110k / Apache-2.0 | Multi-agent debate (analysts, bull/bear, trader, risk) → buy/sell/hold | Different paradigm (LLM is the trader). **Borrow the bull/bear debate for a "critique my strategy" feature.** Benchmark against it to show why a spec beats an LLM trader. |
| **[virattt/ai-hedge-fund](https://github.com/virattt/ai-hedge-fund)** | ~63.9k / MIT | Persona agents + backtester + paper mode with a **hash-chained ledger** | **Borrow the hash-chained paper ledger** for auditability. |
| **[microsoft/RD-Agent](https://github.com/microsoft/RD-Agent)** + **[Qlib](https://github.com/microsoft/qlib)** | 14.9k / 49.2k, MIT | LLM hypothesis → code → backtest → feedback loop, bandit scheduler; Qlib factor platform | Borrow the loop design only for a future "auto-explore" mode, **and count every trial**. |
| **[QuantConnect/mcp-server](https://github.com/QuantConnect/mcp-server)**, **[alpaca-mcp-server](https://github.com/alpacahq/alpaca-mcp-server)**, **[maverick-mcp](https://github.com/wshobson/maverick-mcp)** | Apache / MIT | Finance MCP servers | Borrow tool granularity (create → validate → backtest → read results) and paper-order safety confirmations. maverick-mcp is a FastMCP reference. |
| FinGPT, FinRobot, FinRL, Jesse (JesseGPT), Freqtrade/FreqAI, Hummingbot/Condor, OpenBB (Apache-2.0, MCP) | various | Adjacent | Low relevance. **Copy Freqtrade's `lookahead-analysis` / `recursive-analysis` idea** (GPL — ideas only). Jesse's 300+ indicator list can guide vocabulary growth. |

### 5.2 Libraries we can reuse

| Need | Use | Avoid (licence) |
|---|---|---|
| CV splitters (walk-forward, **combinatorial purged CV**) | **skfolio** (BSD-3) | timeseriescv (stale) |
| Bootstrap, **White's Reality Check / Hansen SPA / StepM / MCS** | **arch** (NCSA) | — |
| Deflated / probabilistic Sharpe reference | **jsharpe** (MIT) or our own (~200 lines) | **pypbo (AGPL)** — test-only cross-check; **mlfinlab** (proprietary) |
| Tear-sheet metrics cross-check | quantstats, empyrical/pyfolio-reloaded (Apache) | — |
| Event-driven engine with backtest/live parity (if ever needed) | **NautilusTrader** (LGPL, fine as an unmodified dependency) | **backtesting.py (AGPL)**, **backtrader (GPL, unmaintained)** |
| Fast sweeps | — | **vectorbt OSS and PyBroker** (Commons Clause: cannot sell a service built on them) |
| NSE data | Licensed broker/vendor data in the product | **nsepython (GPL)**, jugaad-data (non-standard "YOLO" licence; scrapes NSE) — dev experiments only |
| Indian F&O cost model | **None mature exists** — Eve's own model is a differentiator. Cross-check against Vibe-Trading's config and `Quantwala/indian-trading-charges` (brand new). | — |

---

## 6. What the research literature says

The academic picture through 2026 strongly supports Eve's architecture.

| Paper | Finding | Implication |
|---|---|---|
| **What survives honest evaluation?** (Gençay, arXiv 2608.27734, ~Aug 2026) | **Every LLM-discovered strategy failed certification against its own trial count**; passive risk premia passed. A planted look-ahead oracle *survived* deflation at Sharpe 35. | Most important paper for Eve. Leakage-safety must be **structural** (spec can't express look-ahead), and DSR/PBO must use the **true trial count**. Eve already does both. |
| **The Alpha Illusion** (arXiv 2605.16895, May 2026) | Reported alpha isn't deployment evidence until it passes temporal integrity, frictions, robustness, calibration, execution checks. Recommends **LLMs as auditable interfaces upstream of independent risk and execution modules**. | Describes Eve's design almost exactly. Use as a design citation and adopt its P1–P6 reporting checklist. |
| **Profit Mirage** (2510.07920) | Best LLM agents lose ~50% of returns after the knowledge cutoff; GPT-4o answers >85% of historical market questions (memorisation). | **The LLM must never see outcome data**; it only translates the user's text. Eve already separates these. |
| **FINSABER** (2505.07078, KDD'26) | Over 20 years and 100+ symbols, LLM advantages "deteriorate significantly"; survivorship and data-snooping inflated earlier results. | Long-history testing matters; Eve has 2022–2026. |
| **StockBench** (2510.02209), **AI-Trader** (2512.10971) | LLM agents "rarely outperform simple baselines"; finance knowledge ≠ trading skill. | Always show a buy-and-hold baseline (Eve's `lags_buy_and_hold` label). |
| **Alpha-GPT** (2308.00016) | LLM translates researcher ideas into a **restricted alpha DSL**; top-10 of 41k in WorldQuant IQC 2024. | Validates NL → constrained language. |
| **AlphaAgent** (2502.16789, KDD'25) | Regularises LLM factor search with **complexity caps, originality vs existing alphas, and hypothesis–factor alignment**. | **Borrow:** complexity budget and novelty checks on specs. |
| RD-Agent(Q), QuantAgent, FinMem, FinAgent, TradingAgents | Large reported returns on short windows; the critiques above target these. | Benchmark, don't imitate. |

---

## 7. Feature comparison matrix

✅ = yes · ◐ = partial / claimed · ❌ = no / not found · ? = unknown

| Capability | **Eve** | FYERS FIA | AlgoTest | uTrade AI | AlgoBulls | INDfolio | Streak | Composer | QuantConnect Mia | NinjaTrader AI | Vibe-Trading (OSS) |
|---|---|---|---|---|---|---|---|---|---|---|---|
| NL → strategy | ✅ | ✅ | ✅ | ✅ | ✅ | ✅ | ❌ | ✅ | ✅ | ✅ | ✅ |
| Typed spec, no generated code | ✅ | ◐ (canvas) | ◐ (visual) | ? | ◐ | ? | ✅ (visual) | ✅ (blocks) | ❌ (code) | ❌ (code) | ❌ (code) |
| Look-ahead impossible by construction | ✅ | ? | ? | ? | ? | ? | ? | ◐ | ❌ | ❌ | ❌ |
| Summary rendered from spec, not LLM | ✅ | ? | ? | ? | ? | ? | n/a | ◐ | ❌ | ❌ | ❌ |
| Hindi / Indian languages | ❌ | ❌ | ❌ | ✅ | ❌ | ❌ | ❌ | ❌ | ❌ | ❌ | ◐ |
| Full Indian F&O cost model by default (dated STT) | ✅ | ? | ◐ (user slippage) | ? | ? | ◐ | ◐ | n/a | ❌ | n/a | ◐ (equities) |
| Walk-forward | ✅ | ❌ | ❌ | ? | ? | ◐ | ❌ | ❌ | ◐ (DIY) | ✅ | ✅ |
| Bootstrap / permutation tests | ✅ | ❌ | ❌ | ? | ? | ◐ (MC) | ❌ | ❌ | ◐ (DIY) | ◐ | ✅ |
| Deflated Sharpe with true trial count | ✅ | ❌ | ❌ | ❌ | ❌ | ❌ | ❌ | ❌ | ❌ | ❌ | ◐ |
| PBO (CSCV) | ✅ | ❌ | ❌ | ❌ | ❌ | ❌ | ❌ | ❌ | ❌ | ❌ | ❌ |
| Holdout used once (enforced) | ✅ | ❌ | ❌ | ❌ | ❌ | ❌ | ❌ | ❌ | ❌ | ❌ | ❌ |
| Plain-language honest verdict | ✅ | ❌ | ❌ | ❌ | ❌ | ❌ | ❌ | ❌ | ❌ | ❌ | ◐ |
| Numeric grounding check on AI answers | ✅ | ❌ | ❌ | ❌ | ❌ | ❌ | ❌ | ❌ | ❌ | ❌ | ❌ |
| Paper trading | ✅ | ✅ | ✅ | ✅ | ✅ | ✅ | ✅ | ❌ | ✅ | ✅ | ✅ |
| Live trading | ❌ | ✅ | ✅ | ✅ | ✅ | ✅ | ✅ | ✅ | ✅ | ✅ | ✅ |
| Options | ❌ | ✅ | ✅ | ✅ | ✅ | ? | ✅ | ❌ | ✅ | ❌ | ✅ |
| Multi-broker | ◐ (data: Dhan, Upstox) | ❌ | ✅ (60+) | ✅ | ✅ | ✅ (7) | ❌ | ❌ | ✅ | ❌ | ✅ |
| Trading journal integration | ✅ (Hisaab) | ❌ | ❌ | ❌ | ❌ | ❌ | ❌ | ❌ | ❌ | ❌ | ◐ (Shadow Account) |
| Strategy marketplace / leaderboard | ❌ (deliberately) | ❌ | ◐ | ? | ✅ | ? | ❌ | ✅ | ✅ | ❌ | ❌ |
| MCP server | ✅ | ✅ | ❌ | ❌ | ❌ | ❌ | ◐ (Kite) | ❌ | ✅ | ✅ | ✅ |

**Reading the matrix:** Eve loses on breadth (options, live trading,
brokers, language) and wins on everything to do with *trust* (typed spec,
structural no-look-ahead, honest statistics, verdict, grounding). The
breadth gaps can be closed; the trust lead is hard to copy because it
requires saying "no" to users, which most competitors' business models avoid.

---

## 8. Regulation (SEBI / NSE) and what it means for Eve

*My interpretation of public summaries — not legal advice.*

### 8.1 The retail algo framework (SEBI circular, 4 Feb 2025)

- **Mandatory for everyone from 1 April 2026** (phased since Oct 2025).
- **The broker is the principal.** Algo providers are the broker's agents
  and cannot connect to exchanges directly.
- **Algo ID:** every algo order carries an exchange-assigned ID; **changing a
  strategy's logic means registering it again**.
- **10 orders per second** per client per exchange segment. A client's own
  algo below that rate is "regular API use"; **any algo *offered* by a
  provider must be registered whatever its rate.**
- **Static IP** for API orders; daily two-factor login.
- **White-box** (logic disclosed and reproducible) vs **black-box** (hidden
  logic → **SEBI Research Analyst registration** and a research report per
  algo).
- **Empanelment as algo provider** with each exchange via a broker: ISO
  27001:2022, twice-yearly CERT-In-empanelled security audits; ~T+30 days
  to empanel; algo approval ~T+7 to T+10 working days.
- **No performance claims.** Brokers may not refer to past or expected algo
  returns or associate with platforms that do (SEBI 2022, carried forward).
  **Enforced:** March 2026 orders in the matter of *Tradetron and other algo
  platforms* fined ~10 brokers ₹16 lakh in total.
- **PaRRVA** (fully operational 4 May 2026; CARE Ratings + NSE): algo
  providers may advertise only verified performance.
- **AI/ML:** RA/IA rules (Dec 2024) require disclosing AI use. SEBI's AI/ML
  consultation (June 2025) proposes an accountable owner per model,
  explainability, audits, human oversight and **kill switches**. Final
  guidelines still pending as of Aug 2026.

### 8.2 What each Eve stage needs

| Stage | Registration | Conditions |
|---|---|---|
| NL → spec → backtest on the user's own idea | **None** (framework covers only orders) | Do not **recommend** strategies or securities (RA/IA territory). No return leaderboards. Label results as hypothetical. Never say "assured" or "consistent". |
| Paper trading | **None** | Live NSE data shown to users may need a data-vendor licence **[unverified]** — safest to feed paper trading from each user's own broker data API. |
| Live, user's own API key, user's static IP, < 10 OPS | Probably none | Weak position: once Eve hosts the strategy and sends orders, it acts as a provider. |
| **Live, hosted by Eve (realistic route)** | **Empanelment with NSE/BSE through Dhan and/or Upstox**; each strategy gets an Algo ID | White-box (user-authored, logic visible) → **no RA needed**. ISO 27001, CERT-In audits, static IP, kill switch, re-registration when logic changes. |
| Selling Eve-authored or hidden strategies | **RA registration** | Avoid. |

**Key design consequence:** because changing logic means re-registering, a
**parameterised grammar of approved rule templates** may get through
registration far better than arbitrary specs. Eve's closed-vocabulary spec is
already close to this — a regulatory advantage over code generators. How the
exchanges assign Algo IDs to **user-built DIY strategies on a provider's
platform** is the top open question (§16). Upstox Algoverse and AlgoTest
already run DIY strategies under the framework, so a path exists.

**Eve's existing design already anticipates the rules:** kill switch, human
approval to promote, audit log, no live tier, spec shown to the user before
running (human oversight), white-box by construction, verdict language that
never claims proof.

---

## 9. Market size

| Metric | Figure |
|---|---|
| Demat accounts | **23.44 crore** (July 2026) |
| NSE unique investors | **13.1 crore** (May 2026) |
| NSE active investors | **4.57 crore** (March 2026, −7% y/y) |
| Individual F&O traders | **78.6 lakh in FY26** (98.1 lakh FY25, −20%) |
| Share losing money | **87.7%** (FY26); 91% (FY25); 93% over FY22–24 |
| Total F&O losses | ₹91,685 crore (FY26) |
| **Transaction costs** | **₹24,859 crore (FY26)**, ~₹31,628 per trader; **turned ~4.4 lakh traders from gross profit to net loss** |
| Algo share of F&O notional turnover | ~70% (FY25) |
| Retail algo use | 13% of F&O traders (FY24; SEBI says overstated) |
| Reference user bases | Stratzy 500k+ (claimed); AlgoTest ~13k active (2024) |

**Sizing sketch (illustrative, not a forecast):**

- **Serviceable market:** ~78.6 lakh F&O traders, plus a few lakh
  serious cash/positional traders who test ideas.
- **Reachable early segment:** systematic-minded traders who already use
  algo tools.
  - If ~5–10% of F&O traders → **4–8 lakh people**.
  - At ₹500–1,000/month and 2% conversion → **₹5–20 crore ARR**.
  - Broker partnerships and B2B validation (§12) raise this ceiling.

---

## 10. Gaps in the market

1. **Nobody gives an honest verdict.** Products are built to reach
   "deploy" fast. None tells the user "this is probably noise — don't trade
   it." AI commentary explains and tunes results; it does not try to
   disprove them.
2. **Overfitting is getting worse with AI.** Iterating costs nothing now;
   leaderboards, "AI suggests improvements" and genetic optimisers are
   data-snooping machines. No consumer product counts trials.
3. **Generated code hallucinates and users can't audit it.** Silent logic
   errors, invented functions, look-ahead.
4. **Indian F&O costs are mostly a number the user types in.** Dated STT
   (0.05% since April 2026), stamp duty, exchange and SEBI fees, GST,
   lot-size changes (NIFTY 65, BANKNIFTY 30), weekly vs monthly expiries
   (BANKNIFTY monthly-only; NSE expiries on Tuesday), rollover and impact
   cost are rarely modelled properly.
5. **Backtest–live gap is the #1 complaint** (Composer, Tradetron,
   Tickeron).
6. **Brokers are skipping straight to agentic execution** (Robinhood,
   Coinbase, IBKR, Alpaca, Dhan, Upstox MCP) with no validation layer between
   idea and order.
7. **No link between what you planned and what you did.** Backtesters
   and journals are separate products (TradeZella is the only one bridging
   them, US-only).
8. **Compliance-safe positioning is scarce.** Many Indian platforms market
   returns; SEBI is now fining for it.

---

## 11. What we should adopt from others

Ordered roughly by value-to-effort.

| # | Idea | Seen in | Why / how for Eve |
|---|---|---|---|
| 1 | **Hindi (and later Hinglish, Gujarati, Marathi, Tamil) strategy input** | uTrade | Huge for Tier-2/3 traders. The typed spec makes this cheap: the LLM translates any language into the same spec; the summary is rendered from the spec in the chosen language. |
| 2 | **Options support** (multi-leg, Greeks, expiry-aware) | AlgoTest, Sensibull, FYERS, AlgoRaider, Vibe-Trading | ~92% of retail F&O losses are in options and ~59% of index options turnover is 0DTE. Biggest demand pool. Needs options data and an expiry calendar. |
| 3 | **Bigger closed vocabulary**: SuperTrend, VWAP, Donchian, ADX, Stochastic, CPR/pivots, ORB, IV rank, PCR, OI change, time-of-day/expiry-day filters | AlgoTest, Streak, Jesse (300+), Quantman | Users' prompts (e.g. "SuperTrend turns green and RSI > 55") must compile. Track "unsupported concept" requests to decide what to add. |
| 4 | **Visual editor on the same spec** | Composer, Streak, FYERS canvas, OpenAlgo Flow | Phase 15 has chat + form; add a block/flow view. One spec, three views. |
| 5 | **Stress tests on synthetic crashes / vol spikes** | Conviction (YC S25), StrategyQuant Monte Carlo | Run the spec through Mar-2020, Jun-2024 election day and budget days, plus synthetic gaps. Show it as "how this strategy behaves on the worst days." |
| 6 | **Broker breadth through one bridge** | OpenAlgo (36 brokers), AlgoTest (60+) | Talk to OpenAlgo over its API/MIT SDK for paper → live, instead of building N connectors. |
| 7 | **"Critique my strategy" debate** | TradingAgents bull/bear | A sceptic agent attacks the spec *before* backtesting (regime dependence, too many params, obvious data mining). Cheap; fits the honesty brand. |
| 8 | **Extract rules from the user's own trades** (Shadow Account) | Vibe-Trading | Hisaab already has the journal: "Here are the 3 rules you actually trade by, and how they backtest." Strong tie-in. |
| 9 | **Scoped MCP tool sets** | qanat | Expose 6 / 19 / 31 tools by mode to save tokens and reduce wrong tool calls. |
| 10 | **Hash-chained paper ledger** | ai-hedge-fund | Tamper-evident paper history; useful later for PaRRVA-style verification. |
| 11 | **Complexity budget + novelty check on specs** | AlphaAgent | Penalise specs with many conditions/parameters; warn when a "new" strategy is a near-duplicate of one already tried (and count it as a trial). |
| 12 | **Look-ahead and recursive analysis as automated checks** | Freqtrade (ideas only, GPL) | Re-run each backtest with data truncated at random points; signals must not change. Plant a look-ahead oracle in tests (per 2608.27734). |
| 13 | **Scheduled research / alerts on Telegram & WhatsApp** | Vibe-Trading, Tradetron | "Your paper strategy hit its drawdown limit" on WhatsApp — the channel Indian traders actually use. |
| 14 | **Downloadable PDF research report** | NeuroBacktest, Vibe-Trading run cards | A shareable "strategy certificate" (see USP 2). |

**Do not adopt:** strategy leaderboards ranked by return, "AI improves your
strategy until it hits target" loops, genetic/AI optimisation without trial
accounting, return-based marketing, black-box (hidden-logic) strategies.

---

## 12. USPs — how Eve becomes unique

### Already ours (defend and market them)

1. **"What you read is what runs."** Typed spec, summary rendered by code,
   look-ahead impossible to express. Competitors generate code that neither
   the user nor the LLM can fully vouch for.
2. **Every attempt counts.** Trial-counted deflated Sharpe, PBO, holdout used
   once. Backed by 2026 research showing LLM-found strategies fail exactly
   this test. Nobody in retail does this.
3. **Indian F&O costs to the rupee, with dates.** Dated STT schedule, live
   lot/tick sizes, statutory charges. SEBI's own data says costs flip lakhs
   of traders to losses.
4. **Honest verdict in plain language** — including "too few trades",
   "failed holdout", "lags buy-and-hold". Willing to say no.
5. **Grounded AI.** Every number in an answer traces to deterministic code;
   the grounding checker blocks invented figures.
6. **Backtest + journal in one place** (Eve + Hisaab).

### New USPs worth building

1. **"Reality Gap" — plan vs actual.** Hisaab knows what the user *actually*
   did; Eve knows what the strategy *said* to do. Show trade-by-trade where
   the user deviated (late entry, moved stop, skipped signal) and the rupee
   cost of each deviation.
   - Nobody has both halves.
   - This is the strongest unique feature available to us.
2. **Shareable Strategy Certificate.** A hash-stamped, one-page report:
   - the exact spec
   - the data window and costs
   - the number of trials
   - DSR, PBO and the holdout result
   - the verdict

   It is a verifiable artefact a trader can show a mentor, a community or a
   prop desk. It cannot be gamed by cherry-picking, because the trial count
   and holdout use are on it. It is also compatible with SEBI's no-cherry-pick
   direction (PaRRVA).
3. **Cost X-ray.** For any strategy, show gross vs net and which charge
   eats the edge (STT, slippage, brokerage, GST). Add "break-even win rate
   at your trade frequency".
   - Answers the #1 retail failure that SEBI identified.
   - Users can grasp it in seconds and will want to share it.
4. **"Kill it early" mode — the falsification-first assistant.**
   - Before any backtest, Eve states what result would *disprove* the idea.
   - It pre-registers that automatically (we already have pre-registration
     machinery).
   - It then runs the cheapest tests that could kill the idea first.
   - Markets as: *"Eve saves you money by killing bad ideas before the
     market does."*
5. **Vernacular-first.** Hindi/Hinglish and regional languages, including
   voice. Only uTrade has Hindi, and none pair it with honest validation.
6. **Expiry-aware Indian calendar intelligence.**
   - Weekly vs monthly expiries and expiry-day behaviour.
   - Budget, RBI and election days; holiday gaps.
   - Built-in regime tags ("works only on expiry days", "fails in high-VIX
     regimes").
   - Global tools don't know the NSE calendar.
7. **Validation-as-a-service (B2B).**
   - Offer the honesty engine as an API to brokers (Dhan/Stratzy, Upstox
     Algoverse, Groww Cloud), algo marketplaces and prop firms.
   - The pitch: "Every strategy on your platform gets an independent verdict."
   - Fits SEBI's direction on performance claims and puts Eve on the right
     side of the regulator.
8. **Paper-to-live graduation gate.**
   - A strategy can be promoted only after it survives the holdout **and**
     N weeks of paper trading in which the live-vs-backtest tracking error
     stays within bounds.
   - Turns the "backtest–live gap" complaint into a product feature.
9. **Behavioural fit score.**
   - Uses Hisaab's psychology data (tilt, revenge trading, hold-time
     discipline).
   - Tells the user whether *they* can actually run this strategy. Example:
     "this needs you to sit through 9 losing trades in a row; your journal
     says you usually abandon after 4."
10. **Strategy health monitor.** After deployment, detect drift between
    live/paper and backtest distributions (win rate, slippage, trade
    frequency) and automatically suggest pausing (kill switch).

---

## 13. Positioning and pricing

**One line:** *"Describe your strategy in plain English or Hindi. Eve shows
you exactly what it will run, tests it on real NSE data with every rupee of
charges, and tells you honestly whether it's an edge or luck."*

**Against each group of competitors:**

| Against | Message |
|---|---|
| AlgoTest / Tradetron / uTrade / FYERS FIA | "They help you deploy faster. Eve tells you whether you should deploy at all." |
| QuantConnect / Pine generators / Vibe-Trading | "No generated code to debug or trust. You read the exact rules that run, and future data can't leak in." |
| Broker MCP + ChatGPT/Claude | "A general AI will happily place your trade. Eve checks it first." |
| SEBI / compliance-conscious partners | "No return claims, white-box by construction, kill switch, audit trail, verdicts that never say 'proven'." |

**Pricing benchmarks (India):** AlgoTest ₹599/week–₹1,499/28 days;
uTrade/INDfolio from ₹999/month; Quantman ~₹1,300; AlgoBulls ₹1,600–8,300;
Tradetron ₹300–15,000; Upstox Algoverse ₹10–20/day per strategy; Streak now
free for Zerodha users.

**Suggested model:**

- **Free tier:** NL → spec → a limited number of backtests per day, plus Cost
  X-ray. This is the growth hook, and free Streak sets the expectation.
- **Pro, ~₹699–999/month:**
  - unlimited backtests
  - full validation and verdict
  - paper trading
  - Reality Gap with Hisaab
  - Strategy Certificates
- **B2B:** validation API priced per evaluated strategy or as a platform
  licence, for brokers, marketplaces and prop firms.
- **Never** charge for or promote "winning strategies."

---

## 14. Risks and threats

| Risk | Severity | Mitigation |
|---|---|---|
| **Brokers ship "good enough" NL builders for free** (FYERS FIA live; Dhan + Stratzy; free Streak) | High | Be broker-neutral and the trust layer they lack; pursue B2B validation partnerships rather than competing on deployment. |
| **Dhan becomes a competitor** after buying Stratzy | Medium–High | Keep Upstox (and Kite/OpenAlgo) as alternatives; pitch Eve's verdict engine to Dhan as complementary. |
| **"Honest = depressing"**: users want to hear yes | High | Make "no" useful: show *why* the idea failed, what nearly worked, cost break-even and the Reality Gap. Frame it as money saved. |
| **Regulatory: live trading requires empanelment** (ISO 27001, audits, Algo IDs, re-registration per logic change) | Medium | Stay backtest + paper until a broker partnership is signed; design the spec as registrable templates. |
| **Performance-claim enforcement** (Tradetron fines; PaRRVA) | Medium | Never market returns; certificates show methodology and verdict, not promises. |
| **Data licensing** for displaying NSE data / paper trading | Medium | Use each user's own broker data feed; confirm NSE vendor rules. |
| **Vibe-Trading or a well-funded entrant adds DSR/PBO** | Medium | The moat is the combination (typed spec + Indian costs + journal + Reality Gap + verdict + compliance posture), not any single statistic. Publish methodology openly to own the narrative. |
| **Narrow vocabulary rejects user ideas** | Medium | Log unsupported concepts; expand the vocabulary weekly from real demand; explain clearly what can't be expressed yet. |
| **LLM cost and latency** | Low–Medium | The model only fills a form; small models suffice. Cache vocabulary prompts. |

---

## 15. Recommended roadmap

**Next 4–6 weeks (sharpen the moat):**

1. **Cost X-ray** and break-even win rate in every result.
2. **Strategy Certificate** (PDF + hash) from existing run cards.
3. **Expand vocabulary** with the 10 most-requested concepts: SuperTrend,
   VWAP, ADX, Stochastic, Donchian, CPR, ORB, time-of-day, expiry-day,
   previous-day high/low.
4. **Structural look-ahead test**: plant an oracle; truncated-data
   re-run check.
5. **"Critique my strategy"** sceptic pass before backtest.

**Next 2–3 months (differentiate):**

6. **Reality Gap** (Hisaab journal × Eve spec).
7. **Hindi / Hinglish** input and rendered summaries.
8. **Stress scenarios** (event days + synthetic shocks) and regime tags.
9. Visual block editor on the same spec.
10. WhatsApp/Telegram alerts for paper strategies.

**Next 3–6 months (expand):**

11. **Options**: multi-leg specs, expiry calendar, Greeks, options data.
12. **Paper-to-live graduation gate** and strategy health monitor.
13. **Broker partnership + empanelment path** (Upstox Algoverse model or
    Dhan); evaluate OpenAlgo as the execution bridge.
14. **B2B validation API** pilot with one broker, marketplace or prop firm.

---

## 16. Open questions to verify

1. **How NSE assigns Algo IDs to user-built DIY strategies on a provider's
   platform**: per user strategy, or one registered builder with parameter
   templates? (NSE/INVG/69255; NSE FAQ 3 Nov 2025; ask Dhan/Upstox
   compliance.) This decides whether an edited spec can go live without days
   of approval.
2. Empanelment net-worth and fee criteria.
3. NSE data-vendor licensing for showing live or delayed data in paper
   trading.
4. Which of AlgoTest, Tradetron, uTrade, INDfolio and Streak are on NSE's
   empanelled list.
5. FYERS FIA's cost model and validation depth; uTrade's backtest realism;
   INDfolio's actual walk-forward and Monte Carlo implementation.
6. Whether Upstox Algoverse adds an AI builder; the scope of Dhan's
   post-Stratzy product.
7. SEBI's final AI/ML guidelines (expected after Aug 2026).
8. Vibe-Trading's exact DSR implementation and whether it counts trials.

---

## 17. Sources

**Indian market and regulation**
- FYERS FIA: https://support.fyers.in/portal/en/kb/articles/what-is-fia-in-fyers-automate-and-what-can-it-help-me-do · https://cxotoday.com/media-coverage/fyers-launches-advanced-ai-automation-tools-built-around-how-traders-actually-trade/ · https://fyers.in/whats-new/fyers-mcp-is-now-live
- AlgoTest: https://algotest.in/blog/detailed-pricing-information-for-algotest/ · https://algotest.in/blog/how-to-create-trading-signals-ai.md
- uTrade: https://www.utradealgos.com/faqs/what-is-utrade-ai-strategy-builders
- AlgoBulls Phoenix: https://alpaca.markets/learn/streamlining-trading-strategy-generation-with-phoenix-copilot
- INDfolio: https://www.techjockey.com/detail/indfolio
- Algoshastra: https://www.stork.ai/en/algoshastra
- AlgoRaider: https://www.indiehackers.com/post/building-a-prompt-to-strategy-trading-engine-for-indian-markets-now-free-to-test-live-c16q6TllmctBK1woel3U
- Tradetron enforcement: https://moneylife.in/article/sebi-cracks-down-on-tradetronlinked-brokers-slaps-16-lakh-penalties-over-assured-returns-claims/80053.html · https://www.sebi.gov.in/enforcement/orders/mar-2026/adjudication-order-in-respect-of-samco-securities-limited-in-the-matter-of-tradetron-and-other-algo-platforms_100597.html
- Dhan MCP / Stratzy: https://dhan.co/blog/trading-strategies/how-dhan-mcp-skills-help-traders-build-ai-trading-flows/ · https://yourstory.com/2026/04/dhan-parent-raise-financial-acquires-stratzy
- Upstox Algoverse: https://upstox.com/algoverse/ · https://community.upstox.com/t/announcing-upstox-mcp-your-trading-data-now-works-with-ai-assistants/14334
- Zerodha / Streak: https://zerodha.com/z-connect/streak/streak-is-now-available-for-all-zerodha-users-at-no-cost · https://zerodha.com/z-connect/featured/connect-your-zerodha-account-to-ai-assistants-with-kite-mcp · https://zerodha.com/z-connect/general/a-comprehensive-overview-of-nses-circular-on-the-new-retail-algo-trading-framework
- Groww Cloud: https://groww.in/updates/groww-cloud-algo-trading
- SEBI framework timeline: https://www.outlookbusiness.com/markets/sebi-extends-deadline-to-implement-retail-algo-trading-by-april-2026
- NSE FAQ: https://nsearchives.nseindia.com/web/sites/default/files/inline-files/FAQ_Retail_Algo_03112025_NSE.pdf
- PaRRVA: https://www.newsonair.gov.in/sebi-operationalises-parrva-to-boost-transparency-and-investor-protection/
- SEBI AI/ML: https://www.taxmann.com/post/blog/sebi-proposes-ai-ml-governance-framework-for-securities-markets · https://www.moneylife.in/article/ai-in-markets-sebi-to-mandate-human-oversight-kill-switches-and-data-controls-says-pandey/81406.html
- STT 2026: https://www.outlookmoney.com/invest/stt-hike-from-april-1-2026-budget-what-it-means-for-futures-and-options-traders
- Lot sizes: https://www.sahi.com/blogs/nifty-lot-size-2026-bank-nifty-sensex
- SEBI FY26 F&O study: https://www.businesstoday.in/markets/story/unique-individual-investors-in-fo-trading-declines-in-fy26-but-average-per-person-loss-widens-548559-2026-08-11 · https://www.businesstoday.in/markets/story/rs24800-crore-bill-how-transaction-costs-are-eating-into-retail-derivatives-trading-550694-2026-08-22
- Demat accounts: https://newsable.asianetnews.com/business/demat-account-additions-surge-in-july-2026-reach-234-4-million-articleshow-hykhvbp

**Global**
- Composer / SoFi: https://businesswire.com/news/home/20260623095057/en/Introducing-Composer-by-SoFi-AI-Powered-Investing-From-Idea-to-Execution · https://help.composer.trade/article/78-slippage-and-fees
- QuantConnect Mia & MCP: https://www.quantconnect.com/announcements/19846/your-ai-quant-developer/ · https://www.quantconnect.com/docs/v2/ai-assistance/mcp-server/key-concepts
- NinjaTrader AI Strategy Builder: https://ninjatrader.com/support/helpGuides/nt8/ai-strategy-builder-beta.htm
- TrendSpider: https://help.trendspider.com/kb/strategy-tester/understanding-strategy-tester-from-trendspider
- LuxAlgo: https://www.luxalgo.com/blog/ai-backtesting-now-with-millions-of-trading-strategies/
- Pine hallucinations: https://quantnomad.beehiiv.com/p/when-ai-gets-pine-script-wrong
- StrategyQuant X: https://strategyquant.com/features/
- Horizon Trade: https://dealroom.co/news/139499-horizon-trade-raises-2m-pre-seed-to-open-systematic-trading-to-everyone/
- Capitalise.ai / Kraken: https://www.businesswire.com/news/home/20250820275978/en/Kraken-Acquires-Capitalise.ai-to-Bring-No-Code-Trading-Automation-to-Kraken-Pro
- Robinhood agentic: https://finance.yahoo.com/markets/stocks/articles/robinhood-now-lets-ai-trade-001000698.html
- TradeZella: https://www.tradezella.com/blog/ai-backtesting

**Open source**
- https://github.com/HKUDS/Vibe-Trading · https://github.com/fidetolabs/qanat · https://github.com/marketcalls/openalgo · https://github.com/TauricResearch/TradingAgents · https://github.com/virattt/ai-hedge-fund · https://github.com/microsoft/RD-Agent · https://github.com/microsoft/qlib · https://github.com/QuantConnect/Lean · https://github.com/QuantConnect/mcp-server · https://github.com/alpacahq/alpaca-mcp-server · https://github.com/nautechsystems/nautilus_trader · https://github.com/skfolio/skfolio · https://github.com/bashtage/arch · https://github.com/tschm/jsharpe · https://github.com/esvhd/pypbo · https://github.com/freqtrade/freqtrade · https://github.com/jerrylearnscoding/claude-enterprise-openclaw-trading

**Papers**
- What survives honest evaluation? https://arxiv.org/abs/2608.27734
- The Alpha Illusion: https://arxiv.org/abs/2605.16895
- Profit Mirage: https://arxiv.org/abs/2510.07920
- FINSABER: https://arxiv.org/abs/2505.07078
- StockBench: https://arxiv.org/abs/2510.02209
- AI-Trader: https://arxiv.org/abs/2512.10971
- Alpha-GPT: https://arxiv.org/abs/2308.00016
- AlphaAgent: https://arxiv.org/abs/2502.16789
- RD-Agent(Q): https://arxiv.org/abs/2505.15155
- TradingAgents: https://arxiv.org/abs/2412.20138
