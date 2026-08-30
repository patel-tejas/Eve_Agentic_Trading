# AI Quant Trading Platform

AI-powered quantitative research and algorithmic trading platform for
Indian Equity Derivatives (NIFTY Futures).

## Stack

| Layer | Tech |
|-------|------|
| Quant engine | Python (Polars, DuckDB, PyArrow, NumPy) — `quant/` |
| Agent / orchestration | Groq (Llama) via AI SDK — `apps/web/app/api/chat/` |
| Tool protocol | MCP — `mcp/quant_server/server.py` (Phase 07) |
| Tool transport (web) | HTTP bridge — `mcp/quant_server/http_bridge.py` (Phase 07b) |
| Frontend | Next.js 16 + TypeScript + Tailwind — `apps/web/` |
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

# Frontend chat (two terminals)
#   1. the deterministic engine, exposed over HTTP:
uv run python -m mcp.quant_server.http_bridge      # http://127.0.0.1:8010

#   2. the web app:
cd apps/web
cp .env.example .env.local     # then add your GROQ_API_KEY
npm install
npm run dev                    # http://localhost:3000
```

## Chat frontend

`apps/web` is a chat over the quant engine. You ask in plain English; the
model calls the deterministic Python tools and reports what they return.

- **Tool definitions are generated**, not hand-written: the bridge derives
  JSON Schema from each Python signature and serves it at `GET /tools`, so a
  tool added in `mcp/quant_server/server.py` appears in the chat with no
  TypeScript change.
- **Tool calls are shown, not hidden.** Every call renders as an expandable
  card with its input and raw JSON output, so any number in an answer can be
  traced to the computation that produced it.
- **Path arguments are never model-controllable** — `processed_root` and
  friends are stripped from the published schema.
- The header shows whether the engine is reachable and whether a model key is
  configured, so a failure is legible before you type a question.

## Environment variables

Copy `.env.example` to `.env` and fill in credentials
(DhanHQ client ID + access token). Never commit `.env`.

## Architecture principle

- **AI orchestrates; Python calculates.**
- The LLM never performs financial calculations, backtesting or P&L.
- The quant engine (`quant/`) is the deterministic source of truth.

## Phases

Step-by-step implementation knowledge: see `docs/phases/`.