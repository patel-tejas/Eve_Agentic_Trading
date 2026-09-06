# Implementation progress log

Running log for `plans/2026-09-06-ema-tuning-and-smc-strategies.md` and
`plans/2026-09-06-ema-ha-pattern-scale-out.md` (the HA-pattern-gated
entry + scale-out ladder variant, requested after round 3). Newest
entries at the top.

---

## 2026-09-07 -- HA-pattern-gated EMA entry + scale-out exit ladder ("ema_ha"), full campaign run

Implemented per `plans/2026-09-06-ema-ha-pattern-scale-out.md`, entirely
within the same pre-registered protocol/campaign (`C2026-09-EMA-SMC`) as
rounds 1-3 -- a new family raises the deflated-Sharpe bar, it does not
get a fresh one.

**Phase 0 gate (run first, before any engine work):** measured the
crossover-AND-HA-pattern base rate across 3 instruments x {5m, 15m} x a
threshold matrix on the train split. 191 of 216 (symbol, tf, threshold)
cells projected >= 100 train / >= 30 validation trades -- proceeded.

**New indicator primitives** (`quant/indicators/heikin_ashi.py`,
`quant/indicators/patterns.py`): Heikin Ashi transform (`ha_open`
recursion built as an `ewm_mean(alpha=0.5, adjust=False)` over a
one-bar-shifted `ha_close` series seeded at `(open[0]+close[0])/2` --
proven algebraically identical to the textbook recursion via a
hand-computed 5-bar fixture, not just self-consistent) and
doji/hammer/inverted-hammer/small-range flags (`add_candle_shape`,
prefix-parameterised so the same code runs on real OHLC or HA columns).
Both proven causal via the `test_prefix_equals_full_frame` harness.
8 new tests, `tests/test_phase11_causality.py`.

**New strategy** `quant/strategies/ema_ha_pattern.py` (id `ema_ha`): 9/15
EMA crossover gated on a qualifying HA pattern within `pattern_window_bars`
of the cross; structural stop (`stop_mode="signal"`) at the anchor bar's
REAL low/high (never the smoothed HA level) -- picked up automatically by
the existing `tests/test_phase09_strategy_causality.py` parametrized
suite once registered.

**Engine surgery** (`quant/backtest/exits.py`, `quant/backtest/engine.py`):
added `ScaleLeg`/`ExitConfig.scale_out` (partial exits sized in LOTS, not
fractional contracts) and a `trail_mode="prev_candle_extreme"`. Every
exit path (signal reversal, stop, target, trail, time, EOD,
end-of-data) now funnels through one `_add_leg` + `_finalize_trade`
mechanism that consolidates N legs into exactly ONE trades-frame row --
critical because a naive one-row-per-leg design would silently triple
`total_trades`, distort `profit_factor`, satisfy the pre-registered
`MIN_TRADES` gate on leg-inflation alone, and break the bootstrap/
permutation significance tests (legs of one trade are not exchangeable
observations). `ExitConfig(scale_out=())` is proven byte-for-bit
identical to the pre-Phase-11 engine by construction (a single leg's
cost/gross formula reduces exactly to the old `round_trip_costs`), not
merely asserted -- the entire pre-existing `test_phase05_backtest.py`/
`test_phase09_exits.py` suites (62 tests) pass unmodified against the
rewritten engine. 10 new tests in `tests/test_phase11_scale_out.py`,
including a manually mutation-tested guard on the `prev_candle_extreme`
trail's `i-1`-only causality (confirmed the test fails when the bug is
deliberately reintroduced, then reverted).

**Sampling/dedup**: `quant/research/sampling.py` gained `canonical_exits`
(quantises scale-leg fractions to actual lot counts before hashing --
0.30 and 0.33 both floor to 1 lot at 4 lots and must not count as
distinct trials) and an `ema_ha` branch in `canonical_params`.
`quant/research/sweep.py`'s `Trial` gained `position_size`/
`initial_capital` (included in `param_hash`'s market dict, so a 1-lot
and a 4-lot config never collide). 7 new tests,
`tests/test_phase11_sampling.py`.

**Campaign** (`scripts/run_round4.py`, rounds 5-8 of `C2026-09-EMA-SMC`,
position_size=4 lots / initial_capital=Rs 40L so 50%/25%/25% lands on
exact 2/1/1 lots and maxDD% stays comparable to the 1-lot campaign):

| Stage | Split | Trials | Wall |
|---|---|---|---|
| 1 -- entry logic (fixed 1R/2R/25% ladder) | train | 19,440 | 650s |
| 2 -- ladder + structural-stop LHS (n=128) x top-6 entries/cell | train | 4,536 | 158s |
| 3 -- local refinement (+/-1 grid step) | train | 208 | 16s |
| validation -- each cell's Stage-3 winner, scored ONCE | val (2025) | 6 | 2s |

0 errors across all 24,190 trials. Cumulative campaign trial count after
this round: **19,714** distinct param hashes (the `n_trials` the
deflated Sharpe ratio is penalized against).

**Result** (`data/results/leaderboard/C2026-09-EMA-SMC/EMA_HA_REPORT.md`):
4 of 6 cells flip negative on validation despite strong (PF 1.35-1.7,
positive on 5/6 cells) train-split numbers -- the familiar overfitting
signature. The 2 cells that stay positive (BANKNIFTY 5m: +Rs242,841, PF
1.92, 72 trades; SENSEX 5m: +Rs89,738, PF 1.43, 196 trades) pass every
raw P&L/PF/drawdown/artifact check but **both fail the statistical gate**
on deflated Sharpe (DSR ~1e-5 to 0.12, nowhere near the 0.95 bar once
penalized against 19,714 cumulative trials) and bootstrap CI (both
include zero, e.g. BANKNIFTY 5m: [-0.71, 3.01]). **Verdict: 0 of 6 pass.
No edge established for the HA-pattern-gated entry either** -- the same
honest, pre-registered outcome as rounds 1-3, now with the added
statistical headwind of a larger cumulative trial count. TEST split
(2026) remains sealed and untouched.

**State: 315 tests passing (up from 288), ruff clean.** Same 4
pre-existing failures as before (unrelated to this work).

---

## 2026-09-06 -- Round 3 complete: final comprehensive comparison, all 6 strategies x both timeframes

`scripts/run_round3.py` (new): for ALL 36 (strategy, symbol, timeframe)
cells -- not a narrowed subset like round 2 -- takes that cell's own
TRAIN-split best config (round 1) and scores it ONCE on the untouched
2025 VALIDATION year, then runs the formal statistical gate on every
result. 36 trials, 0 errors, 16s wall (this was a small, targeted sweep,
not a new parameter search). Final report:
`data/results/leaderboard/C2026-09-EMA-SMC/FINAL_REPORT.md`.

**Nominal ranking (raw validation-split net_pnl, averaged across the 3
instruments) -- read with the caveat below before trusting it:**

| Timeframe | Best strategy | avg net_pnl | avg PF | avg trades |
|---|---|---|---|---|
| 5m | `ist_judas` | +Rs 11,463 | 1.24 | 35 |
| 15m | `ema` | +Rs 6,305 | 1.18 | 104 |

**Caveat that matters:** `ist_judas`'s 5m "win" is propped up almost
entirely by two near-empty cells -- SENSEX 5m had exactly **3** trades
in the whole validation year, NIFTY 5m had **6**. An average across
3/6/96-trade cells is not a meaningful comparison; `ema` on 15m is the
only entry in either ranking built on cells that all clear >=30 trades
(32-172 across the three instruments) and is the more defensible
"best," such as it is.

**Formal statistical gate: 0 of 36 cells pass** (deflated Sharpe,
survival at 95%; bootstrap CI excludes zero) -- penalized against the
campaign's true cumulative 5,259 distinct trials. Every single
(strategy, timeframe) combination fails. **No candidate from this
campaign is statistically credible.**

### Campaign verdict

Three rounds, ~8,750 total trials, one legitimate stopping point: **no
edge established** under this protocol, for any of the 6 strategy
families (the re-normalized EMA, or the 5 new SMC/ICT strategies), on
either timeframe searched (5m, 15m), across any of the 3 instruments.
This is the honestly-reported, pre-registered outcome -- the TEST split
(2026, containing June/July/August) has never been opened and remains
sealed; there is nothing to justify opening it, since the protocol
requires clearing the validation-split gate first, and nothing did.

What WAS fixed and verified along the way, independent of whether an
edge was found: the angle-filter scale bug (131x selectivity spread ->
~1.2x), the paise/rupee tick-size trap, the lot-size error, the missing
bracket-exit/EOD-square-off machinery, the force-close backtest
artifact that had been read as a real result, two real multiprocessing
bugs (registry-not-populated-in-spawned-workers, OpenBLAS thread
oversubscription) that a smoke test could not have caught, and two
statistical holes in the validator that were inflating confidence. The
tuning/search/validation infrastructure itself is sound and reusable
for a future campaign with different strategies or ranges.

---

## 2026-09-06 -- Round 2 complete: no candidate survives validation. Honest, gated verdict.

`scripts/run_round2.py` (new): stage 2a (EMA exit tuning -- top-6 distinct
15m entries per instrument from round 1, crossed with an LHS(128) sample
of `STAGE2_EXIT_GRID`, on TRAIN) + stage 2b (score round 2a's best EMA
config AND round 1's top-5-per-cell SMC configs ONCE on the untouched
2025 VALIDATION year). 2,304 + 153 = 2,457 trials, 0 errors, 55s wall.

**A second real multiprocessing bug found only by running the actual
campaign at scale:** `OpenBLAS error: Memory allocation still failed
after 10 retries, giving up`, crashing the whole pool
(`BrokenProcessPool`) partway through stage 2a. `POLARS_MAX_THREADS=1`
was not enough -- numpy's OpenBLAS backend (used by
`quant.research.sampling`'s RNG and the `_stats`/`significance`/
`multiple_testing` modules) has its own, independent thread pool. 14
worker processes x OpenBLAS's own default all-core thread pool each is
the same oversubscription problem in a different library, and it fails
by crashing rather than merely running slow. Fixed: `sweep.py` now also
sets `OPENBLAS_NUM_THREADS`, `OMP_NUM_THREADS`, `MKL_NUM_THREADS`,
`NUMEXPR_NUM_THREADS` to `"1"` in the parent before the pool is created.
Regression test updated (`test_single_threaded_env_vars_set_by_run_sweep`).
Retried clean after the fix: 0 errors.

### The result, honestly

**Every round-1 "winner" that looked promising in-sample FAILED to hold
up against the untouched 2025 validation year.** Most strikingly:
`pdh_pdl_turtle_soup` on BANKNIFTY -- round 1's standout, 100% of 72
combos net-positive, PF 1.4-1.7, a checked plateau not a spike -- turns
**net-NEGATIVE on validation** (best combo: -Rs 30,617, PF 1.06; worst
of the carried-forward set: -Rs 61,393, PF 0.98). The exit-tuned EMA
(BANKNIFTY 15m) comes back roughly flat (-Rs 1,909, PF 1.22, Sharpe
~0.01); NIFTY and SENSEX EMA configs produced too few trades on one
validation year to even clear `MIN_TRADES["train"]=100` and could not
be assessed. A handful of SMC cells (smc_sweep_fvg, smc_ob_choch,
ist_judas on BANKNIFTY/NIFTY 5m) came back nominally positive but on
only 1-2 surviving configs per cell -- the automated plateau-vs-spike
check correctly flagged the best of these
(`smc_sweep_fvg`/BANKNIFTY/5m) as a **possible isolated spike**, not a
supported result.

**Ran the formal promotion gate (`scripts/promote_candidate.py --split
val`) against the top 15 validation-split candidates. Verdict: 0 of 15
pass.** Every one fails both deflated Sharpe (survival at 95%) and the
bootstrap Sharpe CI (excludes zero), correctly penalized against the
campaign's cumulative 5,259 distinct trials -- not just this round's.
This did not require unsealing the TEST split (2026 data): the gate ran
against `split="val"`, and `--split test` remains blocked by the seal
mechanism (`quant.research.protocol.unseal_test`) until there is a
reason to open it.

**This is the legitimate, pre-registered outcome the plan explicitly
built for** ("edge found and gated, OR no edge established, here is the
evidence and which gate each candidate failed") -- not a bug, and not a
failure of the campaign. If anything it is a positive result for the
*methodology*: the train/validation split and the plateau-vs-spike
check caught an overfit result (Turtle Soup) before the statistical
gate would have had to. The TEST split has not been touched and remains
sealed.

**Not done / open decision:** whether to spend a round 3 on materially
different ranges (different strategy families, wider entry windows, or
switching the confirmation leg to the real futures data instead of the
index-spot proxy) or to close the campaign here with "no edge
established on this protocol" as the final, honestly-reported result.

---

## 2026-09-06 -- Round 1 sweep launched (real data, discovery train split)

`scripts/run_round1.py` (new) + `scripts/analyze_round.py` (new,
deterministic "Analyst" role -- per project convention, Task/Agent
subagents are not spawned unless asked, so this round-loop step is
ordinary reproducible code reading the leaderboard, not an LLM call).

Also registered the EMA family itself into `STRATEGY_REGISTRY`
(`quant/strategies/ema_9_15.py`, `_registry_generate_signals` adapter)
so it flows through the identical sweep/leaderboard machinery as the 5
SMC strategies -- one engine, one leaderboard schema, for every family.

Round 1 scope (deliberately bounded, per the plan's round protocol):
search ENTRY logic broadly (EMA's Stage-1 grid, full param space for
each of the 5 SMC strategies), hold exits at one reasonable FIXED
configuration (ATR stop 1.5x / R-multiple target 2.0x for EMA;
structural signal-based stop/target for the SMC strategies). Exit
tuning is round 2+ work. Campaign `C2026-09-EMA-SMC`, round 1, on
`DISCOVERY_SPLITS["train"]` (2022-01-01 -> 2024-12-31), 3 instruments
(NIFTY/BANKNIFTY/SENSEX) x 2 timeframes (5m/15m) x 6 strategies.

**Result: 5,946 trials, 0 errors, 210s wall clock on 14 workers**
(~35ms/trial average -- 3-year 5m frames are the slow end). Full report:
`data/results/leaderboard/C2026-09-EMA-SMC/round_01/analysis.md`
(generated by `scripts/analyze_round.py`).

Headline, TRAIN-SPLIT / SCREENING ONLY -- none of this has been through
validation-split ranking (round 2), the test-split gate (round 3), or
ANY of the deflated-Sharpe/PBO/bootstrap/BH-FDR machinery yet. Treat
exactly as the repo's own Phase 08 grid was treated before its DSR/PBO
verdict: informative about where to look next, not evidence of an edge.

- **`pdh_pdl_turtle_soup` (S5) is the strongest, broadest performer.**
  100% of its 72 combos are net-positive on BANKNIFTY (both 5m and 15m),
  PF 1.4-1.7, 271-506 trades, maxDD 5.8-9.5%. The top-20 leaderboard is
  almost entirely this strategy on BANKNIFTY. The winning combo has 12
  of 72 same-cell trials within 20% of its net_pnl -- a supported
  plateau, not an isolated spike (checked automatically).
- **The re-normalized EMA is materially better on 15m than the old
  fixed-scale filter ever showed**: 64-81% of combos positive across
  all three instruments on 15m (vs. the single-month baseline's -11,308
  net once corrected). On 5m it is weak (15-27% positive) -- consistent
  with Phase 1's cost-per-bar-count finding.
- `smc_sweep_fvg` (S1) is a solid second: 56-73% positive on several
  cells, PF up to 1.91.
- `orb_vwap` (S4) is instrument-dependent (100% positive on NIFTY/SENSEX
  5m, 0% on BANKNIFTY 5m) and ran here on index spot (`vwap_is_proxy`) --
  screening only, per the plan; never eligible for promotion without a
  futures re-run.
- `ist_judas` (S3) and `smc_ob_choch` (S2) are the weakest of the six,
  net-negative on most cells except BANKNIFTY.

**Not yet done:** round 2 (validation-split ranking + exit-parameter
tuning for the survivors above), round 3 (local refinement + the
one-shot test-split gate), futures confirmation, `scripts/
promote_candidate.py` (written, unexercised).

## 2026-09-06 -- Phases 4-6 + Phase 8 statistical fixes complete and verified

**Phase 4 -- new tuning space**
- `quant/research/sampling.py` (new) -- `canonical_params` (effect-based
  dedup: a config identical in EFFECT to another, e.g.
  `slope_threshold_atr=0.0` with any `angle_lookback`, collapses to one
  canonical form), `sample_combinations` (discrete Latin-hypercube-style
  sampling, deterministic under seed), `local_refinement` (+/-1 grid
  step, clipped at grid edges, never extrapolates).
- `quant/research/parameter_search.py` (modified) -- `STAGE1_EMA_GRID`
  (~598 valid combos after dedup, measured), `STAGE2_EXIT_GRID`,
  `STAGE3_NUMERIC_AXES` (only the 4 numeric exit axes -- categorical
  fields like `stop_mode` stay fixed during Stage-3 refinement).
  `evaluate_params` gained `exit_params` (layers an `ExitConfig` onto a
  `BacktestConfig` via `dataclasses.replace`). `DEFAULT_GRID` untouched
  (320 combos, existing tests still pass).
- Verified end-to-end on real NIFTY 15m index-spot data (Jan-Jun 2022):
  Stage 1 -> Stage 2 (LHS n=20) -> Stage 3 (local refinement) pipeline
  runs correctly; ~14ms/trial.
- Tests: `tests/test_phase09_sampling.py`.

**Phase 5 -- causal SMC primitives + 5 strategies**
- `quant/indicators/structure.py` (new) -- `add_swings` (confirmed
  pivots, emitted at `p+right` not `p`), `add_fvg` (3-bar gaps +
  mitigation tracking via an explicit per-bar loop -- inherently
  stateful, so vectorizing it would be the wrong trade), `add_bos_choch`,
  `add_order_blocks`, `add_prev_day_levels`, `add_session_levels`,
  `add_vwap` (falls back to unweighted typical-price mean when volume is
  zero, self-flagging `vwap_is_proxy`). Explicitly does NOT wrap the
  `smartmoneyconcepts` PyPI package -- its `swing_highs_lows` is CENTERED
  (peeks into the future) and it is pandas-based; verified both facts
  before writing this module. Zero new dependencies.
- `tests/test_phase09_causality.py` (new, non-negotiable per the plan) --
  prefix-equals-full-frame for every primitive, PLUS a test that
  deliberately reintroduces the centered-window bug and confirms the
  harness catches it (a vacuous test suite would be worse than none).
- `quant/strategies/base.py` (new) -- `StrategySpec`/`STRATEGY_REGISTRY`,
  `can_run_on()` guards a `requires_volume` strategy off index-spot data.
- Five strategies, all built on the primitives above, all NSE/BSE
  09:15-15:30 IST (no US kill-zones): `smc_sweep_fvg` (S1, liquidity
  sweep + FVG reversal), `smc_ob_choch` (S2, order block + BOS/CHoCH
  continuation), `ist_judas` (S3, IST-timed opening raid fade),
  `orb_vwap` (S4, opening range breakout + VWAP/ATR filter),
  `pdh_pdl_turtle_soup` (S5, PDH/PDL sweep-and-reverse). Each returns
  `timestamp, signal_type, stop_price, target_price` for
  `ExitConfig(stop_mode="signal", target_mode="signal")`.
- `tests/test_phase09_strategy_causality.py` (new) -- same
  prefix-equals-full-frame guarantee, one level up, for all 5 registered
  strategies via the registry (parametrized, not hand-duplicated per
  strategy).
- Verified all 5 end-to-end against real July 2026 NIFTY futures data
  through the actual backtest engine (not just signal generation).

**Phase 6 -- parallel sweep harness + leaderboard**
- `quant/research/leaderboard.py` (new) -- JSONL shard writes
  (`part_<pid>_<chunk>.jsonl`, one per worker chunk, merged on read into
  a single frame), `trial_param_hash`, `completed_trial_ids`,
  `cumulative_trial_count` (distinct `param_hash` across the WHOLE
  campaign -- what DSR must be penalized against, not one round's count).
- `quant/research/sweep.py` (new) -- `Trial` (frozen, picklable),
  `run_trial` (never raises -- captures `status="error"` so one bad
  config can't kill a sweep), `run_sweep` (`ProcessPoolExecutor`,
  `POLARS_MAX_THREADS=1` set in the parent before pool creation, resume
  via `completed_trial_ids`).
- **Two real bugs found and fixed via mutation/integration testing on
  the actual Windows multiprocessing path (not just unit tests):**
  1. `run_sweep` only checked new trials against PREVIOUSLY COMPLETED
     ones, not against each other within the SAME call -- two identical
     trials submitted together both ran and both got written as
     duplicate leaderboard rows. Fixed: dedupe the input list by
     `trial_id` (first occurrence kept) before the completed-trials
     filter.
  2. **On Windows, `ProcessPoolExecutor` SPAWNS a fresh interpreter per
     worker rather than forking.** A worker only gets `STRATEGY_REGISTRY`
     populated if `quant.research.sweep` itself imports the strategy
     modules -- a caller importing them in its own `__main__` script does
     NOT make them visible inside a spawned worker. Without this fix,
     every trial in a real multi-worker run failed with a `KeyError`
     invisible to a single-process smoke test (which is why the bug
     wasn't caught until the actual parallel path was exercised). Fixed
     by importing all 5 strategy modules at the top of `sweep.py` itself.
  3. Measured real parallel throughput on this machine: 60 trials across
     8 workers on 15m NIFTY futures data in ~0.87s.
- Tests: `tests/test_phase10_sweep.py` (idempotent resume, in-call
  dedup, `POLARS_MAX_THREADS` set, one bad trial doesn't kill the sweep,
  cumulative count is distinct-param-hash-across-rounds).

**Phase 8 (partial) -- fixed two statistical holes, both of which
previously INFLATED confidence**
- `quant/research/validate.py` (modified) -- `validate_parameter_search`
  gained two additive, backward-compatible parameters:
  - `n_trials_override`: lets a sweep campaign pass its TRUE cumulative
    trial count (from `leaderboard.cumulative_trial_count()`) instead of
    this one call's own grid size, to `deflated_sharpe_ratio`. Verified:
    a larger override provably raises the luck benchmark and cannot
    increase the deflated Sharpe.
  - `min_trades`: filters near-zero-trade trials out BEFORE selection and
    BEFORE `trial_sharpes` is built. A zero-trade trial has zero return
    variance -> `sharpe_ratio` reports exactly 0.0; a pile of identical
    0.0s SHRINKS the measured `trial_sharpe_std`, which shrinks the luck
    benchmark, which makes DSR easier to pass for the wrong reason. The
    existing walk-forward schedule already produces zero-trade steps, so
    this was a live, not hypothetical, hole.
  - Also fixed: PBO's "too few trials" skip check now uses `len(results)`
    (the trials actually in this call, matching the CSCV matrix's own
    width) rather than the possibly-overridden `n_trials`, which would
    otherwise have masked a real too-few-trials condition.
- Tests: `tests/test_phase09_validate_fixes.py`. All 78 pre-existing
  `test_phase08b_validation.py` tests still pass unmodified.

**State: 286 tests passing, ruff clean.** Same 4 pre-existing unrelated
failures as before.

**Not yet done:** the remainder of Phase 8 (promotion gate script,
`scripts/promote_candidate.py`), Phase 7 (round-loop orchestration
script -- implemented as deterministic code performing the Analyst
role, not spawned LLM subagents, per project convention), Phase 9 (MCP
surface). A real Round 1 sweep has not yet been run at full scale.

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
