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

# Frontend (optional, Phase 49+)
cd apps/web
npm install
npm run dev
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