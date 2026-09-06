# Implementation progress log

Running log for `plans/2026-09-06-ema-tuning-and-smc-strategies.md`.
Newest entries at the top.

---

## 2026-09-06 -- Phases 1-3 complete and verified

**Phase 1 -- Units, bracket exits, gate check**
- `quant/backtest/market.py` (new) -- `MarketContext`, single paise->rupee
  conversion boundary, guard rejects raw paise (e.g. `10.0`) unconverted.
- `quant/backtest/exits.py` (new) -- `ExitConfig`: stop-loss, target,
  trailing stop, time-stop, EOD square-off. Conservative intrabar
  precedence (stop wins ties; gaps fill at open).
- `quant/backtest/engine.py` (modified) -- bracket-exit execution,
  `exit_reason`/`mae`/`mfe`/`bars_held`/`r_multiple` trade columns
  (appended, never inserted). Default `ExitConfig()` reproduces the
  pre-Phase-09 engine bit-for-bit -- verified by mutation testing
  (deliberately reintroduced the trailing-stop lookahead bug and
  confirmed the test suite catches it).
- `quant/indicators/atr.py`, `quant/candles/session.py` (new).
- **Gate finding:** re-ran the "profitable" July 2026 15m EMA baseline
  (previously +Rs 5,737) with corrected lot 65 / tick Rs 0.10 and a real
  EOD square-off (15:15, the last 15m bar's own label). Result flips to
  **-Rs 11,308** (PF 0.69, 8 trades vs 4) -- the old result was a single
  trade riding to the backtest's month boundary (+Rs 26,914, held 7
  calendar days), not a strategy. Documented in `data/results/STALE.md`.
- Tests: `tests/test_phase09_{market,exits}.py`.

**Phase 2 -- Multi-instrument data**
- `quant/data/upstox.py` (modified) -- `UpstoxClient(require_auth=False)`
  (verified: v3 historical-candle serves index spot unauthenticated),
  retry+backoff on 429/5xx.
- `quant/data/index_spot.py` (new) -- `resolve_contract_specs()` (reads
  the LIVE instrument master, never hardcodes -- caught BANKNIFTY's real
  tick size of Rs 0.20, which a literal would have gotten wrong),
  `download_index_month`/`download_index_range` (resumable, hard-fails
  on a 0-row response instead of writing a placeholder).
- `quant/data/download.py` (modified) -- same 0-row guard added to the
  existing futures downloader.
- `scripts/download_index_history.py`, `scripts/process_index_history.py`
  (new).
- `quant/processing/pipeline.py` (modified) -- `process_index_month()`.
- `quant/data/store.py` (new) -- `load_candles()` builds one continuous
  multi-month frame; verified 1,157 trading days of NIFTY 15m,
  2022-01-03 -> 2026-09-04.
- **Backfilled: NIFTY/BANKNIFTY/SENSEX index-spot 1m, 2022-01 -> 2026-09**
  (171 months, ~1.3M rows, zero failures) and processed into 1m/5m/15m
  under `data/{raw,processed}/index/<SYMBOL>/<YYYY-MM>/`.

**Phase 3 -- EMA fix**
- `quant/indicators/angle.py` (modified) -- `ema_slope_atr_expr` /
  `add_ema_slope_atr`, additive.
- `quant/strategies/ema_9_15.py` (modified) -- `angle_mode`,
  `atr_period`, `slope_threshold_atr` (ships neutral at 0.0 -- the sweep
  picks the value, not this file). `slope_atr` appended as a trailing
  output column.
- Verified on real July 2026 NIFTY data: ATR-normalized selectivity is
  35.3%/30.1%/34.7% across 1m/5m/15m, vs the old fixed-scale filter's
  0.55%/5.01%/13.43% (131x spread -> ~1.2x).
- `quant/research/walk_forward.py` (modified) -- fixed a hardcoded
  `_PARAM_COLUMNS` that would `KeyError` on any new grid.
- Tests: `tests/test_phase09_angle.py`; `tests/test_phase04_signals.py`
  updated for the additive `slope_atr` column.

**Foundational (Phase 8 prep)**
- `quant/research/protocol.py` (new) -- pre-registered
  `DISCOVERY_SPLITS`/`CONFIRM_SPLITS`, tiered `MIN_TRADES` (measured
  basis: PDH/PDL sweep-and-fail fires on 60% of the 31 available
  sessions, OR break-and-reverse on 68% -- a flat 100-trade test minimum
  would fail every event-driven family on sample size alone), seal/unseal
  mechanics enforcing "test split opened exactly once."
- Tests: `tests/test_phase09_protocol.py`.

**State: 243 tests passing, ruff clean.** Only 4 pre-existing failures
remain (`test_phase02_processing.py` x3, `test_phase07_mcp.py::
test_process_month_data`), confirmed present on unmodified `master`
before this work started -- unrelated to Phase 09.

**Not yet done:** Phase 4 (new tuning grid/sampling), Phase 5 (causal SMC
primitives + 5 strategies), Phase 6 (parallel sweep harness), Phase 7
(agent round loop), Phase 8 (promotion gate wiring), Phase 9 (MCP
surface).
