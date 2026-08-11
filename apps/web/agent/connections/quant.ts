import { defineMcpClientConnection } from "eve/connections";

/**
 * The deterministic quant engine, exposed as an MCP server.
 *
 * Start it before using the agent:
 *     uv run python -m mcp.quant_server.server --transport http --port 8010
 */
export default defineMcpClientConnection({
  url: process.env.QUANT_MCP_URL ?? "http://127.0.0.1:8010/mcp",
  description:
    "Deterministic quant research engine: processed month data (list_research_months, get_historical_candles), data pipeline (download_month_data, validate_dataset, process_month_data), the EMA 9/15+angle strategy (generate_signal, run_backtest_signals), baseline variant comparisons (compare_timeframes), advanced research (parameter_search, walk_forward_test), and the experiment vault of past runs (vault_query). Every tool is deterministic given the same inputs; the agent orchestrates, the engine calculates.",
  tools: {
    allow: [
      "list_research_months",
      "get_historical_candles",
      "download_month_data",
      "validate_dataset",
      "process_month_data",
      "generate_signal",
      "run_backtest_signals",
      "compare_timeframes",
      "parameter_search",
      "walk_forward_test",
      "vault_query",
    ],
  },
});