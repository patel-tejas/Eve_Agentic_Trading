# AI-Powered Quantitative Trading Research & Execution Platform

## Project Proposal, Architecture & Implementation Plan

**Project Type:** AI-powered quantitative research and algorithmic
trading platform\
**Primary Market:** Indian Equity Derivatives\
**Primary Instrument:** NIFTY Futures\
**Initial Broker/Data Provider:** DhanHQ\
**Initial Research Period:** July 2026\
**Initial Timeframes:** 1-minute, 5-minute, 15-minute\
**Baseline Strategy:** 9 EMA / 15 EMA crossover + ±30° EMA-angle filter\
**Agent Runtime:** Eve\
**Tool Protocol:** MCP\
**Quantitative Engine:** Python\
**Local Research Storage:** Parquet + DuckDB\
**Long-Term Data Warehouse:** Snowflake\
**Future Streaming Layer:** Kafka\
**Frontend:** Next.js + TypeScript\
**Status:** Proposal / Architecture Definition

------------------------------------------------------------------------

## 1. Executive Summary

This project proposes an AI-powered quantitative research and trading
platform for the Indian market.

The platform will combine:

-   broker market-data APIs
-   historical market-data ingestion
-   quantitative indicators
-   deterministic strategy engines
-   backtesting
-   parameter research
-   walk-forward validation
-   AI-agent orchestration
-   MCP-based tools
-   real-time market data
-   risk management
-   paper trading
-   eventual broker execution
-   Snowflake-based historical analytics

The initial research problem is deliberately narrow:

> Determine whether a 9 EMA / 15 EMA crossover strategy with a ±30°
> EMA-angle filter has a repeatable trading edge on NIFTY Futures.

The strategy will initially be tested independently on:

-   1-minute candles
-   5-minute candles
-   15-minute candles

The first dataset will focus on July 2026.

The project will not initially trade options and will not begin with
machine learning. The deterministic strategy must first be understood
and validated.

The long-term objective is to evolve this into an **AI quantitative
research assistant and trading platform** where a user can ask:

> "Download July NIFTY Futures data and backtest my strategy on 1m, 5m
> and 15m."

The system should automatically:

``` text
Resolve instrument
        ↓
Check data
        ↓
Fetch missing data
        ↓
Validate dataset
        ↓
Build candles
        ↓
Calculate indicators
        ↓
Generate signals
        ↓
Run backtests
        ↓
Calculate performance
        ↓
Compare timeframes
        ↓
Generate research report
```

The AI agent will orchestrate these actions, but the actual financial
calculations and trading rules will remain deterministic, tested Python
code.

------------------------------------------------------------------------

## 2. Problem Statement

Retail and student-built trading systems often have two major problems.

### Problem 1 --- Manual quantitative research

A researcher has to manually:

-   find the correct instrument
-   download historical data
-   clean the data
-   calculate indicators
-   write strategy code
-   run backtests
-   change parameters
-   compare timeframes
-   inspect results
-   repeat the entire process

This becomes slow and error-prone.

### Problem 2 --- AI trading systems can be unreliable

An LLM can explain a strategy, but it should not be trusted to directly
perform:

-   financial calculations
-   backtesting
-   position accounting
-   P&L calculation
-   risk calculation
-   order execution

These require deterministic and testable software.

### Proposed solution

Build an AI research layer on top of a deterministic quantitative
engine.

``` text
AI Agent
   ↓
Tool calls
   ↓
Deterministic Quant Engine
   ↓
Data / Strategy / Backtester
   ↓
Verified results
   ↓
AI explanation
```

This gives the user the convenience of an AI assistant without allowing
the LLM to become the source of truth for financial calculations.

------------------------------------------------------------------------

## 3. Project Vision

The long-term vision is:

> Build an AI-native quantitative research and trading platform for
> Indian markets where users can interact with market data, strategies,
> experiments and backtests using natural language while every important
> calculation is performed by deterministic, auditable software.

The platform should eventually support:

``` text
Research
   ↓
Strategy Development
   ↓
Backtesting
   ↓
Parameter Optimization
   ↓
Walk-Forward Validation
   ↓
Paper Trading
   ↓
Risk Validation
   ↓
Human-Approved Live Trading
```

------------------------------------------------------------------------

## 4. Initial Research Question

The first research question is:

> Does a 9 EMA / 15 EMA crossover combined with a ±30° EMA-angle filter
> generate a meaningful edge on NIFTY Futures?

Initial configuration:

``` text
Instrument:
NIFTY Futures

Fast EMA:
9

Slow EMA:
15

BUY:
9 EMA crosses above 15 EMA
AND EMA angle >= +30°

SELL:
9 EMA crosses below 15 EMA
AND EMA angle <= -30°

Initial Exit:
Opposite EMA crossover

Execution:
Next candle open

Timeframes:
1m
5m
15m

Initial Dataset:
July 2026
```

This baseline will be frozen before parameter optimization.

------------------------------------------------------------------------

## 5. Why NIFTY Futures

The actual intended trading instrument is NIFTY Futures.

Therefore, the primary backtesting data must represent futures rather
than only the NIFTY spot/index.

The futures dataset provides important information such as:

-   tradable futures price
-   volume
-   open interest
-   expiry
-   lot size
-   tick size
-   contract-specific metadata

NIFTY spot/index data may later be used as contextual market data, but
it will not replace futures data for the primary strategy backtest.

------------------------------------------------------------------------

## 6. Why 1m, 5m and 15m

The strategy will be tested separately on:

``` text
1 minute
5 minutes
15 minutes
```

EMA periods are candle-based.

  -----------------------------------------------------------------------
  Timeframe              EMA 9 approximate time   EMA 15 approximate time
                                        horizon                   horizon
  ------------------- ------------------------- -------------------------
  1m                                  9 minutes                15 minutes

  5m                                 45 minutes                75 minutes

  15m                               135 minutes               225 minutes
  -----------------------------------------------------------------------

The mathematical EMA weighting remains the same for a given period, but
the real-world time represented by each candle changes.

Therefore the three timeframes are effectively different trading regimes
and must be evaluated separately.

------------------------------------------------------------------------

## 7. Project Scope

### Included in initial scope

-   DhanHQ integration
-   NIFTY Futures instrument discovery
-   July 2026 historical data
-   1-minute raw candles
-   5-minute candles
-   15-minute candles
-   EMA 9
-   EMA 15
-   mathematical EMA angle
-   crossover signals
-   long/short backtesting
-   transaction costs
-   slippage
-   performance metrics
-   AI research agent
-   MCP tools
-   reproducible experiments
-   local Parquet storage
-   DuckDB analytics

### Later scope

-   Snowflake
-   live WebSocket data
-   Kafka
-   real-time signal generation
-   paper trading
-   risk engine
-   human approval
-   live order execution
-   ML-based signal filtering
-   additional instruments
-   options
-   advanced order-flow features

### Explicitly out of initial scope

-   options trading
-   automatic live trading
-   deep-learning trading models
-   autonomous LLM order execution
-   high-frequency trading
-   multi-broker execution

------------------------------------------------------------------------

## 8. High-Level Architecture

### Research architecture

``` text
                         USER
                           |
                           v
                    Next.js Dashboard
                           |
                           v
                     Eve AI Agent
                           |
                           v
                    MCP / Tool Layer
                           |
        +------------------+------------------+
        |                  |                  |
        v                  v                  v
    Data Tools        Strategy Tools      Research Tools
        |                  |                  |
        v                  v                  v
      DhanHQ          Python Quant Engine   Backtester
        |                  |                  |
        v                  v                  v
 Historical Data       Indicators          Metrics
        |                  |                  |
        +------------------+------------------+
                           |
                           v
                    Experiment Results
                           |
                           v
                    Parquet / DuckDB
                           |
                           v
                      Research UI
```

### Future production architecture

``` text
                         USER
                           |
                           v
                    Next.js Application
                           |
                           v
                       Eve Agent
                           |
                           v
                    MCP / Tool Layer
                           |
       +-------------------+-------------------+
       |                   |                   |
       v                   v                   v
   Research Tools      Broker Tools       Data Tools
       |                   |                   |
       v                   v                   v
  Quant Engine           DhanHQ            Snowflake
       |                   |                   |
       |                   v                   |
       |              Live Market Data        |
       |                   |                   |
       +-------------------+-------------------+
                           |
                           v
                         Kafka
                           |
                           v
                  Real-Time Feature Engine
                           |
                           v
                     Strategy Engine
                           |
                           v
                      Risk Engine
                           |
                           v
                  Human Approval Gate
                           |
                           v
                    Execution Engine
                           |
                           v
                         DhanHQ
```

------------------------------------------------------------------------

## 9. AI Agent Architecture

The AI layer will use **Eve** as the agent/orchestration runtime.

The agent will not directly perform quantitative calculations.

Instead:

``` text
User Request
     ↓
Eve Agent
     ↓
Tool Selection
     ↓
Deterministic Tool
     ↓
Verified Result
     ↓
Agent Explanation
```

Example:

``` text
User:
"Backtest NIFTY 9/15 EMA with 30 degree angle on July."

Eve:
1. Resolve NIFTY futures contract
2. Check whether July data exists
3. Fetch missing data if required
4. Validate data
5. Run 1m backtest
6. Run 5m backtest
7. Run 15m backtest
8. Compare metrics
9. Generate research report
```

------------------------------------------------------------------------

## 10. Why Eve

Eve is being evaluated as the agent runtime because it provides concepts
that map directly to this project:

-   agents
-   tools
-   skills
-   subagents
-   MCP connections
-   sandboxed execution
-   durable workflows
-   state
-   schedules
-   human-in-the-loop
-   evaluations

This avoids building the entire agent infrastructure from scratch.

Eve will be used primarily as the **orchestration and agent layer**,
while Python remains the quantitative source of truth.

------------------------------------------------------------------------

## 11. Eve Project Structure

A possible structure:

``` text
agent/
|
+-- instructions.md
|
+-- tools/
|   +-- get_instruments.ts
|   +-- get_futures_contract.ts
|   +-- get_historical_data.ts
|   +-- validate_market_data.ts
|   +-- calculate_ema.ts
|   +-- calculate_angle.ts
|   +-- generate_signal.ts
|   +-- run_backtest.ts
|   +-- compare_timeframes.ts
|   +-- run_parameter_search.ts
|
+-- skills/
|   +-- market-data.md
|   +-- futures-research.md
|   +-- ema-strategy.md
|   +-- backtesting.md
|   +-- risk-management.md
|
+-- subagents/
|   +-- data-agent/
|   +-- strategy-agent/
|   +-- research-agent/
|
+-- evals/
|
+-- connections/
```

------------------------------------------------------------------------

## 12. Agent Skills

Skills will hold domain-specific instructions.

Example:

``` text
agent/skills/ema-strategy.md
```

Conceptually:

``` markdown
Strategy:
9 EMA / 15 EMA

BUY:
Bullish crossover
AND positive angle >= 30°

SELL:
Bearish crossover
AND negative angle <= -30°

Signal:
Only after candle close

Execution:
Next candle open
```

Skills prevent the main agent prompt from becoming a huge collection of
unrelated rules.

------------------------------------------------------------------------

## 13. Subagent Architecture

The system can later use specialized subagents.

``` text
                    Main Research Agent
                            |
          +-----------------+-----------------+
          |                 |                 |
          v                 v                 v
      Data Agent       Strategy Agent    Research Agent
          |                 |                 |
          v                 v                 v
       DhanHQ           Indicators        Backtester
       Validation       Signals           Metrics
       Storage          Strategy          Experiments
```

### Data Agent

Responsible for:

-   instrument discovery
-   contract discovery
-   historical data retrieval
-   data validation
-   dataset storage

### Strategy Agent

Responsible for:

-   indicator configuration
-   strategy definitions
-   signal generation
-   strategy versioning

### Research Agent

Responsible for:

-   backtesting
-   metric calculation
-   parameter experiments
-   timeframe comparisons
-   walk-forward validation
-   report generation

------------------------------------------------------------------------

## 14. MCP Architecture

MCP will provide a standardized tool boundary between the agent and the
application.

Potential tools:

``` text
get_instruments
get_futures_contract
get_historical_candles
validate_dataset

build_5m_candles
build_15m_candles

calculate_ema
calculate_ema_angle
generate_signal

run_backtest
calculate_metrics
compare_timeframes

parameter_search
walk_forward_test

query_snowflake
save_dataset
load_dataset
```

The agent should never need to know how these tools are implemented
internally.

------------------------------------------------------------------------

## 15. DhanHQ Integration

DhanHQ will be the initial broker and market-data provider.

The integration will have two separate responsibilities.

### Historical

``` text
DhanHQ Historical API
        ↓
Instrument discovery
        ↓
NIFTY Futures
        ↓
Historical candles
        ↓
Parquet
```

### Future live phase

``` text
DhanHQ WebSocket
        ↓
Live futures data
        ↓
Real-time candle builder
        ↓
Feature engine
        ↓
Strategy
```

The internal data model will be broker-independent.

Example:

``` python
Candle(
    timestamp=...,
    instrument="NIFTY_FUT",
    open=...,
    high=...,
    low=...,
    close=...,
    volume=...,
    open_interest=...
)
```

This allows another broker to be added later without changing the
strategy engine.

------------------------------------------------------------------------

## 16. Historical Data Pipeline

The first pipeline:

``` text
DhanHQ
  ↓
Instrument Master
  ↓
Resolve NIFTY Futures
  ↓
Historical API
  ↓
July 2026 1m candles
  ↓
Raw validation
  ↓
Parquet
```

The first dataset should contain:

``` text
timestamp
instrument/security_id
open
high
low
close
volume
open_interest
```

------------------------------------------------------------------------

## 17. Data Storage Strategy

### Raw

``` text
data/raw/
```

Store data exactly as received after normalization.

### Processed

``` text
data/processed/
```

Store cleaned and aggregated datasets.

### Strategy results

``` text
data/results/
```

Store signals, trades and backtest metrics.

Suggested layout:

``` text
data/
|
+-- raw/
|   +-- futures/
|       +-- NIFTY/
|           +-- 2026-07/
|               +-- contract_metadata.json
|               +-- candles_1m.parquet
|
+-- processed/
|   +-- candles_5m.parquet
|   +-- candles_15m.parquet
|
+-- results/
    +-- signals_1m.parquet
    +-- signals_5m.parquet
    +-- signals_15m.parquet
    +-- trades_1m.parquet
    +-- trades_5m.parquet
    +-- trades_15m.parquet
```

------------------------------------------------------------------------

## 18. Why Parquet

Parquet is ideal for the initial research layer because it is:

-   columnar
-   compressed
-   fast
-   portable
-   easy to query
-   supported by Polars
-   supported by PyArrow
-   supported by DuckDB
-   compatible with Spark
-   suitable for later Snowflake ingestion

------------------------------------------------------------------------

## 19. Why DuckDB

DuckDB will provide local analytical SQL over Parquet.

Example research query:

``` sql
SELECT
    date_trunc('day', timestamp) AS trading_day,
    COUNT(*) AS candles,
    AVG(volume) AS avg_volume
FROM 'candles_1m.parquet'
GROUP BY 1
ORDER BY 1;
```

This allows rapid analysis without deploying a database server.

------------------------------------------------------------------------

## 20. Python Quant Engine

The quantitative engine is the core source of truth.

Suggested structure:

``` text
quant/
|
+-- data/
|   +-- dhan.py
|   +-- instruments.py
|   +-- validation.py
|
+-- candles/
|   +-- aggregation.py
|
+-- indicators/
|   +-- ema.py
|   +-- angle.py
|
+-- strategies/
|   +-- ema_9_15.py
|
+-- backtest/
|   +-- engine.py
|   +-- execution.py
|   +-- costs.py
|   +-- metrics.py
|
+-- research/
    +-- parameter_search.py
    +-- walk_forward.py
```

------------------------------------------------------------------------

## 21. Strategy Engine

The strategy engine will receive normalized candles and return
structured signals.

``` text
Candle
  ↓
EMA 9
  ↓
EMA 15
  ↓
Slope
  ↓
Angle
  ↓
Crossover
  ↓
BUY / SELL / HOLD
```

The LLM never calculates these values itself.

------------------------------------------------------------------------

## 22. EMA Calculation

For EMA period `N`:

``` text
alpha = 2 / (N + 1)
```

Initial values:

``` text
EMA 9:
alpha = 0.20

EMA 15:
alpha = 0.125
```

These are applied separately to 1m, 5m and 15m candle series.

------------------------------------------------------------------------

## 23. Angle Calculation

A chart's visual angle cannot be used directly because it depends on:

-   chart scaling
-   zoom
-   screen dimensions
-   price scale

Therefore the system needs a normalized mathematical definition.

Initial model:

``` text
normalized_slope =
    (EMA[t] - EMA[t-k]) / EMA[t-k]
```

Then:

``` text
angle =
    atan(normalized_slope × scale)
```

Parameters:

``` text
angle_threshold
angle_lookback
angle_scale
```

Initial target:

``` text
angle_threshold = 30°
```

The exact scale/normalization definition must be frozen before the final
benchmark.

This is one of the most important methodological decisions in the
project.

------------------------------------------------------------------------

## 24. Signal Rules

### BUY

``` text
9 EMA crosses above 15 EMA
AND
EMA angle >= +30°
```

### SELL

``` text
9 EMA crosses below 15 EMA
AND
EMA angle <= -30°
```

### HOLD

``` text
No qualifying crossover
```

------------------------------------------------------------------------

## 25. Crossover Detection

Bullish:

``` python
ema9 > ema15
AND previous_ema9 <= previous_ema15
```

Bearish:

``` python
ema9 < ema15
AND previous_ema9 >= previous_ema15
```

Signals are generated only after the candle closes.

------------------------------------------------------------------------

## 26. Execution Model

The backtester must avoid look-ahead bias.

If the signal occurs when candle `t` closes:

``` text
Candle t closes
      ↓
Signal generated
      ↓
Enter/exit at candle t+1 open
```

This applies independently to all timeframes.

Example:

``` text
1m:
signal at 09:30 close
entry at 09:31 open

5m:
signal at 09:30-09:35 close
entry at next 5m open

15m:
signal at 09:30-09:45 close
entry at next 15m open
```

------------------------------------------------------------------------

## 27. Exit Model

Initial baseline:

``` text
Long:
Exit when 9 EMA crosses below 15 EMA.

Short:
Exit when 9 EMA crosses above 15 EMA.
```

Stop-loss and take-profit systems will be added as separate experiments
rather than modifying the baseline silently.

------------------------------------------------------------------------

## 28. Futures Contract Handling

Futures have expiry dates.

The system must track:

``` text
security_id
trading_symbol
expiry
lot_size
tick_size
start_date
end_date
```

The initial research should test actual contracts rather than
immediately creating a synthetic continuous series.

Continuous futures can be introduced later with explicit rollover
methodology.

------------------------------------------------------------------------

## 29. Transaction Costs

A realistic backtest must calculate:

``` text
Gross P&L
    -
Brokerage
    -
Exchange charges
    -
GST
    -
SEBI charges
    -
Stamp duty
    -
Applicable STT
    -
Slippage
    =
Net P&L
```

The cost model will be configurable and must be updated according to the
applicable broker/exchange charges at implementation time.

------------------------------------------------------------------------

## 30. Slippage

The backtester will support configurable slippage.

Examples:

``` text
ideal
normal
stress
```

or:

``` text
entry_slippage_ticks
exit_slippage_ticks
```

The goal is to determine whether the strategy remains profitable under
realistic execution assumptions.

------------------------------------------------------------------------

## 31. Baseline Experiments

Three initial strategies will be compared.

### Strategy A --- EMA crossover

``` text
9 EMA crosses 15 EMA
```

### Strategy B --- EMA + angle

``` text
9 EMA crosses 15 EMA
AND ±30° filter
```

### Strategy C --- EMA + angle + trend filter

Potential example:

``` text
BUY:
9 EMA > 15 EMA
angle >= 30°
price > 15 EMA
```

The purpose is to determine whether the angle condition contributes
meaningful edge.

------------------------------------------------------------------------

## 32. Timeframe Experiment

The baseline strategy will be run separately:

``` text
1m
5m
15m
```

The final comparison will include:

  Metric                    1m    5m   15m
  ---------------------- ----- ----- -----
  Trades                   ---   ---   ---
  Win rate                 ---   ---   ---
  Gross P&L                ---   ---   ---
  Net P&L                  ---   ---   ---
  Profit factor            ---   ---   ---
  Maximum drawdown         ---   ---   ---
  Sharpe                   ---   ---   ---
  Sortino                  ---   ---   ---
  Average trade            ---   ---   ---
  Average holding time     ---   ---   ---

------------------------------------------------------------------------

## 33. Parameter Research

After the baseline is validated, parameters can be tested.

Potential fast EMA:

``` text
5
7
9
12
```

Potential slow EMA:

``` text
15
18
21
25
```

Angle:

``` text
20°
25°
30°
35°
40°
```

Angle lookback:

``` text
1
2
3
5
```

These experiments must not use the final test set.

------------------------------------------------------------------------

## 34. Train / Validation / Test

For the first July experiment:

``` text
July 2026
|
+------------------+-----------+-----------+
| Training         | Validation| Test      |
|                  |           |           |
| July 1-23        | July 24-27| July 28-31|
+------------------+-----------+-----------+
```

The exact boundaries should be based on actual trading sessions.

For a deterministic strategy, "training" means parameter calibration
rather than ML model training.

------------------------------------------------------------------------

## 35. Walk-Forward Validation

After the initial July research, expand to walk-forward evaluation.

Conceptually:

``` text
Historical window
       ↓
Calibrate parameters
       ↓
Next unseen period
       ↓
Evaluate
       ↓
Expand window
       ↓
Repeat
```

This is more reliable than selecting parameters using the full dataset.

------------------------------------------------------------------------

## 36. Performance Metrics

Minimum metrics:

``` text
Total trades
Winning trades
Losing trades
Win rate
Gross P&L
Net P&L
Average trade
Average winner
Average loser
Profit factor
Maximum drawdown
Average holding time
Longest losing streak
Longest winning streak
Sharpe ratio
Sortino ratio
```

Additional:

``` text
Calmar ratio
expectancy
daily P&L
monthly P&L
trade distribution
drawdown duration
```

------------------------------------------------------------------------

## 37. Research Report Generation

The agent should be able to produce a report containing:

``` text
Dataset
Instrument
Period
Timeframe

Strategy
EMA settings
Angle definition
Entry
Exit

Execution assumptions
Transaction costs
Slippage

Performance
P&L
Win rate
Profit factor
Drawdown
Sharpe
Sortino

Observations
Failure cases
Potential improvements
```

The report should distinguish:

-   actual measured results
-   assumptions
-   hypotheses
-   recommendations

The agent must never fabricate missing metrics.

------------------------------------------------------------------------

## 38. Agent Safety Model

The AI agent must not have unrestricted access to trading actions.

Initial permissions:

``` text
READ:
Market data
Historical data
Portfolio metadata

WRITE:
Research datasets
Backtest results

NO LIVE ORDERS
```

Later:

``` text
Signal
  ↓
Risk Engine
  ↓
Human Approval
  ↓
Order
```

The system should never allow the LLM to bypass the risk engine.

------------------------------------------------------------------------

## 39. Risk Engine

Before any future live order:

``` text
Signal
  ↓
Position check
  ↓
Maximum position check
  ↓
Daily loss check
  ↓
Trade frequency check
  ↓
Market hours check
  ↓
Duplicate order check
  ↓
Order validation
  ↓
Human approval
  ↓
Execution
```

Risk controls should include:

-   maximum position size
-   maximum daily loss
-   maximum trades/day
-   maximum consecutive losses
-   emergency kill switch
-   duplicate-order protection
-   position reconciliation
-   order-status reconciliation

------------------------------------------------------------------------

## 40. Paper Trading

Before live execution:

``` text
Live Dhan Feed
      ↓
Strategy
      ↓
Risk Engine
      ↓
Simulated Execution
      ↓
Paper Portfolio
```

Track:

``` text
signal timestamp
expected entry
simulated fill
slippage
exit
P&L
latency
```

Paper trading must reproduce the same strategy code used by the
backtester.

------------------------------------------------------------------------

## 41. Real-Time Architecture

Once the historical system is validated:

``` text
Dhan WebSocket
      ↓
Market Data Ingestion
      ↓
Kafka
      ↓
Real-Time Candle Builder
      ↓
Feature Engine
      ↓
EMA 9 / EMA 15
      ↓
Angle
      ↓
Signal Engine
      ↓
Risk Engine
      ↓
Paper Trading
```

Kafka should be introduced only when the real-time data
volume/architecture justifies it.

------------------------------------------------------------------------

## 42. Why Kafka Later

The first July dataset is too small to require Kafka.

Initially:

``` text
Dhan
 ↓
Python
 ↓
Parquet
```

Later:

``` text
Dhan
 ↓
Kafka
 ├── Strategy
 ├── Storage
 ├── Monitoring
 └── Analytics
```

Kafka becomes useful for:

-   event replay
-   decoupled consumers
-   real-time processing
-   buffering
-   scalable ingestion
-   multiple strategy consumers

------------------------------------------------------------------------

## 43. Snowflake Architecture

Snowflake will be the long-term historical and analytical warehouse.

It should not be the low-latency execution path.

Recommended:

``` text
Dhan
 |
 +----> Kafka ----> Real-time Strategy
 |
 +----> Snowflake
           |
           +---- Historical Research
           +---- Analytics
           +---- ML Dataset
           +---- Reporting
```

------------------------------------------------------------------------

## 44. Snowflake Data Model

Potential schema:

``` text
TRADING_PLATFORM
|
+-- RAW
|   +-- FUTURES_CANDLES
|   +-- MARKET_TICKS
|   +-- MARKET_DEPTH
|
+-- MARKET
|   +-- CANDLES_1M
|   +-- CANDLES_5M
|   +-- CANDLES_15M
|
+-- FEATURES
|   +-- PRICE_FEATURES
|   +-- VOLUME_FEATURES
|   +-- FUTURES_FEATURES
|   +-- ORDERBOOK_FEATURES
|
+-- STRATEGY
|   +-- STRATEGY_CONFIGS
|   +-- SIGNALS
|   +-- BACKTESTS
|   +-- PERFORMANCE
|
+-- EXECUTION
    +-- ORDERS
    +-- FILLS
    +-- POSITIONS
```

------------------------------------------------------------------------

## 45. AI + Snowflake

Eventually the agent can expose tools such as:

``` text
query_snowflake()
find_market_periods()
compare_regimes()
get_strategy_results()
get_historical_features()
```

Example:

> "Find the last five periods where NIFTY had similar volatility to
> July."

The agent could:

``` text
query Snowflake
      ↓
retrieve historical periods
      ↓
run quantitative comparison
      ↓
summarize results
```

------------------------------------------------------------------------

## 46. Machine Learning Roadmap

Machine learning is intentionally delayed.

First establish:

``` text
Deterministic Strategy
       ↓
Backtest
       ↓
Robustness
       ↓
Out-of-sample validation
```

Only then introduce ML.

Potential architecture:

``` text
EMA Strategy
      ↓
Candidate Signal
      ↓
ML Model
      ↓
Probability
      ↓
Signal Filter
      ↓
Risk Engine
```

Example:

``` text
EMA says BUY
ML probability = 0.82
       ↓
Trade allowed
```

versus:

``` text
EMA says BUY
ML probability = 0.41
       ↓
Trade rejected
```

ML should enhance a proven strategy rather than replace the research
baseline.

------------------------------------------------------------------------

## 47. Future ML Features

Potential features:

``` text
EMA distance
EMA slope
EMA angle
returns
momentum
ATR
volatility
volume
relative volume
OI
OI change
price/OI relationship
India VIX
NIFTY spot/futures basis
market breadth
```

Later, if live depth data is available:

``` text
bid/ask spread
bid/ask imbalance
top-5 depth
top-20 depth
depth imbalance
```

------------------------------------------------------------------------

## 48. Options Roadmap

Options are not part of the initial project.

Later:

``` text
NIFTY Signal
    |
    +----> Futures
    |
    +----> Options
```

The options phase would require:

-   historical option contracts
-   expiry mapping
-   strike selection
-   IV
-   Greeks
-   spread
-   liquidity
-   slippage
-   option-specific risk

This should be treated as a separate research module.

------------------------------------------------------------------------

## 49. Frontend

The frontend will be built with:

``` text
Next.js
TypeScript
Tailwind
shadcn/ui
```

Main interface:

### AI Research Chat

``` text
"Backtest NIFTY EMA strategy for July."
```

### Market Data Explorer

``` text
Instrument
Date
Timeframe
OHLC
Volume
OI
```

### Strategy Builder

``` text
Fast EMA: 9
Slow EMA: 15
Angle: 30°
Timeframe: 5m
```

### Backtest Dashboard

``` text
P&L
Drawdown
Win rate
Profit factor
Sharpe
Trades
```

### Charts

``` text
Candles
EMA 9
EMA 15
Signals
Equity curve
Drawdown
Trade distribution
```

### Experiment Comparison

``` text
1m vs 5m vs 15m
20° vs 25° vs 30° vs 35°
```

------------------------------------------------------------------------

## 50. Suggested UI

``` text
+--------------------------------------------------------+
| Quant Research Agent                     NIFTY Futures |
+--------------------------------------------------------+
|                                                        |
| Chat                                                   |
|                                                        |
| User: Backtest 9/15 EMA at 30° for July               |
|                                                        |
| Agent:                                                 |
| ✓ Found futures contract                               |
| ✓ Loaded dataset                                       |
| ✓ Validated candles                                    |
| ✓ Ran 1m                                               |
| ✓ Ran 5m                                               |
| ✓ Ran 15m                                              |
|                                                        |
+--------------------+-----------------------------------+
| Strategy           | Results                           |
|                    |                                   |
| EMA 9 / 15         | 1m   5m   15m                    |
| Angle 30°          | P&L  P&L  P&L                    |
|                    | DD   DD   DD                     |
+--------------------+-----------------------------------+
```

------------------------------------------------------------------------

## 51. Observability

The system should record:

``` text
agent request
tool call
tool arguments
tool result
strategy configuration
dataset version
backtest configuration
model/provider
execution time
errors
```

This makes every experiment reproducible.

A backtest result should be tied to:

``` text
dataset_hash
strategy_version
parameter_config
cost_model_version
engine_version
```

------------------------------------------------------------------------

## 52. Reproducibility

Every experiment should have an experiment ID.

Example:

``` text
EXP-2026-0001
```

Configuration:

``` json
{
  "instrument": "NIFTY_FUT",
  "period": "2026-07",
  "timeframes": ["1m", "5m", "15m"],
  "fast_ema": 9,
  "slow_ema": 15,
  "angle": 30,
  "execution": "next_open",
  "cost_model": "india_futures_v1"
}
```

The exact same experiment should be rerunnable.

------------------------------------------------------------------------

## 53. Data Versioning

Datasets should have versions.

Example:

``` text
nifty_futures_july_2026_v1
nifty_futures_july_2026_v2
```

If a data correction happens, the original result remains traceable.

------------------------------------------------------------------------

## 54. Testing Strategy

### Unit tests

Test:

``` text
EMA
angle
crossover
signals
position management
P&L
fees
slippage
```

### Integration tests

Test:

``` text
Dhan API
instrument resolution
data download
Parquet storage
MCP tools
agent workflows
```

### Backtest regression tests

Known historical datasets should produce known outputs.

Example:

``` text
dataset X
strategy config Y
expected trade count Z
```

If code changes alter results unexpectedly, the regression test catches
it.

------------------------------------------------------------------------

## 55. Agent Evaluations

The agent itself should also be tested.

Example:

``` text
Prompt:
"Backtest NIFTY 9/15 EMA at 30° for July."

Expected:
- Correct instrument
- Correct dataset
- Correct timeframe
- Correct strategy
- No look-ahead bias
- Correct execution assumption
- Costs included
- Metrics reported
```

Agent evaluation should detect:

-   hallucinated data
-   incorrect tool selection
-   incorrect strategy interpretation
-   missing assumptions
-   unsupported claims

------------------------------------------------------------------------

## 56. Security

Secrets must never be committed.

Use environment variables or secrets management for:

``` text
DHAN_CLIENT_ID
DHAN_ACCESS_TOKEN
SNOWFLAKE credentials
LLM API keys
```

The agent should not expose secrets through tool outputs.

------------------------------------------------------------------------

## 57. Permission Model

Separate permissions:

``` text
READ_MARKET_DATA
READ_PORTFOLIO
RUN_RESEARCH
WRITE_DATASET
RUN_BACKTEST
PAPER_TRADE
REQUEST_LIVE_ORDER
EXECUTE_LIVE_ORDER
```

Initial deployment:

``` text
READ_MARKET_DATA = YES
RUN_RESEARCH = YES
RUN_BACKTEST = YES
PAPER_TRADE = YES
LIVE_ORDER = NO
```

Live execution is enabled only after explicit approval and risk
controls.

------------------------------------------------------------------------

## 58. Technology Stack

### Frontend

``` text
Next.js
TypeScript
Tailwind CSS
shadcn/ui
```

### Agent

``` text
Eve
Vercel AI SDK
```

### Tool Protocol

``` text
MCP
```

### Broker

``` text
DhanHQ
```

### Quant

``` text
Python
Polars
NumPy
PyArrow
DuckDB
```

### Data

``` text
Parquet
```

### Warehouse

``` text
Snowflake
```

### Streaming

``` text
Kafka
```

### API

``` text
FastAPI
```

### Testing

``` text
pytest
```

### Future ML

``` text
scikit-learn
XGBoost
PyTorch
```

------------------------------------------------------------------------

## 59. Repository Structure

``` text
indian-trading-agent/
|
+-- apps/
|   +-- web/
|       +-- app/
|       +-- components/
|       +-- lib/
|
+-- agent/
|   +-- instructions.md
|   +-- tools/
|   +-- skills/
|   +-- subagents/
|   +-- evals/
|
+-- mcp/
|   +-- quant-server/
|
+-- quant/
|   +-- data/
|   |   +-- dhan.py
|   |   +-- instruments.py
|   |   +-- validation.py
|   |
|   +-- candles/
|   |   +-- aggregation.py
|   |
|   +-- indicators/
|   |   +-- ema.py
|   |   +-- angle.py
|   |
|   +-- strategies/
|   |   +-- ema_9_15.py
|   |
|   +-- backtest/
|   |   +-- engine.py
|   |   +-- execution.py
|   |   +-- costs.py
|   |   +-- metrics.py
|   |
|   +-- research/
|       +-- parameter_search.py
|       +-- walk_forward.py
|
+-- data/
|   +-- raw/
|   +-- processed/
|   +-- results/
|
+-- tests/
|
+-- notebooks/
|
+-- docs/
|
+-- .env.example
+-- pyproject.toml
+-- README.md
```

------------------------------------------------------------------------

## 60. Implementation Phases

### Phase 0 --- Project Foundation

Tasks:

-   create repository
-   configure Python environment
-   configure Next.js
-   configure Eve
-   configure environment variables
-   create initial quant package
-   create test framework

Deliverable:

``` text
Empty but runnable project
```

### Phase 1 --- DhanHQ Data Acquisition

Tasks:

-   Dhan authentication
-   download instrument master
-   resolve NIFTY Futures
-   identify July contract(s)
-   download July 2026 1-minute candles
-   normalize data
-   save Parquet

Deliverable:

``` text
July NIFTY Futures 1m dataset
```

### Phase 2 --- Data Validation

Tasks:

-   timestamp validation
-   duplicate detection
-   missing candles
-   OHLC validation
-   volume validation
-   OI validation
-   contract metadata validation

Deliverable:

``` text
Validated canonical dataset
```

### Phase 3 --- Candle Processing

Tasks:

-   build 5m candles
-   build 15m candles
-   verify boundaries
-   compare against provider data where possible

Deliverable:

``` text
1m
5m
15m
```

datasets.

### Phase 4 --- Strategy Engine

Tasks:

-   EMA 9
-   EMA 15
-   angle calculation
-   crossover detection
-   BUY/SELL signals
-   strategy configuration

Deliverable:

``` text
Deterministic signal engine
```

### Phase 5 --- Backtester

Tasks:

-   positions
-   entries
-   exits
-   next-candle execution
-   lot size
-   costs
-   slippage
-   P&L
-   metrics

Deliverable:

``` text
Reproducible backtest engine
```

### Phase 6 --- Baseline Results

Run:

``` text
1m
5m
15m
```

with:

``` text
EMA 9
EMA 15
Angle ±30°
```

Deliverable:

``` text
Baseline comparison report
```

### Phase 7 --- Eve Agent

Create tools:

``` text
get_futures_contract
get_historical_data
validate_dataset
run_backtest
compare_timeframes
```

Deliverable:

Natural-language research workflow.

Example:

``` text
"Backtest NIFTY strategy for July."
```

### Phase 8 --- Advanced Research

Add:

``` text
parameter_search
walk_forward_test
regime_analysis
```

Deliverable:

Robustness report.

### Phase 9 --- Snowflake

Tasks:

-   warehouse design
-   schema
-   ingestion
-   dataset versioning
-   experiment storage
-   analytical queries

Deliverable:

Long-term research warehouse.

### Phase 10 --- Real-Time Data

Tasks:

-   Dhan WebSocket
-   authentication
-   subscriptions
-   reconnect handling
-   message normalization
-   real-time candle builder

Deliverable:

Live market-data pipeline.

### Phase 11 --- Kafka

Tasks:

-   event schema
-   topics
-   producer
-   consumer
-   replay
-   monitoring

Deliverable:

Scalable event-driven market-data architecture.

### Phase 12 --- Paper Trading

Tasks:

-   live signals
-   simulated execution
-   slippage
-   position state
-   P&L
-   monitoring

Deliverable:

Real-time paper-trading system.

### Phase 13 --- Risk Engine

Tasks:

-   position limits
-   daily loss
-   trade limits
-   kill switch
-   reconciliation

Deliverable:

Production risk layer.

### Phase 14 --- Human-Approved Live Trading

Only after extensive paper testing:

``` text
Signal
 ↓
Risk
 ↓
Approval
 ↓
Dhan
```

Deliverable:

Controlled live execution.

------------------------------------------------------------------------

## 61. Initial Milestone

The first milestone is:

> A user can ask the AI agent to retrieve July 2026 NIFTY Futures data
> and run the 9/15 EMA + 30° strategy on 1m, 5m and 15m, with
> reproducible results.

Expected workflow:

``` text
User:
"Backtest my NIFTY strategy for July."

Agent:
✓ Resolve futures contract
✓ Retrieve data
✓ Validate dataset
✓ Generate 5m
✓ Generate 15m
✓ Calculate EMA
✓ Calculate angle
✓ Generate signals
✓ Run 1m
✓ Run 5m
✓ Run 15m
✓ Calculate metrics
✓ Compare results
✓ Generate report
```

------------------------------------------------------------------------

## 62. Definition of Done for Phase 1

Phase 1 is complete when:

-   Dhan authentication works
-   correct NIFTY Futures contract is identified
-   July 2026 data is downloaded
-   data is stored as Parquet
-   validation passes
-   1m dataset is reproducible
-   5m and 15m datasets can be generated
-   no duplicate candles exist
-   timestamps are correct
-   OI is present where expected
-   contract metadata is stored

------------------------------------------------------------------------

## 63. Definition of Done for Baseline Strategy

The baseline is complete when:

-   EMA 9 works
-   EMA 15 works
-   angle calculation is mathematically documented
-   crossover detection works
-   signals are reproducible
-   entries use next-candle execution
-   exits are deterministic
-   costs are included
-   slippage is configurable
-   1m results exist
-   5m results exist
-   15m results exist
-   comparison report exists

------------------------------------------------------------------------

## 64. Definition of Done for AI Research Layer

The AI layer is complete when the user can say:

``` text
"Run the NIFTY EMA strategy for July."
```

and the agent can:

``` text
resolve instrument
fetch/check data
validate
run backtests
compare timeframes
report assumptions
return results
```

without manually writing code.

------------------------------------------------------------------------

## 65. Key Engineering Principles

### Principle 1 --- AI is not the source of truth

LLMs orchestrate.

Python calculates.

### Principle 2 --- Backtests must be reproducible

Same dataset + same config = same result.

### Principle 3 --- No look-ahead bias

Signals are generated after candle close.

Execution happens at the next available candle.

### Principle 4 --- Separate strategy from execution

``` text
Strategy
≠
Broker
```

### Principle 5 --- Separate broker from data model

``` text
Dhan
↓
Adapter
↓
Internal Candle
```

### Principle 6 --- Separate research from live trading

``` text
Backtest
≠
Paper trade
≠
Live trade
```

### Principle 7 --- Introduce complexity only when needed

Start:

``` text
Dhan
 ↓
Parquet
 ↓
Python
 ↓
Backtest
```

Then:

``` text
Eve
 ↓
MCP
```

Then:

``` text
Snowflake
```

Then:

``` text
WebSocket
```

Then:

``` text
Kafka
```

Then:

``` text
Paper trading
```

Then:

``` text
Live execution
```

------------------------------------------------------------------------

## 66. Final Architecture

``` text
                                  USER
                                    |
                                    v
                           +----------------+
                           |    Next.js     |
                           |   Dashboard    |
                           +-------+--------+
                                   |
                              Eve / AI SDK
                                   |
                                   v
                         +---------------------+
                         |    RESEARCH AGENT   |
                         |        EVE          |
                         +----------+----------+
                                    |
                              MCP / Tools
                                    |
              +---------------------+---------------------+
              |                     |                     |
              v                     v                     v
        +-----------+         +-----------+         +-----------+
        | Data      |         | Strategy  |         | Research  |
        | Tools     |         | Tools     |         | Tools     |
        +-----+-----+         +-----+-----+         +-----+-----+
              |                     |                     |
              v                     v                     v
           DhanHQ              Python Quant           Backtester
              |                     |                     |
              v                     v                     v
       Historical/Live         EMA/Angle/Signal      Metrics/Tests
              |                     |                     |
              +---------------------+---------------------+
                                    |
                                    v
                           +----------------+
                           | Parquet/DuckDB |
                           +-------+--------+
                                   |
                                   v
                              Snowflake
                                   |
                                   v
                         Historical Research


Future live path:

Dhan WebSocket
      |
      v
    Kafka
      |
      v
Real-Time Feature Engine
      |
      v
 Strategy Engine
      |
      v
 Risk Engine
      |
      v
Human Approval
      |
      v
 Dhan Execution
```

------------------------------------------------------------------------

## 67. Expected Final Product

The final system should behave like an **AI quantitative research
workstation**.

A user should be able to ask:

``` text
"Get July NIFTY futures data."

"Backtest my 9/15 EMA strategy."

"Compare 1m, 5m and 15m."

"Test 20°, 25°, 30°, 35° and 40°."

"Run walk-forward validation."

"Show me where the strategy loses most."

"Compare performance during high and low volatility."

"Store the results."

"Start paper trading the best validated configuration."
```

The agent handles orchestration.

The quantitative engine handles mathematics.

Dhan handles market data and eventual execution.

Snowflake handles long-term research data.

Kafka handles future real-time event distribution.

The frontend makes the whole system usable.

------------------------------------------------------------------------

## 68. Project Outcome

If implemented successfully, the project will demonstrate experience
across:

``` text
Quantitative Finance
       +
Algorithmic Trading
       +
Financial Data Engineering
       +
AI Agents
       +
MCP
       +
Next.js
       +
Python
       +
Real-Time Systems
       +
Kafka
       +
Snowflake
       +
Backtesting
       +
Risk Management
```

More importantly, it will produce a research platform where strategy
decisions are:

-   measurable
-   reproducible
-   explainable
-   testable
-   auditable
-   extensible

rather than simply relying on an AI model to make trading decisions.

------------------------------------------------------------------------

## 69. Immediate Next Action

The immediate next action is **not** to build the complete agent.

Start with the smallest valuable pipeline:

``` text
DhanHQ
   ↓
NIFTY Futures instrument discovery
   ↓
July 2026 1m historical data
   ↓
Validation
   ↓
Parquet
```

Then:

``` text
1m
 ↓
5m / 15m
 ↓
EMA 9 / 15
 ↓
Angle
 ↓
Signals
 ↓
Backtest
```

Only after this works should the Eve agent be connected to the
quantitative engine.

This ordering keeps the project technically manageable and ensures that
the AI layer is built around a working quantitative foundation rather
than hiding problems inside an agent.

------------------------------------------------------------------------

## 70. Final Initial Configuration

``` text
Project:
AI Quantitative Trading Research Platform

Broker:
DhanHQ

Instrument:
NIFTY Futures

Initial period:
July 2026

Canonical data:
1-minute

Derived resolutions:
5-minute
15-minute

Strategy:
EMA 9 / EMA 15

Angle:
±30°

Entry:
Crossover + angle confirmation

Exit:
Opposite crossover

Execution assumption:
Next candle open

Costs:
Brokerage + applicable exchange/regulatory charges + slippage

Agent:
Eve

Tool protocol:
MCP

Quant engine:
Python

Local storage:
Parquet + DuckDB

Future warehouse:
Snowflake

Future streaming:
Kafka

Future ML:
XGBoost / scikit-learn / PyTorch

Options:
Future phase

Live trading:
Future phase, after paper trading and risk validation
```

------------------------------------------------------------------------

## 71. Conclusion

The project is designed as a layered system rather than a single trading
bot.

The most important architectural decision is the separation:

``` text
AI Agent
   |
   v
Orchestration
   |
   v
Tools
   |
   v
Deterministic Quant Engine
   |
   +---- Data
   +---- Indicators
   +---- Strategy
   +---- Backtesting
   +---- Risk
```

This allows the project to start small with a July 2026 NIFTY Futures
backtest while retaining a clear path toward a production-grade
AI-native trading platform.

The first goal is therefore simple:

> **Build a trustworthy NIFTY Futures historical-data and backtesting
> engine.**

Everything else --- Eve, MCP, Snowflake, Kafka, real-time trading and ML
--- should be layered on top of that foundation.
