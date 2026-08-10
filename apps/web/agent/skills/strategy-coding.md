---
description: Use when a user wants to create a new trading strategy, asks Eve to code a strategy, or wants to modify the existing strategy logic.
---

# Custom Strategy Implementation

## How to implement a user-defined strategy

1. **Clarify** entry/exit rules, indicators, timeframe, and risk parameters.
2. **Design** the Python implementation following the existing pattern in `quant/strategies/`.
3. **Write** the code with `write_file` tool — strategies must use polars, not pandas.
4. **Validate** by running a backtest via the quant connection.

## Strategy file requirements

- Location: `quant/strategies/<strategy_name>.py`
- Must define a `StrategyConfig` (pydantic BaseModel with all parameters)
- Must define `generate_signals(candles, config, timeframe)` returning a DataFrame
- Signal column must be named `signal_type` with values `BUY`, `SELL`, or `HOLD`
- Use polars vectorized expressions — no Python loops over rows, no pandas

## Available indicators in polars

- **EMA**: `pl.col("close").ewm_mean(span=N, adjust=False)`
- **SMA**: `pl.col("close").rolling_mean(window_size=N)`
- **RSI**: compute gain/loss ewm_mean then 100 - (100 / (1 + gain/loss))
- **Bollinger**: rolling_mean ± k * rolling_std
- **VWAP**: cumulative (close * volume) / cumulative volume
- **Crossover**: compare current bar vs previous bar values with `.shift(1)`

## Adding to MCP server (optional)

If the strategy needs new tools exposed, import it in `mcp/quant_server/server.py`
and add the handler to `_TOOL_FUNCTIONS`. Then restart the MCP server.
