# Fine-tune the EMA strategy, rebuild the tuning space, add 5 Indian-market SMC/ICT strategies, and run a parallel search campaign

> **Status: done (2026-09-06).** All phases implemented; the 3-round
> campaign (rounds 1-3, ~8,750 trials) ran to completion. Verdict: 0 of
> 36 (strategy, symbol, timeframe) cells passed the statistical gate on
> the validation split -- no edge established, honestly, per the
> pre-registered protocol. See `plans/PROGRESS.md` for the running
> implementation log and `data/results/leaderboard/C2026-09-EMA-SMC/
> FINAL_REPORT.md` for the full results table. Follow-up work (a
> Heikin-Ashi pattern-gated entry + scale-out ladder, same campaign) is
> tracked in `plans/2026-09-06-ema-ha-pattern-scale-out.md`.

## Context

The 9/15 EMA + 30° angle strategy does not work, and the repo's own Phase-08b validation already says so: **deflated Sharpe 0.1505 (fails), bootstrap Sharpe CI [-3.81, 8.82] (includes zero), PBO 0.686 (overfit) → "no edge established."**

That verdict is right, but it is a verdict on a broken measurement. Five defects were found, four of them fixable, and each was verified against the data on disk rather than inferred.

### 1. The angle filter is scale-broken

`quant/indicators/angle.py:36-38` computes `angle = atan(((EMA[t]-EMA[t-k])/EMA[t-k]) × 1000) × 180/π` with `angle_scale` frozen at 1000. A 30° threshold therefore demands a normalized slope of `tan(30°)/1000 = 0.0577%` per bar — **14.0 NIFTY points of 9-EMA movement in a single bar, identical on every timeframe.** Fraction of July bars that pass:

| | lb=1 | lb=3 | lb=5 |
|---|---|---|---|
| 1m | **0.55%** | 3.31% | 8.41% |
| 5m | 5.01% | 19.95% | 34.11% |
| 15m | 13.43% | 50.00% | **72.06%** |

The same nominal "30°" is a **131× different filter** across the grid, and `angle_lookback` silently rescales `angle_threshold` rather than acting as an independent knob. **The 320-combo grid was never searching what it claimed to search.** On disk: variant B took 0 trades on 1m and 0 on 5m for all of August, and 0 trades on July's only high-volatility day — the gate screens out exactly the regime worth trading.

The same data, ATR-normalized as `(EMA[t]−EMA[t−k]) / (k · ATR[t])`, is near-invariant across every timeframe and lookback:

| | p50 | p70 | p85 | p95 |
|---|---|---|---|---|
| 1m | 0.148 | 0.232 | 0.340 | 0.502 |
| 5m | 0.126 | 0.202 | 0.309 | 0.512 |
| 15m | 0.150 | 0.222 | 0.359 | 0.566 |

One threshold now means the same selectivity everywhere, and it widens in volatile regimes instead of shutting off. Dividing by `k` is what decouples the threshold from the lookback.

### 2. The engine cannot express a stop or a target

`quant/backtest/engine.py:145-179` exits on the opposite signal only. No stop-loss, no take-profit, no trailing stop, no time-stop, and **no end-of-day square-off** — positions are marked across overnight gaps. The single trade carrying July's profit (LONG Jul 24 13:00 → Jul 31 15:15, **+₹26,914**, 134 bars) exited only because the month ended (`closed_at_end=1`). That is a backtest boundary artifact, not an exit. Every ICT/SMC strategy is stop-and-target based, so this blocks the new work too.

### 3. Contract specs are wrong — and the units are a trap

`contract_metadata.json` reports `lot_size: 65` and `tick_size: 10.0`. `BacktestConfig.lot_size` is hardcoded to **50**, `SlippageConfig.tick_size` to **0.05**. The processed parquets already carry both columns and nothing reads them.

**`tick_size: 10.0` is in paise (= ₹0.10).** If that value ever reaches `SlippageConfig.tick_size` unconverted, slippage becomes ₹10 × 65 = ₹650/leg — ~200× too large, and every result reads as "the strategy is terrible." One conversion boundary, guarded, is a hard requirement.

### 4. The economics were never checked, and they rule out 1m

Verified against `quant/backtest/costs.py` at NIFTY ≈ 24,251:

| Config | Round-trip cost | Break-even |
|---|---|---|
| lot 50 / tick ₹0.05 (current) | ₹341 | 6.83 points |
| lot 65 / tick ₹0.10 (correct) | ₹436 | 6.71 points |

This reconciles exactly with the recorded July A/1m run: 268 trades, mean ₹336.4/trade, ₹90,155 total. The cost model is correct; only the constants were wrong. Note that break-even **in points barely moves** (6.83 → 6.71) because cost and P&L both scale with lot size — the lot fix changes rupee magnitudes ~30% and therefore changes which configs clear `maxDD < 10%` of fixed ₹10L capital, but it does not rescue anything.

Against median ATR14 per timeframe:

| Timeframe | ATR14 | Net edge needed per trade |
|---|---|---|
| **1m** | 7.7 pts | **0.86 ATR** |
| 5m | 17.8 pts | 0.37 ATR |
| 15m | 34.0 pts | 0.20 ATR |

**No EMA crossover produces 0.86 ATR of net edge per trade at any parameter setting.** That is the whole explanation for the −₹103,025 result, and it is not a tuning problem.

> **Decision: drop 1m from all P&L research.** Keep it as an aggregation source and for higher-timeframe-confirmation inputs. Do not spend a core-hour tuning it.

### 5. There is almost no data

31 trading days: NIFTY futures July 2026 (23 days) + Aug 3–12 2026 (8 days). No June, no BANKNIFTY, no SENSEX. `data/raw/futures/{2026-01,2026-02,2026-03}/candles_1m.parquet` are **0-row placeholders** — the downloader resolved a live contract for a historical month, got `[]`, and wrote the file with no `len(frame)` guard (`quant/data/download.py:168-184`). Searching 320 variations against 4-trade months is a best-of-N noise draw, which is precisely what PBO 0.686 measured.

**The unlock, verified live against the API:** Upstox v3 `historical-candle` serves **1-minute data back to January 2022, unauthenticated**, for `NSE_INDEX|Nifty 50`, `NSE_INDEX|Nifty Bank`, `BSE_INDEX|SENSEX` (1 month per request). ~1,150 sessions × 3 instruments instead of 23 × 1. Index candles carry `volume = 0`, so volume-dependent strategies stay on futures.

### Intended outcome

A correctly-measured EMA strategy with real exits, a tuning space that searches what it claims to, 5 NSE/BSE-adapted SMC/ICT strategies, and a parallel campaign that reports honestly whether anything clears a pre-registered bar on a sealed 2026 test set — which is exactly the June/July/August window asked for.

**On "run agents in a loop until we find good profits":** the loop is built as asked, but it makes the acceptance bar *harder*, by design. The deflated-Sharpe luck benchmark scales as √(2 ln N); going from 320 to ~30,000 cumulative trials raises the bar from ~3.4σ to ~4.5σ of trial dispersion. More search on the same data cannot manufacture an edge — it can only find one that survives being searched for. The campaign has two legal terminal states: *edge found and gated*, or *no edge established, here is the evidence and which gate each candidate failed*.

## Decisions already made

| Decision | Choice |
|---|---|
| Data basis | Index spot 2022-01 → 2026-09 for discovery; NIFTY futures Jul/Aug 2026 as a cost-realistic overlay |
| Acceptance bar | Statistically credible — DSR > 0.95, PBO < 0.5, bootstrap CI excluding zero, plus P&L/PF/DD/trade-count minima |
| Loop budget | 3 rounds |

---

## Pre-registered protocol — written and committed BEFORE any sweep runs

**New `quant/research/protocol.py`** (tracked in git — `data/results/` is gitignored, so the protocol cannot live only there). Its `canonical_json` hash is written to `data/results/search/<campaign>/test_seal.json` at campaign start and checked at every gate.

```python
DISCOVERY_SPLITS = {                      # index spot, price_source="index_spot_proxy"
    "train": (date(2022,1,1),  date(2024,12,31)),   # ~740 sessions  parameter selection
    "val":   (date(2025,1,1),  date(2025,12,31)),   # ~245 sessions  round-to-round ranking
    "test":  (date(2026,1,1),  date(2026,9,5)),     # ~170 sessions  SEALED — opened once
}
CONFIRM_SPLITS = {                        # futures, price_source="futures"
    "train": (date(2026,7,1), date(2026,7,31)),
    "test":  (date(2026,8,3), date(2026,8,12)),     # 8 days — sanity check, NOT a gate
}
EMBARGO_TRADING_DAYS = 1
MIN_TRADES = {"train": 100, "val": 30, "test": 20}
MAX_ROUNDS = 3
```

**The test split contains June, July and August 2026.** No sweep, no agent, and no ranking step reads it until the final gate.

**Why `MIN_TRADES` is tiered rather than a flat 100 — measured, not assumed.** The event-driven strategies fire on a fraction of sessions. On the 31 sessions available:

| Event | Frequency | Projected over the 170-session test split |
|---|---|---|
| PDH/PDL sweep-and-fail (S5) | 18/30 sessions = 60% | ~102 |
| OR break-and-reverse 09:45–11:00 (S3) | 21/31 sessions = 68% | ~115 |

Those are *before* the ATR-displacement and overshoot filters cut them further. A flat 100-trade test minimum would fail every SMC family on sample size alone regardless of edge, so the minima are declared **now, with this measured basis**, not adjusted after seeing results.

**Stopping rule:** 3 rounds maximum; the Referee may declare exhaustion earlier if two consecutive rounds show no validation improvement > 10%. The test split is unsealed once, at the end. **No re-tuning after unsealing** — enforced mechanically: `run_sweep.py` refuses `--split test` unless `--unseal-test` is passed with the matching seal hash, and the unseal event is recorded in the leaderboard.

---

## Phase 1 — Units, bracket exits, and a re-run of the existing grid

No new data, no new strategies. Produces numbers on day one and settles whether the EMA is dead or was merely un-exitable.

### 1.1 Contract units — one conversion boundary, guarded

**New `quant/backtest/market.py`:**
```python
@dataclass(frozen=True)
class MarketContext:
    symbol: str
    price_source: Literal["futures", "index_spot_proxy"]
    lot_size: int              # a COUNT — never scaled
    tick_size_rupees: float    # INR — instrument master reports PAISE, divide by 100 here
    def __post_init__(self):
        if not 0.01 <= self.tick_size_rupees <= 1.0:
            raise ValueError(f"tick_size_rupees={self.tick_size_rupees} outside [0.01, 1.0]; "
                             "did you pass paise straight from the instrument master?")

def market_context_from_candles(frame, *, symbol, price_source="futures") -> MarketContext
```
Mixed units in one struct is how this class of bug survives review, so the docstring says which field is which and the guard makes the paise mistake impossible to ship. No new I/O — the processed parquets already carry both columns.

`BacktestConfig` gains `market: MarketContext | None = None`; when present it overrides `lot_size` and `slippage.tick_size`.

**Zero test churn.** Verified breakage ledger — these are the only affected assertions:

| Assertion | Location | Action |
|---|---|---|
| `qty = 50` hand-calc | `tests/test_phase05_backtest.py:120` | **Keep `BacktestConfig.lot_size` default at 50.** Thread 65 in via `MarketContext` from the runners only. |
| `"lot_size": 50` in report assumptions | `quant/research/baseline.py:199` | Make dynamic, else reports keep lying. |
| `len(grid_combinations()) == 320` | `tests/test_phase08_research.py:88-90` | **Freeze `DEFAULT_GRID`.** New grids are separate constants. |
| `cfg.angle_scale == 1000.0` | `tests/test_phase04_signals.py:35` | Keep field and default. New normalization is opt-in. |

**Flag for verification before the campaign:** `STT_SELL_RATE = 0.000125` (0.0125%). Indian futures STT was raised to **0.02%** effective 2024-10-01. At 0.02% the round trip is ~₹549 = **8.4 points**, not 6.7 — a 25% harder bar. Confirm against a real contract note; do not assume either way.

**Effect on recorded results:** gross scales ×1.30, costs ~×1.28. Everything under `data/results/**` from Phases 06/08 becomes non-comparable. Write `data/results/STALE.md` recording why, and archive rather than delete.

### 1.2 Bracket exits

**New `quant/backtest/exits.py`:**
```python
@dataclass(frozen=True)
class ExitConfig:
    stop_mode:   Literal["none","atr","points","pct","signal"] = "none"
    stop_atr_mult: float = 2.0
    stop_points: float = 0.0
    target_mode: Literal["none","r_multiple","atr","points","signal"] = "none"
    target_r_multiple: float = 2.0
    trail_mode:  Literal["none","atr","breakeven_then_atr"] = "none"
    trail_atr_mult: float = 2.0
    breakeven_at_r: float = 1.0
    time_stop_bars: int = 0             # 0 = disabled
    session_start: str | None = None    # "09:15" — no entries before
    session_end:   str | None = None    # "15:00" — no NEW entries after
    eod_squareoff: str | None = None    # "15:20" — force flat, per calendar day
    atr_period: int = 14
    intrabar: Literal["conservative"] = "conservative"
```
`BacktestConfig` gains `exits: ExitConfig = field(default_factory=ExitConfig)`. **All defaults reproduce today's behaviour bit-for-bit** — that equivalence is the regression test, and it is why none of the 13 existing test files change.

**Intrabar precedence, per bar `i` on an open position — conservative convention:**
1. **Gap-through** — long: if `open[i] <= sl_level`, fill at `open[i]`, *not* at the stop. Same for a gapped target. This is what makes gaps honest.
2. **Stop-loss** — `low[i] <= sl_level` (long) → fill at `sl_level`.
3. **Take-profit** — `high[i] >= tp_level`. **If SL and TP are both inside the same bar, SL wins.** Pessimistic, standard, asserted in a test.
4. **Trailing stop** — the trail level applicable to bar `i` **must be computed from bars ≤ i−1 only.** Updating the trail from bar `i`'s own high and then testing bar `i`'s low against it is intrabar lookahead, and it is the most common way bracket engines manufacture fake profit. Asserted in a test.
5. **Time stop** — `i − entry_idx >= time_stop_bars`, fill at `close[i]`.
6. **EOD square-off** — resolved by **wall-clock time, never bar index.** August has bars to 15:39 (385/day) vs July's 375/day, so any index-based rule is wrong on half the data.

Brackets are live from the entry bar itself. ATR for stop sizing is taken from bar `entry_idx − 1` — the last fully-closed bar before the fill — so the level is known before it is used. Exit prices get slippage via the existing `adjusted_price()`.

Signal-driven entries and reversals stay on the existing next-open path, untouched. Bracket exits are the **only** thing allowed to fill intrabar; that preserves the no-look-ahead guarantee exactly where it matters.

**Engine changes** (`quant/backtest/engine.py`): select `high`/`low` only when brackets are enabled (callers without OHLC keep working); **append** to `TRADE_COLUMNS`, never insert — `tests/test_phase05_backtest.py:66-70` indexes positionally. New columns: `exit_reason` (`signal|stop|target|trail|time|eod|end_of_data`), `mae`, `mfe`, `bars_held`, `r_multiple`. Optional per-signal `stop_price`/`target_price` columns override `ExitConfig` when `stop_mode="signal"` — **SMC strategies need structural stops** (beyond the sweep wick), not N×ATR, and this is what makes them expressible.

**Also new:** `quant/indicators/atr.py` (`true_range_expr`, `add_atr` with Wilder RMA, causal) and `quant/candles/session.py` (`filter_session`, `add_session_day`, `time_at_or_after`). Wire `filter_session` into `process_month` — this fixes August's 15:31–15:39 bars.

### 1.3 Re-run the existing 320 grid with correct units and brackets

```powershell
uv run pytest -q
uv run python scripts/run_research.py --year 2026 --month 7 --timeframes 5,15
```
**Gate on this before building anything else.** Two specific checks: `pct_closed_at_end` must drop to 0, and the +₹5,737/4-trade 15m cell must be re-examined without its ₹26,914 force-close artifact. Expected: it does not survive. That is a finding, and it is what justifies the rest.

---

## Phase 2 — Multi-instrument index history

**`quant/data/upstox.py`** — `UpstoxClient.__init__(self, settings=None, *, require_auth: bool = True)`. When `False`, skip `require_upstox_credentials()` and omit the `Authorization` header. Additive; `test_phase01_upstox.py` unaffected.

**New `quant/data/index_spot.py`:**
```python
INDEX_KEYS = {"NIFTY": "NSE_INDEX|Nifty 50", "BANKNIFTY": "NSE_INDEX|Nifty Bank",
              "SENSEX": "BSE_INDEX|SENSEX"}

def resolve_contract_specs(symbol) -> dict   # lot_size, tick_size from the LIVE instrument master
def download_index_month(symbol, year, month, *, out_root="data/raw/index", overwrite=False) -> dict
def download_index_range(symbol, start: date, end: date, **kw) -> list[dict]
```

**Contract specs are resolved from the instrument master, never hardcoded.** `UpstoxClient.fetch_instrument_master(exchange=...)` is already parameterized (`upstox.py:115`). This is the same mistake that produced `lot_size = 50`, and BANKNIFTY in particular has been revised repeatedly — do not write a literal into the plan or the code and hope. **Resolution is a hard precondition of Phase 6**: the sweep refuses to run for a symbol whose specs are unresolved, because a wrong lot size does not merely scale P&L, it changes which configs clear `maxDD < 10%` of fixed capital.

- One request per calendar month; `2022-01 → 2026-09` × 3 = **171 requests**. 0.4 s pacing, exponential backoff on 429/5xx, 3 retries — the current client has no rate limiting, retry, or 429 handling at all.
- Lands at `data/raw/index/<SYMBOL>/<YYYY-MM>/candles_1m.parquet` + `download_metadata.json` (URL, status, row count, sha256, `fetched_at`, `price_source`).
- **Resume rule:** skip iff the parquet exists AND `metadata.rows > 0` AND the month is fully past. The `rows > 0` clause is the direct fix for the three 0-row placeholder files.
- **Hard failure** if `rows == 0` for a month with known NSE trading days. Never write an empty parquet silently. Add the same guard to `download.py:168-184`.
- Sets `volume = 0`, `open_interest = 0`, `price_source = "index_spot_proxy"`.

**`scripts/download_index_history.py`** — `--symbols --start --end [--dry-run]`, idempotent, safe to re-run after a crash.

**Processing:** `process_month(*, symbol="NIFTY", asset_class="futures", ...)` deriving roots as `data/{raw,processed}/<asset_class>/<SYMBOL>/<YYYY-MM>/`; defaults keep every current call site and `test_phase02_processing.py` green. Add `filter_session()` before aggregation, and group by session date before `group_by_dynamic` (09:15 happens to be 5m/15m epoch-aligned today, but that is luck, not a guarantee). Relax `validate_dataset` with `expect_volume: bool = True` so `volume == 0` is not a failure on index spot.

**New `quant/data/store.py`** — `load_candles(symbol, timeframe, *, asset_class, start, end)` and `available_months(...)`. Research needs one continuous 4.7-year frame; nothing in the repo can build one today.

**Futures beyond July 2026** needs `/v2/expired-instruments/` + `UPSTOX_ANALYTICS_TOKEN` and possibly a paid plan. **Flagged high-risk; the plan assumes it is unavailable** and does not block on it. Optionally add a `basis` column (`futures_close − index_close` on overlapping days) to quantify how good the spot proxy is.

---

## Phase 3 — Fix the EMA strategy

**`quant/indicators/angle.py`** gains (existing `ema_angle_expr` untouched):
```python
def ema_slope_atr_expr(ema_column, atr_column="atr", *, lookback=1) -> pl.Expr:
    """(EMA[t] - EMA[t-k]) / (k * ATR[t]).  Units: ATR per bar.
    Dividing by k decouples the threshold from the lookback: under the legacy
    fixed-scale formula the SAME 30-degree threshold passes 0.55% of 1m/lb=1
    bars and 72.06% of 15m/lb=5 bars."""
```

**`quant/strategies/ema_9_15.py`** — `StrategyConfig` gains, with every existing field and default unchanged:
```python
angle_mode: Literal["fixed_scale", "atr_normalized"] = "fixed_scale"
atr_period: int = 14
slope_threshold_atr: float = 0.0    # 0.0 = gate off; the SWEEP picks this, not a shipped constant
```
`slope_threshold_atr` ships **neutral**. The percentile table above was measured on July 2026 NIFTY — 23 days that sit inside the train split — so it is sound evidence for the *invariance* claim but not a defensible default. Re-derive the percentile→threshold mapping on the full 2022–2024 train span once downloaded, across all three instruments, and record it in the run card.

Schema stability: still populate `angle` as `atan(slope_atr) × 180/π` so `Signal.angle`, `signal_events()` and the MCP tools are untouched; add `slope_atr` as a trailing column.

Also add `signal_mode="crossover_and_slope_and_htf"` — 15m entries confirmed by a 60m EMA-slope sign via `store.load_candles`. Cheap, and it directly addresses "3 of 9 walk-forward steps produce zero trades."

**Bug fix:** `quant/research/walk_forward.py:42` hardcodes `_PARAM_COLUMNS = {"fast_ema","slow_ema","angle_threshold","angle_lookback"}` and will `KeyError` on any new grid. Derive it from the grid keys actually passed in.

---

## Phase 4 — The new tuning space (staged and sampled, not cartesian)

`DEFAULT_GRID` stays frozen at 320 combos so `test_phase08_research.py` passes. Everything below is new.

**Stage 1 — entry logic, full cartesian (cheap):**
```python
STAGE1_EMA_GRID = {
    "fast_ema":            (5, 8, 9, 13, 21),
    "slow_ema":            (15, 21, 34, 55, 89),
    "angle_mode":          ("atr_normalized",),
    "slope_threshold_atr": (0.0, 0.10, 0.20, 0.30, 0.45),
    "angle_lookback":      (1, 3, 5),
    "signal_mode":         ("crossover_and_angle", "crossover_angle_and_trend"),
}
```
`fast_ema` keeps 9 and `slow_ema` keeps 15 so the incumbent stays in its own grid and can be ranked against the field. ~23 valid `fast<slow` pairs × 5 × 3 × 2 = 690 raw, **~575 after canonical de-dup**.

**Stage 2 — exits, Latin-hypercube sampled:**
```python
STAGE2_EXIT_GRID = {
    "stop_mode": ("atr",),           "stop_atr_mult": (0.75, 1.0, 1.5, 2.0, 3.0),
    "target_mode": ("none", "r_multiple"), "target_r_multiple": (1.0, 1.5, 2.0, 3.0),
    "trail_mode": ("none", "atr", "breakeven_then_atr"), "trail_atr_mult": (1.5, 2.5),
    "time_stop_bars": (0, 12, 30, 75),
    "session_start": ("09:15", "09:30"), "session_end": ("14:45", "15:10"),
    "eod_squareoff": ("15:20",),
}
```
Full cartesian is 7,680 — do not run it. Take **top-K = 6** Stage-1 entries × **LHS n = 128** = **768 trials**.

**Stage 3 — local refinement:** ±1 grid step on the 5 numeric axes around the Stage-2 winner, capped at 3⁵ = 243.

**Per (instrument, timeframe): ~575 + 768 + 243 ≈ 1,586 trials.** Timeframes {5m, 15m} (1m dropped per the economics), instruments ×3 → 6 cells → **~9,500 trials for the EMA family per round.**

**New `quant/research/sampling.py`:**
```python
def canonical_params(strategy_id, params) -> dict
    """Drop parameters made inert by a mode switch, so dedupe is by EFFECT, not by dict.
       e.g. slope_threshold_atr=0.0 -> drop angle_lookback;
            stop_mode='none' -> drop trail_* and target_r_multiple."""
def sample_combinations(grid, *, n, seed, method="lhs", constraints=()) -> list[dict]
def staged_search(stage_grids, *, top_k=6, budgets=(None,128,243), seed=...) -> Iterator[list[dict]]
```
Effect-based dedupe matters twice: it stops the sweep spending trials on configs identical to signal-reversal-only, and it keeps duplicate configs from inflating the `n_trials` that DSR is penalized by. Everything is seeded and deterministic.

---

## Phase 5 — Causal SMC primitives and the 5 strategies

### 5.1 Reimplement in Polars — do not wrap `smartmoneyconcepts`

Three independent reasons, the first disqualifying:

1. **Correctness.** `smc.swing_highs_lows(ohlc, swing_length=50)` is *centered* — "the highest high out of the swing_length candles **before and after**". `MitigatedIndex` (from `fvg`) and `BrokenIndex` (from `bos_choch`) are backward-annotated columns describing what happened *later*. Reading any of them at bar `i` peeks into the future. Escaping that by recomputing per bar is **O(n²)** and unusable across a 16-way sweep of 96k-bar frames.
2. **Dependencies.** The venv has `polars`, `numpy`, `httpx`, `fastmcp`, `pytest` — no `pandas`, `scipy`, `joblib`, or `smartmoneyconcepts`. The library is pandas-based and would pay a conversion on every trial. **This plan adds zero new dependencies.**
3. **Scope.** The primitives actually needed are small and each is causal by construction.

The library ([joshyattridge/smart-money-concepts](https://github.com/joshyattridge/smart-money-concepts)) is the reference for definitions, not a dependency.

**New `quant/indicators/structure.py`:**
```python
def add_swings(frame, *, left=3, right=3)      # pivot at p is EMITTED AT p+right, never at p
def add_fvg(frame)                              # 3-bar gap, known at bar i from i-2,i-1,i
def add_bos_choch(frame, *, close_break=True)   # close beyond an ALREADY-CONFIRMED pivot
def add_order_blocks(frame, *, displacement_atr=1.0)
def add_prev_day_levels(frame)                  # PDH/PDL/PDC from the previous COMPLETED session
def add_session_levels(frame, *, start="09:15", end="09:45", prefix="or")
def add_vwap(frame, *, anchor="session", fallback="typical_price")
```

**`tests/test_phase09_causality.py` is non-negotiable.** If only one test from this plan gets written, it is this one:
```python
@pytest.mark.parametrize("fn", [add_swings, add_fvg, add_bos_choch, add_order_blocks,
                                add_prev_day_levels, add_session_levels, add_vwap, add_atr])
def test_prefix_equals_full_frame(fn, july_1m):
    full = fn(july_1m)
    for i in SAMPLED_INDICES:                       # ~40 indices across the frame
        assert fn(july_1m.head(i + 1)).row(i) == full.row(i)
```
Nothing downstream is trustworthy without it.

### 5.2 Strategy registry

**New `quant/strategies/base.py`** — a `StrategySpec` protocol with `id`, `requires_volume`, `default_timeframes`, `param_space()`, `generate_signals(frame, params)` returning `timestamp, signal_type, [stop_price], [target_price]` plus diagnostics, and a `STRATEGY_REGISTRY`. The sweep planner **refuses** to schedule a `requires_volume=True` strategy against a `volume == 0` dataset — the mechanical guard against silently backtesting VWAP on index spot.

### 5.3 The five — all NSE/BSE 09:15–15:30 IST, single session, no US kill-zones

| # | Strategy | Entry | Stop / Target | Volume |
|---|---|---|---|---|
| **S1** | `smc_sweep_fvg` — **Liquidity Sweep + FVG Reversal** (ICT) | `low[i] < PDL` **and** `close[i] > PDL` (took liquidity, rejected); within `k ∈ [1,3]` bars a bullish 3-bar FVG forms with body ≥ `displacement_atr × ATR`; BUY on retrace into the FVG, valid `fvg_valid_bars` | Structural stop below the sweep low − 0.2 ATR; target `target_r_multiple × R` or the opposing PDH | No — spot OK |
| **S2** | `smc_ob_choch` — **Order Block + CHoCH Continuation** (SMC) | CHoCH = close beyond the last *confirmed* opposing pivot; OB = last opposing candle before the displacement leg; limit entry on retest, valid `ob_valid_bars` | Stop beyond the OB extreme; target next confirmed pivot or R-multiple | No — spot OK |
| **S3** | `ist_judas` — **Indian Opening Raid** (ICT Judas Swing, re-timed) | OR 09:15–09:45. In 09:45–10:30 a bar takes out `or_high` but closes back **inside** → SELL toward `or_low`. Mirrored for the low | Stop beyond the raid extreme + buffer; target `or_low`/`or_high` or R-multiple; EOD 15:20 | No — spot OK |
| **S4** | `orb_vwap` — **Opening Range Breakout + VWAP/ATR filter** | OR 09:15–09:30; BUY on close > `or_high` **and** > VWAP **and** `or_range >= min_or_atr × ATR` | Stop at `or_low` or `stop_atr_mult × ATR`; target R-multiple or `or_range × k`; EOD 15:20 | **Yes — futures only** |
| **S5** | `pdh_pdl_turtle_soup` — **PDH/PDL Sweep-and-Reverse** | `close[i] > PDH`, then within `revert_bars` a close back below PDH → SELL. Mirrored for PDL | Stop beyond the failed-breakout extreme; target PDC or the opposing PD level; time stop; EOD 15:20 | No — spot OK |

S1, S2, S3 and S5 are the ICT/Smart Money Concepts set. S4 is the widely-replicated ORB family from the Indian-market repos ([sushant1827/Trading_Strategies](https://github.com/sushant1827/Trading_Strategies), [aeron7/nifty-banknifty-intraday-data](https://github.com/aeron7/nifty-banknifty-intraday-data)).

S3 is the *correct* re-timing of the Judas Swing: NSE has one session, so the manipulation leg is the first hour, not a London kill-zone. S1 and S5 share primitives and are mechanically close to Turtle Soup, which has decades of published Indian-index evidence — and are the two whose base rates I measured (60% / 68% of sessions).

**S4 on index spot** runs with `fallback="typical_price"` (cumulative mean of typical price) and is written to the leaderboard with `price_source="index_spot_proxy"` and `vwap_is_proxy=True`. Screening only; it can never be promoted from spot.

**Rejected, with reasons:** ICT London/NY kill zones (meaningless on a single session); anchored-VWAP mean reversion (needs volume, and is a variant of S4); ORB+Gap-Go (subsumed by S3/S5 opening logic). Five *distinct* families beats eight correlated ones, because BH-FDR is applied across families.

---

## Phase 6 — Parallel harness and leaderboard (16 cores, zero new deps)

**New `quant/research/sweep.py`** — `Trial` dataclass (frozen, picklable), `param_hash()` via `run_card.hash_mapping`, module-level `run_trial(trial)`, `run_sweep(trials, *, workers, out_dir, chunk=64)` on `concurrent.futures.ProcessPoolExecutor`.

**Windows/spawn specifics — all mandatory:**
- Set `os.environ["POLARS_MAX_THREADS"] = "1"` **in the parent, before the pool is created**, so spawned children inherit it before importing polars. `pl.thread_pool_size()` is 16 here; without this, 16 workers × 16 threads = 256-way oversubscription and the sweep runs *slower* than serial.
- Pass candle **file paths**, never pickled DataFrames.
- `if __name__ == "__main__":` guard on every sweep entrypoint.
- Module-level `_FRAME_CACHE` in the worker so ~1,600 trials on one file read the parquet once.
- Crash-safe writes: one `part_<pid>_<chunk>.jsonl` per worker chunk, merged on read. Never concurrent-append to one file.

**Measured throughput on this machine:** 1m 44 ms/trial, 5m 8.1 ms, 15m 6.7 ms on 23 days → ~0.45 s/trial scaled to 4.7 years of 5m with brackets. **A ~10,000-trial round finishes in ~5 minutes on 16 cores.** Compute is not the bottleneck; statistical power is. Wall-clock for the campaign is dominated by the 171-request download and agent analysis, not the sweeps.

**New `quant/research/leaderboard.py`** — append-only, resumable. Path `data/results/leaderboard/<campaign_id>/round_<NN>/part_*.jsonl` → merged `leaderboard.parquet`.

Schema (one row per trial): `campaign_id, round, trial_id, strategy_id, param_hash, params_json, exits_json, symbol, price_source, timeframe, split, window_start, window_end, n_bars, trading_days, total_trades, winning_trades, losing_trades, win_rate, gross_pnl, net_pnl, avg_trade_pnl, profit_factor, expectancy, max_drawdown_pct, max_drawdown_value, sharpe, sortino, calmar, total_return_pct, avg_holding_periods, `**`pct_closed_at_end`**`, exit_reason_counts_json, daily_returns_json, lot_size, tick_size_rupees, slippage_mode, engine_version, strategy_version, cost_model_version, git_sha, config_hash, run_card_hash, seed, created_at, host, duration_ms, status, error`.

`pct_closed_at_end` is the artifact detector — it is what would have caught the ₹26,914 trade. `daily_returns_json` is required for DSR/PBO date alignment (`daily_returns_by_date` already exists for exactly this). `status ∈ {ok, error, skipped_min_trades, skipped_no_volume}`.

```python
def append_results(rows, *, campaign_id, round_no, out_dir) -> Path
def load_leaderboard(campaign_id, *, round_no=None) -> pl.DataFrame
def completed_trial_ids(campaign_id) -> set[str]      # resume / idempotency
def cumulative_trial_count(campaign_id) -> int        # DISTINCT param_hash -> DSR n_trials
```
Before dispatch, drop trials whose `trial_id` already exists with `status != "error"`.

---

## Phase 7 — The agent loop

**Hard rule: LLM agents never run backtests.** Compute is CPU-bound and belongs to the harness. Agents read aggregates and propose the next round.

```
Referee writes round_N/plan.json  (families, ranges, budget, seed)
  -> scripts/run_sweep.py --campaign C --round N --plan round_N/plan.json
  -> ProcessPoolExecutor (16 cores) -> part_*.jsonl -> leaderboard.parquet
  -> Analyst reads round_N/leaderboard.parquet          -> round_N/analysis.md
  -> Hypothesis agents x3 (PARALLEL)                    -> round_{N+1}/proposal_<family>.json
  -> Referee merges, enforces budget + stopping rule    -> round_{N+1}/plan.json
```

- **Analyst ×1** — reads only the aggregated leaderboard, never raw trade frames. Reports which families beat break-even; parameter-stability *plateaus* vs isolated spikes; regime attribution via the existing `analyse_regimes`; and flags any row with `pct_closed_at_end > 0` or `total_trades < MIN_TRADES`.
- **Hypothesis ×3, parallel**, one per family bucket: (a) EMA/trend, (b) SMC structural (S1, S2), (c) breakout/fade (S3, S4, S5). **Sandboxed** — proposed values must fall inside the pre-registered legal ranges in `protocol.py`, validated by JSON schema. A proposal outside them is *rejected* by the Referee, never silently clipped.
- **Referee ×1** — merges, enforces the round budget and the stopping rule, decides whether to unseal.

Round plan: **R1** EMA family across 3 instruments × {5m, 15m}; **R2** the 5 new families; **R3** local refinement of survivors, then the gate. Files under `agent/campaign/{protocol.md, ANALYST.md, HYPOTHESIS.md, REFEREE.md}`; state under `data/results/leaderboard/<campaign_id>/round_<NN>/`.

---

## Phase 8 — The promotion gate (run once, at the end)

Reuses the Phase-08b machinery, which is fully implemented and unit-tested but **has never been run against real results** — no run card, DSR, PBO or bootstrap output exists anywhere on disk.

All must hold:

1. `total_trades >= MIN_TRADES[split]` on train **and** validation
2. Validation `net_pnl > 0`, `profit_factor >= 1.3`, `max_drawdown_pct < 10`
3. `pct_closed_at_end <= 0.05` — kills the force-close artifact
4. `deflated_sharpe_ratio(...)` survives at 95%, with **`n_trials` = cumulative distinct `param_hash` across the whole campaign**, from `cumulative_trial_count()`
5. `bootstrap_sharpe_ci(...)` excludes zero
6. `probability_of_backtest_overfitting(...)` < 0.5 (CSCV)
7. `benjamini_hochberg(...)` at α = 0.10 **across the ≤6 strategy families only — not across instruments.** BANKNIFTY and SENSEX are ~0.9 correlated with NIFTY; cross-instrument agreement is a *robustness check, not 3× the statistical power*. Treating 3 instruments × 6 strategies as 18 independent tests would be exactly the p-hacking this gate exists to prevent.
8. `validate_parameter_search(...) → SearchValidation.credible is True`
9. **Futures confirmation** on 2026-07/08 at lot 65 / tick ₹0.10: net P&L per trade > **6.7 points** (or 8.4 if the 0.02% STT is confirmed)

Only then is the test split unsealed, run **once**, and reported.

### Two holes in the existing validator that must be fixed first

Both are in `quant/research/validate.py` and both currently **inflate** confidence:

- **`n_trials` must be cumulative**, not per-round. `expected_maximum_sharpe(n_trials, trial_sharpe_std)` scales the luck benchmark with trial count; passing one round's count when the campaign tried far more understates the bar.
- **Zero-trade trials deflate the benchmark.** The existing walk-forward already produces zero-trade steps. A zero-trade trial has no return variance → `sharpe_ratio(...)` returns 0.0; a pile of identical 0.0s **shrinks** `trial_sharpe_std`, which shrinks `expected_max_sharpe`, which makes DSR *easier* to pass. Add `min_trades: int = 0` to `validate_parameter_search` and filter `results` **before selection and before building `trial_sharpes`** — not as a post-hoc note on the winner.

Every promoted candidate gets a `run_card.py` SHA-256 run card. Output: `data/results/search/FINAL_REPORT.md` — leaderboard, per-candidate gate results, equity curves.

**If nothing passes, that is the reported result**, with the validation ranking and a diagnosis of which gate each candidate failed. The test set is not re-opened.

---

## Phase 9 — Surface it

Add to `_TOOL_FUNCTIONS` (`mcp/quant_server/server.py:655`; the HTTP bridge derives schemas via `inspect.signature`, so no TypeScript change): `list_strategies`, `read_leaderboard`, `campaign_status`. **Read-only** — agents observe, they never compute. Also fix `download_month_data`'s `out_dir` default (`server.py:233` writes `data/raw/futures/`, while `validate_dataset` at `:254` and `process_month_data` at `:280` read `data/raw/futures/NIFTY/` — a download via MCP cannot find its own file).

---

## Files

**New:** `quant/backtest/{market,exits}.py` · `quant/indicators/{atr,structure}.py` · `quant/candles/session.py` · `quant/data/{index_spot,store}.py` · `quant/strategies/base.py` · `quant/strategies/{smc_sweep_fvg,smc_ob_choch,ist_judas,orb_vwap,pdh_pdl_turtle_soup}.py` · `quant/research/{sampling,sweep,leaderboard,protocol}.py` · `scripts/{download_index_history,run_sweep,run_loop_round,promote_candidate}.py` · `agent/campaign/*.md` · `tests/test_phase09_{market,exits,angle,causality}.py` · `tests/test_phase10_{sweep,protocol}.py`

**Modified:** `quant/backtest/engine.py` (brackets, `exit_reason`, `MarketContext`) · `quant/indicators/angle.py` (+`ema_slope_atr_expr`) · `quant/strategies/ema_9_15.py` (3 additive fields) · `quant/research/{parameter_search,walk_forward,validate,baseline}.py` · `quant/processing/pipeline.py` · `quant/data/{upstox,download,validation}.py` · `mcp/quant_server/server.py`

**Reused unchanged:** `quant/backtest/{costs,metrics}.py` · `quant/research/{significance,multiple_testing,_stats,run_card,regime}.py` · `quant/candles/aggregation.py` · `mcp/quant_server/http_bridge.py`

## Verification

```powershell
uv run pytest -q                                    # all 13 existing files stay green
uv run pytest tests/test_phase09_causality.py -v    # THE gate — no primitive sees the future
uv run pytest tests/test_phase09_exits.py -v
uv run ruff check .

uv run python scripts/run_research.py --year 2026 --month 7 --timeframes 5,15   # Phase 1 re-run

uv run python scripts/download_index_history.py --symbols NIFTY --start 2022-01 --end 2022-03 --dry-run
uv run python scripts/download_index_history.py --symbols NIFTY,BANKNIFTY,SENSEX --start 2022-01 --end 2026-09
uv run python scripts/process_month.py --symbol NIFTY --asset-class index --year 2024 --month 3

uv run python scripts/run_sweep.py --campaign C2026-09 --round 1 --plan ...round_01/plan.json --workers 16
uv run python scripts/run_sweep.py --campaign C2026-09 --round 1 --resume    # must skip 100%, add 0 rows
uv run python scripts/promote_candidate.py --campaign C2026-09 --dry-run
```

**What must pass before believing any number:**
- Default `ExitConfig` reproduces the current engine bit-for-bit
- Prefix-equals-full-frame holds for every structural primitive
- A hand-checked bar containing both SL and TP exits at the **stop**
- A hand-checked gap-through fills at the **open**, not the stop level
- Trail level at bar `i` is computed from bars ≤ `i−1`
- EOD square-off is clock-based and works on the 385-bar August day
- `MarketContext` raises on `tick_size_rupees=10.0`; `lot_size` is not scaled
- `param_hash` is stable under key reordering; `--resume` adds zero rows
- `POLARS_MAX_THREADS=1` is set in the children
- `--split test` is refused without the seal hash

## Risks

| Risk | Severity | Mitigation |
|---|---|---|
| Subtle lookahead in SMC primitives | **High** — the #1 way SMC backtests manufacture edge | `test_phase09_causality.py`. Do not proceed past Phase 5 without it |
| Paise/rupee tick confusion | **High** — 200× slippage error reads as "strategy is bad" | Single conversion boundary + range guard in `MarketContext.__post_init__` |
| Futures history pre-July-2026 unavailable (Plus-gated) | Med | Plan assumes unavailable; index spot carries discovery, futures carries cost realism |
| 8-day futures test set | Med | Explicitly downgraded to a cost sanity check, never a statistical gate |
| Contract specs assumed rather than resolved | Med | Registry resolution is a hard precondition of Phase 6; sweep refuses unresolved symbols |
| STT 0.0125% vs 0.02% | Med | Moves break-even 6.7 → 8.4 points. Confirm against a contract note before the campaign |
| Windows spawn + Polars oversubscription | Med | `POLARS_MAX_THREADS=1` in the parent; asserted in `test_phase10_sweep.py` |
| Index spot is not tradeable | Med | Two-tier `price_source` on every row; promotion requires the futures leg |
| **The honest outcome may be "no edge"** | — | Built so that is a *result*, not a failure — with a per-gate diagnosis that says what to try next |

**New dependencies: none.** `concurrent.futures` is stdlib; no pandas, scipy, joblib, or `smartmoneyconcepts`.
