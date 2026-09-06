# Heikin-Ashi pattern-gated 9/15 EMA entries + a scale-out exit ladder

**Status: done.** Implemented in full (Phase 0 gate through the round
4/5-8 campaign and gate). Verdict: 0 of 6 (symbol, timeframe) cells pass
the statistical gate on the validation split -- no edge established. See
`plans/PROGRESS.md` (2026-09-07 entry) for the implementation log and
`data/results/leaderboard/C2026-09-EMA-SMC/EMA_HA_REPORT.md` for the
full results table.

## Context

The 3-round campaign (`C2026-09-EMA-SMC`, ~8,750 trials) finished with **0 of 36 cells passing the statistical gate**. The best defensible cell was `ema` on 15m (+₹6,305, PF 1.18) — positive, but not distinguishable from luck once penalised for the number of trials searched. The EMA entry fires on *every* crossover, and most crossovers are noise.

You have specified a much more selective entry, read off three annotated charts:

> Buy only when the candle on which the 9/15 EMA crosses is a **hammer / inverted hammer / doji** — a small body with a small high-to-low range — **on Heikin Ashi candles**.

And a managed exit instead of a single target:

> **SL = low of the entry candle.** Minimum target 1:1. At 1:1 sell 50%, at 1:2 sell another 25%, then **trail the rest at every next candle's low**. Fine-tune those quantities by backtesting.

Reading the three screenshots: blue = fast EMA, black = slow EMA; the green/red boxes are TradingView's long/short position tool. In all three the entry sits on a **small-bodied candle with wicks on both sides**, at or just before the crossover, with the red box (stop) reaching down to that candle's low. Image 2 is the short mirror — stop above the entry candle's high.

**Why this could work where the plain crossover did not:** a Heikin Ashi candle with a small body and wicks on both sides is, by HA's construction, a genuine loss of directional momentum — HA smooths the body, so a small HA body at a crossover means the last two bars disagreed. That is a real, causal filter, not a curve-fit parameter. It should cut trade count hard and lift per-trade edge.

**Two things to be honest about before spending the effort:**

1. **Scale-outs cannot create an edge — they redistribute one.** Selling 50% at 1R caps the right tail, which is where trend-following expectancy lives. It raises win-rate and smooths the equity curve, and it lowers raw expectancy on a positive-drift entry. If the entry has no edge, no ladder rescues it. All of the upside here has to come from the HA pattern filter.
2. **The filter's selectivity is also its main risk.** "Crossover AND small-body HA candle" is a conjunction of two uncommon events. The pre-registered minima are `MIN_TRADES = {train: 100, val: 30, test: 20}`. If the conjunction fires on, say, 8% of crossovers, 15m NIFTY will not clear 30 validation trades and the result is *untestable* regardless of how good it looks. **That is measured first, in Phase 0, before any engine surgery.**

The sealed 2026 TEST split stays sealed. This variant enters the same pre-registered protocol as everything else — adding a new family raises the deflated-Sharpe bar (√(2 ln N)), it does not lower it.

### Decisions taken

| Decision | Choice |
|---|---|
| Position size | **4 lots** (260 contracts) so 50/25/25 = 2/1/1 lots exactly, with `initial_capital` scaled ₹10L → ₹40L so `max_drawdown_pct` stays comparable to the 1-lot campaign |
| Timeframes | **5m and 15m** only — directly comparable to the existing campaign; 1m stays excluded on economics |
| Instruments | NIFTY, BANKNIFTY, SENSEX index spot (as before) |

---

## Phase 0 — Measure the base rate. This is a GATE.

**`scripts/measure_ha_pattern_base_rate.py`** (read-only, no leaderboard writes). On the train split (2022-01 → 2024-12) for 3 instruments × {5m, 15m}, report:

- total 9/15 crossovers
- of those, how many have a qualifying HA pattern within `k ∈ {0, 1, 2, 3}` bars
- swept across a small threshold matrix (`doji_body_pct ∈ {0.10, 0.20, 0.30}`, `small_range_atr ∈ {off, 0.8, 1.2}`)
- **projected val-split trade count** = train count × (245/740)

**Gate:** at least one (instrument, timeframe, threshold) cell must project **≥ 30 validation trades and ≥ 100 train trades**. If nothing clears it, stop and report — the options then are a wider `k`, looser body thresholds, or pooling instruments, and that is a decision to take with the numbers in hand rather than after building the engine. This is the same discipline that set the tiered `MIN_TRADES` in the first place (S3/S5 base rates were measured on 31 sessions before the minima were fixed).

Runtime: minutes. Do not skip it.

---

## Phase 1 — Heikin Ashi + candle-shape primitives

Neither exists anywhere in the repo (confirmed: zero hits for `heikin|doji|hammer|body_ratio|wick` across `quant/`, `mcp/`, `scripts/`, `tests/`). Both new modules follow the `quant/indicators/atr.py` shape exactly: frame-in / frame-out, `name=`/`prefix=` override, nulls during warm-up.

### `quant/indicators/heikin_ashi.py`

```python
def add_heikin_ashi(frame, *, prefix="ha_") -> pl.DataFrame
```
- `ha_close = (open + high + low + close) / 4` — plain expression.
- `ha_open` is recursive (`ha_open[t] = (ha_open[t-1] + ha_close[t-1]) / 2`). **Vectorise it, do not loop:** build a source series with `x[0] = (open[0] + close[0]) / 2` and `x[t] = ha_close[t-1]`, then `ha_open = x.ewm_mean(alpha=0.5, adjust=False)`. That is algebraically the exact HA recursion including its seed — assert this against a hand-computed 5-bar fixture.
- `ha_high = max(high, ha_open, ha_close)`, `ha_low = min(low, ha_open, ha_close)`.

### `quant/indicators/patterns.py`

```python
def add_candle_shape(frame, *, prefix="ha_", atr_column="atr_14", ...) -> pl.DataFrame
```
Prefix-parameterised so the identical code runs on HA columns or raw OHLC. Emits `body`, `range`, `upper_wick`, `lower_wick`, `body_pct` (= `body / range`, null-safe when `range == 0`), then the boolean flags:

| Flag | Rule |
|---|---|
| `is_doji` | `body_pct <= doji_body_pct` |
| `is_hammer` | `body_pct <= hammer_body_pct` **and** `lower_wick >= wick_ratio × range` **and** `upper_wick <= opp_wick_ratio × range` |
| `is_inverted_hammer` | mirror of the above |
| `is_small_range` | `range <= small_range_atr × ATR` (`small_range_atr = 0.0` disables) — this is your "small difference of high and low" clause, and it is a *separate* test from body ratio |

Both modules go into `tests/test_phase11_causality.py` using the existing `test_prefix_equals_full_frame` parametrisation from `tests/test_phase09_causality.py`. HA is recursive from bar 0, so it is causal — but it must be *proved* causal alongside the other primitives, not assumed.

Neither `quant/indicators/__init__.py` nor `quant/candles/__init__.py` re-exports anything, so no `__init__` edits are needed.

---

## Phase 2 — The strategy: `quant/strategies/ema_ha_pattern.py` (id `ema_ha`)

A new module, not an edit to `ema_9_15.py` — the incumbent stays byte-identical so the existing campaign results remain comparable. Reuses `add_ema`, `add_atr`, `add_ema_slope_atr`, and the same crossover expressions.

`StrategyConfig` (pydantic `BaseModel`, mirroring `ema_9_15.py:31`) adds:

| Field | Values | Meaning |
|---|---|---|
| `pattern_window_bars` | 0–3 | Crossover at bar `t` qualifies if a pattern fired at any bar in `[t−k, t]`. **`k=0` is your literal spec**; `k>0` covers the reading in image 3, where the small candle sits slightly *before* the visible cross. Let the sweep decide. |
| `pattern_set` | `any` / `doji_only` / `directional` | `directional` = hammer-or-doji for BUY, inverted-hammer-or-doji for SELL |
| `doji_body_pct`, `hammer_body_pct`, `wick_ratio`, `opp_wick_ratio`, `small_range_atr` | — | passed through to `add_candle_shape` |
| `stop_anchor` | `pattern_bar` / `signal_bar` | which bar's low defines the SL |
| `stop_reference` | `real` / `ha` | real OHLC low (default, tradeable) vs HA low (smoothed, what the chart shows) |
| `stop_buffer_atr` | 0.0–0.25 | pad below the low |

**Entry:** crossover at `t` **and** a qualifying pattern in the window **and** (optionally) the existing ATR-normalised slope gate. Signal at `t`'s close, fill at `t+1`'s open — unchanged, no look-ahead.

**Stop:** emitted as the existing **`stop_price` column** and consumed by `ExitConfig(stop_mode="signal")`. For LONG, `stop_price = low_of_anchor_bar − stop_buffer_atr × ATR`; mirrored for SHORT. **This needs zero engine work** — the SMC strategies already use exactly this path. `target_price` stays null; the ladder replaces the single target.

Registered via `register_strategy(StrategySpec(id="ema_ha", requires_volume=False, default_timeframes=("5m","15m"), ...))`, and **added to the module-level import block in `quant/research/sweep.py:51-56`** — on Windows, spawned workers only see strategies imported from inside `sweep.py` itself. Omitting this makes every trial fail with a `KeyError` that no single-process smoke test catches.

---

## Phase 3 — Scale-out exits in the engine

The engine is currently strictly all-or-nothing: `cfg.quantity` is one scalar and `close_trade` closes 100% (`quant/backtest/engine.py:301-334`). This is the only real surgery in the plan.

### The critical constraint: one row per *logical* trade

Emitting one trades-frame row per leg would silently corrupt, with nothing raising:

- `quant/backtest/metrics.py:104-127` — `total_trades = trades.height` triples; `avg_trade_pnl` falls ~3×; `profit_factor` (`:115-117`) partitions *gross* by each row's *net* sign, so a scratched runner and a winning scale-out of the same trade land on opposite sides.
- `quant/research/validate.py:240` — the pre-registered `MIN_TRADES` gate would be satisfied by leg inflation. **This is the worst one**: it is precisely the p-hacking `protocol.py` exists to prevent.
- `quant/research/sweep.py:221` — `pct_closed_at_end` becomes leg-weighted, so a force-closed runner reads 0.33 instead of 1.0 and slips past the `<= 0.05` artifact gate in `scripts/promote_candidate.py:68`.
- `quant/research/parameter_search.py:166` → `monte_carlo_permutation_test` — legs of one trade are **not exchangeable**; permuting them manufactures equity paths that cannot occur.

**So: one row per logical trade, with a volume-weighted exit price.** `metrics.py` then needs no changes at all.

### `quant/backtest/exits.py`

```python
@dataclass(frozen=True)
class ScaleLeg:
    at_r: float      # R-multiple that triggers this leg
    fraction: float  # fraction of the ORIGINAL position

# added to ExitConfig -- every default is a no-op:
scale_out: tuple[ScaleLeg, ...] = ()
after_leg1_stop: Literal["keep", "breakeven"] = "keep"
trail_after_leg: int = 0          # trail only once N legs have filled
trail_buffer_atr: float = 0.0
# TrailMode gains "prev_candle_extreme"
```
`ExitConfig.enabled` gains `or bool(self.scale_out)`. **`ScaleLeg` must be a frozen dataclass of plain floats** — `Trial` is pickled across process boundaries on Windows spawn.

### `quant/backtest/engine.py`

- **Lot quantisation.** Legs are sized in **lots, not contracts** — NIFTY's lot of 65 is indivisible. `lots_i = floor(fraction_i × position_size)`, remainder to the runner. Raise loudly if any configured leg quantises to 0 lots; never silently drop a leg.
- **State:** `remaining_qty`, `filled_legs: list[dict]`. `realized` accrues per leg so the equity curve is right *during* a trade.
- **Per-bar precedence** (extends the existing conservative convention in `exits.py:15-32`):
  1. Stop first — if hit, it closes the **entire remaining** position. Stop still wins ties.
  2. Otherwise, fill every unfilled leg whose `at_r` level the bar reaches, in ascending `at_r`. Several legs may fill in one bar; gap-through fills at the open.
  3. `after_leg1_stop="breakeven"` moves `sl_level` to `entry_price` — **effective from bar `i+1` only.** Do not re-test bar `i`'s own low against a stop that bar `i` itself just created.
  4. `trail_mode="prev_candle_extreme"`: on bar `i`, stop ratchets to `lows[i-1] − trail_buffer_atr × ATR` (LONG), monotonic. **Bar `i-1`, never bar `i`** — `_update_trailing_stop` (`engine.py:348-390`) already enforces exactly this discipline; the new mode slots into it.
- **`unrealized`** (`engine.py:444-448`) must use `remaining_qty`, not the scalar — otherwise the equity curve, and every equity-derived metric (Sharpe, drawdown, Calmar), is wrong.
- **`close_position` folds all legs into one row:** `exit_price` = Σ(qtyᵢ·pxᵢ)/Σqtyᵢ; `quantity` = the original full size; `gross_pnl` = Σ over legs; `exit_reason` = the *final* leg's reason; `closed_at_end = 1` only if the final leg was forced at end-of-data.
- **Costs — do not call `round_trip_costs` per leg**, it would charge the entry N times. Use the per-order helper that already exists: `cost_of_order(entry_price, full_qty, entry_side, cfg)` **once**, plus `cost_of_order(leg_px, leg_qty, exit_side, cfg)` **per leg** (`quant/backtest/costs.py:55-85`). The N × ₹20 flat brokerage + GST that this charges is real — each leg is a separate order — and it is a genuine cost of laddering that a naive implementation would hide.
- **Two new columns, `n_legs` and `exit_legs_json`, appended at the END** of both `TRADE_COLUMNS` (`engine.py:82-102`) and the schema dict (`engine.py:466-484`). `tests/test_phase05_backtest.py:66` indexes positionally — never insert.

### `quant/research/sweep.py`

`Trial` gains `position_size: int = 1` and `initial_capital: float | None = None`, threaded into `BacktestConfig`. **`position_size` must go into the `market` dict fed to `trial_param_hash`** (`sweep.py:102`) — otherwise a 1-lot and a 4-lot config collide on the same hash and one silently overwrites the other.

### `quant/research/sampling.py`

Extend the canonicaliser (`sampling.py:75-100`) to prune inert params, alongside the existing `stop_mode`/`trail_mode` pruning:
- `pattern_set="doji_only"` → drop `wick_ratio`, `opp_wick_ratio`, `hammer_body_pct`
- `small_range_atr=0.0` → drop it from the hash
- `trail_mode="none"` → drop `trail_buffer_atr`, `trail_after_leg`
- **Quantise leg fractions to lots before hashing.** At 4 lots, `fraction=0.30` and `fraction=0.33` both floor to 1 lot — behaviourally identical trials that would otherwise hash as distinct, breaking `--resume` dedup and inflating the `cumulative_trial_count` that the deflated Sharpe is penalised against.

---

## Phase 4 — Round 4 campaign

**`scripts/run_round4.py`**, modelled on `run_round1.py`, campaign `C2026-09-EMA-SMC`, `--round 5`. Staged, not cartesian:

- **Stage 1 — entry** (full cartesian, cheap; fixed 1R/2R/25% ladder): `fast_ema ∈ {5,9,13}`, `slow_ema ∈ {15,21,34}`, `pattern_window_bars ∈ {0,1,2,3}`, `pattern_set ∈ {any, doji_only, directional}`, `doji_body_pct ∈ {0.10,0.20,0.30}`, `wick_ratio ∈ {0.40,0.55}`, `small_range_atr ∈ {0.0,0.8,1.2}`, `slope_threshold_atr ∈ {0.0,0.15}`. Constrained `fast < slow`, deduped by effect.
- **Stage 2 — the ladder**, Latin-hypercube sampled (this is the "fine-tune the quantity numbers" ask), on the top-6 Stage-1 entries: `leg1_at_r ∈ {0.8,1.0,1.2}`, `leg1_frac ∈ {0.25,0.50,0.75}`, `leg2_at_r ∈ {1.5,2.0,3.0}`, `leg2_frac ∈ {0.0,0.25}`, `after_leg1_stop ∈ {keep, breakeven}`, `trail_after_leg ∈ {1,2}`, `trail_buffer_atr ∈ {0.0,0.15}`, `stop_anchor`, `stop_reference`, `stop_buffer_atr ∈ {0.0,0.10,0.25}`. `eod_squareoff="15:15"` fixed (**not** 15:20 — see `exits.py:34-48`).
- **Stage 3** — ±1 grid step around the Stage-2 winner.

Selection on **train** only. The **validation** split is scored **once** per surviving cell, then `scripts/run_round3.py`'s report builder is reused for a per-strategy × per-timeframe comparison including the incumbent `ema` family, so you can see directly whether the HA gate beat the plain crossover. Baseline to beat: **`ema` 15m, +₹6,305, PF 1.18**.

Then `scripts/promote_candidate.py --split val` for the full gate. **TEST stays sealed.**

---

## Files

**New:** `quant/indicators/{heikin_ashi,patterns}.py` · `quant/strategies/ema_ha_pattern.py` · `scripts/{measure_ha_pattern_base_rate,run_round4}.py` · `tests/test_phase11_{heikin_ashi,patterns,scale_out,causality}.py`

**Modified:** `quant/backtest/exits.py` (`ScaleLeg`, 4 fields, new trail mode) · `quant/backtest/engine.py` (partial fills, per-leg costs, 2 appended columns, `remaining_qty` mark-to-market) · `quant/research/sweep.py` (`Trial.position_size`/`initial_capital`, strategy import, param hash) · `quant/research/sampling.py` (canonicaliser)

**Deliberately untouched:** `quant/strategies/ema_9_15.py`, `quant/backtest/metrics.py`, `quant/backtest/costs.py`, `quant/research/protocol.py`.

## Verification

```powershell
uv run pytest -q                                    # all 288 existing tests stay green
uv run ruff check .

# Phase 0 GATE -- do this before anything else
uv run python -m scripts.measure_ha_pattern_base_rate

uv run pytest tests/test_phase11_causality.py -v    # HA + patterns see no future
uv run pytest tests/test_phase11_scale_out.py -v

uv run python -m scripts.run_round4 --workers 14
uv run python -m scripts.promote_candidate --campaign C2026-09-EMA-SMC --split val
```

**Named tests that must exist and pass** — each one guards a specific way this could silently produce fake profit:

- `ExitConfig(scale_out=())` reproduces today's engine **bit-for-bit** on the existing fixtures (this is what keeps all 288 tests green).
- HA recursion matches a hand-computed 5-bar fixture, including the `(open[0]+close[0])/2` seed.
- Prefix-equals-full-frame for `add_heikin_ashi` and `add_candle_shape`.
- A bar containing **both** the stop and a leg's target exits **entirely at the stop**.
- A gap-through the 1R level fills that leg **at the open**, not at the level.
- The `prev_candle_extreme` trail on bar `i` uses `low[i-1]`. **Mutation-test this** — reintroduce the `low[i]` lookahead and confirm the test fails. A trailing-stop assertion that passes against the buggy code is worthless; that exact vacuous-test trap already bit this project once.
- Breakeven-after-leg-1 does not exit on the same bar that triggered leg 1.
- 3 legs produce **1** trades-frame row, `quantity` = full size, `exit_price` = the volume-weighted average, and `total_trades` counts **1**.
- Leg costs = 1 entry order + N exit orders — assert the exact rupee figure so a `round_trip_costs`-per-leg regression is caught.
- `position_size=1` with a 50/25/25 ladder **raises**, and does not silently trade a partial ladder.
- `param_hash` differs between `position_size=1` and `position_size=4`; two fractions quantising to the same lot count hash the **same**.
