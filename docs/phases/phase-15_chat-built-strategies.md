# Phase 15 — Strategies Built in Chat

## Goal

Let a trader describe a strategy in plain English, in Hisaab's Eve chat or by
filling in a form, and get rules the engine can test honestly, saved to their
account, versioned, evaluated on data they did not tune on, and paper traded.

## What was built

| Part | Where |
|---|---|
| P0 common gate: policy tiers, auth, validation, rate limits, audit | `mcp/quant_server/gate.py`, `policy.py`, `auth.py`, `audit.py` |
| P1 `eve.strategy/1` spec, new indicators, compiler, stateless tools | `quant/strategies/spec/`, `quant/indicators/`, `strategy_tools.py` |
| P2 saved strategies, immutable versions, recorded backtests | `store.py`, `store_tools.py`; Hisaab `supabase_schema.sql` (`algo_*`) |
| P3 Hisaab builder: chat and form on one spec | Hisaab `app/dashboard/strategies`, `components/strategy-builder` |
| P4 honest verdict | `quant/strategies/spec/evaluation.py`, `evaluate_saved_strategy` |
| P5 paper trading and kill switch | `paper_tools.py` |

## Design rules

- **The model fills a form; it never writes code.** A spec is typed data
  with closed vocabularies. `rule_spec` interprets it with the same engine,
  costs and fills as every other strategy. Offsets are bars back and must be
  `>= 0`, so look-ahead cannot be expressed.
- **What the user reads is what runs.** The summary is rendered from the spec
  by code (`describe.py`, mirrored in Hisaab and pinned by
  `npm run verify:spec`), never written by the model.
- **Every try counts.** Each new version and each recorded backtest raises the
  strategy's trial count; the verdict deflates the Sharpe ratio by it.
- **The holdout is used once.** A month the strategy was backtested on is
  refused as a holdout; one reused by a later version is flagged.
- **Stopping is easy, starting is deliberate.** Eve may engage the kill
  switch; releasing it, promoting to paper and archiving are UI-only.
- **No live trading.** No tool is in the `trade_live` tier, the status enum
  has no `live` value, and broker tokens never enter the model's context.

## Verdict labels

`too_few_trades` (under 30 in a window), `failed_holdout`, `not_significant`
(deflated Sharpe probability under 0.95), `lags_buy_and_hold`,
`survived_holdout`. The best label never says "proven": one or two months of
one instrument cannot establish an edge.

## Deployment notes

- Set `EVE_INTERNAL_SECRET` on both sides before the bridge leaves localhost.
- Set `SUPABASE_URL` and `SUPABASE_ANON_KEY` on the engine. Projects on the
  legacy HS256 JWT secret also need `SUPABASE_JWT_SECRET`.
- Apply Hisaab's `supabase_schema.sql` (idempotent) for the `algo_*` tables;
  `scripts/sql/verify-algo-rls.sql` checks the policies against a local Postgres.

## Tests

`tests/test_phase15_gate.py`, `_spec.py`, `_compile_causality.py`,
`_store.py`, `_evaluation.py`, `_paper.py`.
