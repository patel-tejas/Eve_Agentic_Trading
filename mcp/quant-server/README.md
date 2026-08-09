# quant-server (MCP)

MCP server exposing the quant engine (`quant/`) as tools for the agent.
**Skeleton only — implemented in Phase 07.**

Candidate tools (proposal §14): get_futures_contract, get_historical_candles,
validate_dataset, calculate_ema, calculate_ema_angle, generate_signal,
run_backtest, calculate_metrics, compare_timeframes, parameter_search,
walk_forward_test.

The server is a thin boundary: it validates arguments, calls `quant/`,
and returns structured results. No financial logic lives here.