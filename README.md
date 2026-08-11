# AI Quant Trading Platform

AI-powered quantitative research and algorithmic trading platform for
Indian Equity Derivatives (NIFTY Futures).

## Stack

| Layer | Tech |
|-------|------|
| Quant engine | Python (Polars, DuckDB, PyArrow, NumPy) — `quant/` |
| Agent / orchestration | Eve — `agent/` (Phase 07) |
| Tool protocol | MCP — `mcp/quant-server/` (Phase 07) |
| Frontend | Next.js + TypeScript + Tailwind — `apps/web/` |
| Broker / data | DhanHQ |
| Local storage | Parquet (`data/raw`, `data/processed`, `data/results`) + DuckDB |
| Warehouse (future) | Snowflake (Phase 09) |
| Streaming (future) | Kafka (Phase 11) |

## Getting started

```bash
# Python environment (uv)
uv sync

# Run tests
uv run pytest

# Import check
uv run python -c "import quant"

# Frontend (eve chat + dashboard)
cd apps/web
npm install

# 1. Serve the quant engine over HTTP (eve connects to it as an MCP server)
#    in the repo root:
uv run python -m mcp.quant_server.server --transport http --port 8010

# 2. Run the app (boots the eve agent + chat UI on http://localhost:3000)
npm run dev
```

Ask the chat things like *"Backtest August 2026 on 5m"* or *"Which recorded
configs beat the baseline?"*. Every run is recorded into the experiment
vault (`data/vault/experiments.db`) and can be revisited with `vault_query`.

## Telegram signal alerts

```bash
# needs .env: TELEGRAM_BOT_TOKEN + TELEGRAM_CHAT_ID
uv run python scripts/telegram_alerts.py --once           # single check
uv run python scripts/telegram_alerts.py --interval 300   # poll loop
uv run python scripts/telegram_alerts.py --no-send        # dry run
```

## Environment variables

Copy `.env.example` to `.env` and fill in credentials
(DhanHQ client ID + access token). Never commit `.env`.

## Architecture principle

- **AI orchestrates; Python calculates.**
- The LLM never performs financial calculations, backtesting or P&L.
- The quant engine (`quant/`) is the deterministic source of truth.

## Phases

Step-by-step implementation knowledge: see `docs/phases/`.