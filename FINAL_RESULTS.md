# Final Results — EMA Tuning, SMC Strategies, and the HA-Pattern Ladder

**Bottom line: no strategy tested — the fixed/re-tuned 9/15 EMA, the 5
new Smart-Money-Concepts/ICT strategies, or the Heikin-Ashi
pattern-gated entry with the 50/25/25 scale-out ladder you specified —
clears a pre-registered statistical bar for a real edge on NIFTY,
BANKNIFTY, or SENSEX. This is reported as the honest result of the
protocol, not a failure of it: every family was measured the same
rigorous way, and several individually look profitable in raw P&L right
up until that same rigor is applied.**

Nothing here should be traded live. Below is what was built, what was
run, and exactly why each candidate fell short — so the reasoning is
checkable rather than a black-box "no."

---

## 1. What was asked, and what was built

You asked to (a) fix the underperforming 9/15 EMA strategy, (b)
re-tune the ~300 existing parameter variations, (c) add 5 well-known
Indian-market-adapted SMC/ICT strategies, (d) automate a parallel
backtest search across historical months, and later (e) add a much more
selective HA-candlestick-pattern entry filter with a specific
50%/25%/25% scale-out exit ladder.

All of it was built:

- **Diagnosed and fixed 5 real defects** in the original EMA strategy:
  an angle filter that was 131× more/less selective depending on
  timeframe (fixed with an ATR-normalized slope), an engine with no
  stop-loss/target/EOD-close at all, wrong contract lot size (50 vs the
  real 65) and tick size (a paise/rupee unit bug that would have
  inflated slippage ~200×), and a data set of only 31 trading days.
- **Backfilled 2022–2026 minute data** for NIFTY, BANKNIFTY, and SENSEX
  index spot (171 months, ~1.3M rows) so the search has real sample
  size instead of one month.
- **Added bracket exits** to the backtest engine (stop-loss,
  take-profit, trailing stop, time-stop, end-of-day square-off) — all
  strategies below need this, and it didn't exist before.
- **Added 5 new strategies**, all NSE/BSE-session-adapted SMC/ICT
  concepts: liquidity-sweep + fair-value-gap reversal, order-block +
  change-of-character continuation, an opening-range "Judas swing" raid
  fade, opening-range-breakout + VWAP, and PDH/PDL sweep-and-reverse
  ("Turtle Soup").
- **Built a parallel search harness**: a leaderboard schema, a
  Windows-safe multi-core sweep runner, staged parameter sampling
  (entry → exits → local refinement), and — critically — a **pre-registered
  statistical gate** (deflated Sharpe ratio, bootstrap confidence
  interval, profit factor, drawdown, and a check that catches
  force-close artifacts) so that a "good-looking" backtest number is
  never taken at face value.
- **Ran a 3-round campaign** (~8,750 trials) across all 6 strategies ×
  3 instruments × 2 timeframes, with a train/validation/test split and
  the 2026 test year **sealed and never opened**.
- **Then, per your later request**, added a completely new entry
  filter — a 9/15 EMA crossover gated on a Heikin-Ashi doji/hammer/
  inverted-hammer pattern (matching the three chart screenshots you
  provided) — and a genuine partial scale-out engine (sell 50% at 1R,
  25% at 2R, trail the remaining 25% at each new candle's low), then
  ran a second, equally rigorous 3-stage search + validation on it.

---

## 2. Round 1–3 results: EMA family + 5 SMC/ICT strategies

Every strategy's own best train-split configuration, scored **once**
on the untouched 2025 validation year:

| Strategy | Best cell | Validation net P&L | PF | Trades | Gate |
|---|---|---|---|---|---|
| `ema` (fixed/re-tuned) | 15m | **+₹6,305** | 1.18 | 32–172/cell | fail |
| `pdh_pdl_turtle_soup` | BANKNIFTY 15m | +₹80,893 (train looked much better) | 1.61 | 88 | fail |
| `smc_ob_choch` | NIFTY 15m | +₹5,277 | 1.28 | 20 | fail |
| `ist_judas`, `orb_vwap` | — | negative on nearly every cell | — | — | fail |

**0 of 36 (strategy, symbol, timeframe) cells passed the full gate.**
The `ema` family on 15m was the most defensible-looking result (modest
positive P&L, reasonable trade count across all 3 instruments) but
still failed on deflated Sharpe / bootstrap CI once penalized for the
size of the search. Full table:
`data/results/leaderboard/C2026-09-EMA-SMC/FINAL_REPORT.md`.

---

## 3. HA-pattern + scale-out ladder results (this session)

Per your instructions, the entry now requires **both** a 9/15 EMA
crossover **and** a small-bodied Heikin-Ashi candle (doji, hammer, or
inverted hammer) at or just before the cross. The exit is a genuine
ladder: stop at the entry candle's real low/high, 50% off at 1R, 25%
more at 2R, and the final 25% trailed at each new candle's low — sized
at 4 lots (2/1/1) so the 50/25/25 split lands on whole lots, with
capital scaled to ₹40L to match.

A 3-stage search (entry logic → ladder/stop tuning → local refinement,
24,190 trials total, 0 errors) produced this validation-split result:

| Symbol | TF | Net P&L | PF | Trades | Win rate | Sharpe | Max DD | Gate |
|---|---|---|---|---|---|---|---|---|
| BANKNIFTY | 15m | −₹85,519 | 1.19 | 247 | 36.8% | −0.22 | 11.7% | fail |
| NIFTY | 15m | −₹156,418 | 1.00 | 100 | 40.0% | −0.83 | 8.3% | fail |
| SENSEX | 15m | −₹31,826 | 1.18 | 98 | 39.8% | −0.12 | 5.6% | fail |
| **BANKNIFTY** | **5m** | **+₹242,841** | **1.92** | 72 | 41.7% | 1.29 | 2.6% | **fail** |
| NIFTY | 5m | −₹131,585 | 1.06 | 112 | 38.4% | −0.63 | 5.3% | fail |
| **SENSEX** | **5m** | **+₹89,738** | **1.43** | 196 | 38.8% | 0.39 | 7.5% | **fail** |

**4 of 6 cells flip negative on validation** despite strong train-split
numbers (PF 1.35–1.7 there) — the classic overfitting signature: the
search found configurations that fit the training years' noise, not a
real pattern.

**The 2 cells that stay positive are the interesting ones and are worth
explaining in full, because they pass every ordinary check:**
positive net P&L, PF well above 1.3, drawdown under 10%, no
force-close artifacts, 72–196 trades. They fail on exactly the two
checks designed to catch exactly this: with **19,714 cumulative
distinct configurations** tried across this campaign, the deflated
Sharpe ratio asks "is this result better than the best of 19,714 random
tries would look by chance?" — and the answer is no (deflated Sharpe
≈0.00001–0.12, nowhere near the 0.95 bar). Independently, a bootstrap
resample of each cell's own daily returns gives a confidence interval
that **includes zero** (e.g. BANKNIFTY 5m: [−0.71, 3.01]) — meaning the
data itself isn't precise enough to rule out "this is a lucky sequence
of trades," even setting the search size aside entirely.

**Verdict: 0 of 6 cells pass. No edge established for the HA-pattern
entry either.** Full table with per-cell failed-check detail:
`data/results/leaderboard/C2026-09-EMA-SMC/EMA_HA_REPORT.md`.

---

## 4. Why "no edge" is the right way to read this — not a shrug

Three independent things had to be true simultaneously for a strategy
to be reported here as real, and none of the 42 (36 + 6) cells tested
across both campaigns cleared all three:

1. **It has to make money net of realistic Indian-futures costs**
   (brokerage, STT, exchange charges, stamp duty, GST, slippage) — most
   candidates never got past this.
2. **It has to survive being one of thousands of things tried.** The
   more configurations a search tests, the more likely *something*
   looks good by pure chance — the deflated Sharpe ratio is the
   correction for exactly that, and it is why the 2 promising HA-ladder
   cells still failed: they were the best of ~20,000 tries, and the
   best of 20,000 coin flips looks impressive too.
3. **The result has to be precise enough to rule out luck at all** —
   the bootstrap confidence interval check. A strategy with only ~70–200
   trades simply doesn't generate enough independent data to be
   confident its Sharpe ratio is really positive, even before asking
   whether it survived a big search.

Every one of these checks was written down **before** any result was
looked at (`quant/research/protocol.py`), and the 2026 test year was
never opened at any point in either campaign — so there is no way this
verdict could have been massaged after the fact.

---

## 5. What this means practically

- **Do not trade any of these configurations live.** None of them
  demonstrated a statistically credible edge; the ones with the best
  raw numbers (BANKNIFTY 5m and SENSEX 5m on the HA-pattern ladder) are
  the most tempting to look at and precisely the ones the gate was
  built to catch.
- The infrastructure built here (data, engine, strategies, statistical
  gate, campaign harness) is reusable — if you want to test a
  genuinely different idea (a different market regime filter, a
  volume/options-flow signal, a different session-timing hypothesis),
  it can be run through the same rigorous pipeline quickly.
- If you want to keep exploring the HA-pattern idea specifically, the
  honest next steps would be: (a) get real (non-proxy) intraday volume
  or options data to add a genuinely new information source rather than
  another price-shape filter, since price-only patterns on the same 3
  indices are largely exhausted by this search; or (b) test the idea on
  a market/instrument this specific search never touched, since a
  well-motivated idea applied to *fresh* data doesn't inherit this
  campaign's trial count.

---

## 6. Where everything lives

| What | Where |
|---|---|
| Original plan (EMA fix + 5 SMC strategies) | `plans/2026-09-06-ema-tuning-and-smc-strategies.md` |
| HA-pattern + ladder plan | `plans/2026-09-06-ema-ha-pattern-scale-out.md` |
| Full implementation log | `plans/PROGRESS.md` |
| Round 1–3 full results table | `data/results/leaderboard/C2026-09-EMA-SMC/FINAL_REPORT.md` |
| HA-pattern ladder full results table | `data/results/leaderboard/C2026-09-EMA-SMC/EMA_HA_REPORT.md` |
| Pre-registered protocol (splits, gate thresholds) | `quant/research/protocol.py` |
| Test suite | 315 passing, ruff clean (4 pre-existing, unrelated failures documented in `plans/PROGRESS.md`) |

**Campaign totals: ~32,940 backtests run across both campaigns, 0
compute errors, the 2026 test split still sealed and unopened.**
