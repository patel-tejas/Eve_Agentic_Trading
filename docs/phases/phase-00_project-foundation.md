# Phase 00 — Project Foundation

## Goal

Set up the project skeleton: repository, Python environment, Next.js frontend, Eve agent config, environment variables, and test framework.

## What We're Building

An empty but runnable project with all tooling in place. No business logic — just the scaffolding so that subsequent phases can drop in code without fighting project config.

## Deliverables

- Monorepo with `apps/web/` (Next.js), `quant/` (Python), `agent/` (Eve), `mcp/` (MCP server)
- Python environment with `pyproject.toml`, `pytest`, `polars`, `duckdb`, `pyarrow`, `numpy`, `fastapi`
- Next.js app with TypeScript, Tailwind, shadcn/ui
- `.env.example` with all required secrets listed
- Empty but importable `quant/` package structure
- Initial test suite that passes (`pytest` runs clean)

## Key Concepts

### Monorepo Layout

```
indian-trading-agent/
├── apps/web/           ← Next.js frontend
│   ├── app/
│   ├── components/
│   └── lib/
├── agent/              ← Eve agent runtime
│   ├── instructions.md
│   ├── tools/
│   ├── skills/
│   ├── subagents/
│   └── evals/
├── mcp/
│   └── quant-server/   ← MCP tool server (Python)
├── quant/              ← Python quant engine
│   ├── data/
│   ├── candles/
│   ├── indicators/
│   ├── strategies/
│   ├── backtest/
│   └── research/
├── data/
│   ├── raw/
│   ├── processed/
│   └── results/
├── tests/
├── notebooks/
├── docs/
├── .env.example
├── pyproject.toml
└── README.md
```

### Python Package Structure

The `quant/` package should be installable as a local package:

```toml
# pyproject.toml
[project]
name = "quant-engine"
version = "0.1.0"
requires-python = ">=3.11"
dependencies = [
    "polars>=0.20",
    "duckdb>=0.10",
    "pyarrow>=15.0",
    "numpy>=1.26",
    "fastapi>=0.110",
    "httpx>=0.27",
    "pydantic>=2.5",
]
```

### Environment Variables

```
DHAN_CLIENT_ID=
DHAN_ACCESS_TOKEN=
DHAN_ENV=          # PROD or UAT
SNOWFLAKE_ACCOUNT=
SNOWFLAKE_USER=
SNOWFLAKE_PASSWORD=
SNOWFLAKE_DATABASE=
LLM_API_KEY=
```

### Next.js Stack

- `create-next-app` with TypeScript + Tailwind + App Router
- shadcn/ui for component library
- `next.config.js` with API route proxy if needed

## Tech References

| Tool | Purpose | Reference |
|------|---------|-----------|
| Polars | DataFrame engine (10-100x faster than Pandas) | `polars.pola.rs` |
| DuckDB | Local analytical SQL over Parquet | `duckdb.org` |
| PyArrow | Parquet I/O, columnar format | `arrow.apache.org` |
| FastAPI | API layer for MCP server | `fastapi.tiangolo.com` |
| Eve | Agent runtime with MCP, skills, subagents | Eve docs |
| MCP | Model Context Protocol for tool boundaries | `modelcontextprotocol.io` |
| Next.js | Frontend framework | `nextjs.org` |
| shadcn/ui | UI components | `ui.shadcn.com` |

## Data Contracts

None yet — this phase only creates the skeleton.

## Dependencies

- Python 3.11+
- Node.js 20+
- DhanHQ account (credentials for `.env`)
- Eve runtime (if available)

## Definition of Done

- [ ] Repository initialized with `.gitignore`
- [ ] `pyproject.toml` with all dependencies installable
- [ ] `pytest` runs and passes (0 tests, clean exit)
- [ ] `quant/` package importable (`python -c "import quant"`)
- [ ] Next.js dev server starts on `localhost:3000`
- [ ] `.env.example` lists all required secrets
- [ ] README with setup instructions

## Open Questions

- Monorepo tool: Turborepo vs Nx vs plain?
- Python virtual env: venv vs conda vs poetry?
- Should `mcp/quant-server/` be a separate package or part of `quant/`?
- Does Eve require a specific project structure?
