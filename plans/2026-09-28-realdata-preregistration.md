# Pre-registration — Campaign C2026-09-REALDATA

**Written 2026-09-28, before any feature–return relationship in this file
was computed.** Sealed by SHA-256 at the campaign's first scoring run.
Any later edit is appended in a dated section, never made in place.

---

## 0. The request, and what "positive" is allowed to mean

The user asked to train and test on the real NIFTY futures data
(`data/raw/futures/NIFTY`, 31 sessions with volume and OI) together with
the past data, to find more real data on the web if results disappoint,
to fine-tune, and "not to stop unless we gain positive results."

Tuning until *something* is positive always succeeds, including on noise;
that is how the prior campaign's +₹2.4L cells arose and then failed
out-of-sample. The user also asked, earlier, not to overfit. Both
instructions are honoured by the following rules, fixed now:

1. **"Positive" means positive on data the tuning never touched.** No
   in-sample, design-period or tuned number is ever reported as the
   result.
2. **The holdout is opened once.** A failed holdout is reported as
   failed and is never reopened, re-split or re-scored with a changed
   model.
3. **Persistence goes to the future.** Every iteration after the
   holdout is scored only on a forward paper-trading log that starts on
   **2026-09-28** — the one holdout that can honestly keep growing.
4. **Every configuration scored on any out-of-sample window increments
   the trial counter `N`,** which the deflated Sharpe ratio is computed
   against.

## 1. Data (all real; provenance recorded)

| ID | Source | Content | Coverage |
|---|---|---|---|
| D1 | disk + Upstox v3 | NIFTY futures 1-minute OHLCV + OI | 2026-07-01 → 2026-09-25 (62 sessions) |
| D2 | NSE F&O bhavcopy | NIFTY futures (all expiries) daily OHLC, settle, contracts, turnover, OI; NIFTY options OI/volume by strike | 2016-01-01 → 2026-09-25 |
| D3 | NSE participant-wise OI | FII / DII / Pro / Client index-futures and index-options long & short | 2012-01-02 → 2026-09-25 |
| D4 | Upstox v3 | India VIX daily | 2009-03-02 → 2026-09-25 |
| D5 | Upstox v3 | NIFTY index spot daily | 2005-01-03 → 2026-09-25 |

D1 is built exactly as the disk data already is: the Aug-2026 contract for
2026-07-01 → 07-31 (`data/raw/futures/NIFTY/2026-07`), then the Sep-2026
contract from 2026-08-03 (disk for 08-03 → 08-12, Upstox v3 for
08-13 → 09-25). Bars stamped after 15:29 are post-close prints and are
dropped.

## 2. Timing rule — no publication leak

Bhavcopy and participant OI are published **after** the close of day *t*.
Therefore, for **every** feature (including VIX and price, for uniformity):

- signal computed from data through day *t*;
- position entered at the **settlement close of day t+1**;
- the position earns **close t+1 → close t+2**.

The ML target for a day-*t* feature row is the continuous-futures return
**close t+1 → close t+2** — the return the fill actually earns.

Settlement close is NSE's last-30-minute VWAP; a VWAP execution over
15:00–15:30 approximates it, which is why it is the fill price.

## 3. Continuous futures and costs (D2)

- **Held contract:** near month, read from `EXPIRY_DT`/`XpryDt` (never
  computed — the expiry weekday changed during the sample). **Roll at the
  settlement close of the 3rd trading session before expiry** into the
  next month.
- **Returns** are computed within one contract (settle t-1 → settle t of
  the same contract); no back-adjustment. The real basis is therefore
  inside the returns, so **no modelled carry** is charged (`r−q = 0`).
- **Roll cost:** one round trip at every contract switch for **any
  non-zero exposure, long or short**.
- **Benchmark:** buy-and-hold of the same continuous series, net of the
  same roll costs.
- **Cost schedule per leg** (verified 2026-09-28; sources in §9):

| Component | Rate |
|---|---|
| STT, sell leg | 0.01% to 2023-03-31 · 0.0125% to 2024-09-30 · 0.02% to 2026-03-31 · **0.05% from 2026-04-01** |
| Exchange (NSE futures) | 0.0019% to 2024-09-30 (conservative; the source gives 0.00183% just before the change) · 0.00173% after |
| Stamp duty, buy leg | 0.002% |
| SEBI fee | 0.0001% |
| GST | 18% of (brokerage + exchange + SEBI) |
| Brokerage | ₹20 per order |
| Slippage | 1 tick per leg |

Round trip ≈ 2.1 bps (to 2023-03) → 2.3 → 3.0 → **~6.0 bps from 2026-04-01**.

## 4. Units (traps named in advance)

- Futures OI is in **units**; traded volume is in **contracts**; lot size
  differs across expiries on the same day. Volume/OI features use
  **notional** (`value_rs`, `oi × settle`) aggregated **across all
  expiries** (near-month OI collapses in expiry week from rollover, which
  is mechanics, not information).
- Participant OI is in contracts summed over all index futures — only
  **ratios** are used.

## 5. Phase 1 — intraday on D1 (sanity check, not a promotion route)

- **P1a / P1b:** the prior campaign's own frozen NIFTY `orb_vwap`
  configurations, **re-run unchanged** except that VWAP is now real:
  - 5m: `{"atr_period":14,"min_or_atr":1.5,"or_minutes":30,"require_vwap":true}`
  - 15m: `{"atr_period":14,"min_or_atr":0.5,"or_minutes":30,"require_vwap":true}`
  (In that campaign `require_vwap` true/false gave identical results —
  the zero-volume VWAP proxy never bound. Real VWAP can.)
- **P1c:** one intraday ML model — gradient boosting on 5-minute bars
  (returns, distance to real VWAP, relative volume, OI change, time of
  day), fitted on 2026-07-01 → 08-12 only, fixed hyper-parameters
  (`max_depth=3, learning_rate=0.05, max_iter=200`), long/short by
  sign of predicted return with a 1-bps dead-band, flat by 15:15.
- Windows reported: **A** 07-01 → 08-12 (the user's 31 sessions),
  **B** 08-13 → 09-04, **C** 09-07 → 09-25. P1a/P1b are frozen, so all
  three windows are out-of-sample for them; P1c is fitted on A.
- Costs: the 0.05% STT regime applies to every D1 session.
- `N_phase1 = 3`. Whatever it shows, 62 sessions is reported as
  **underpowered**.

## 6. Phase 2 — daily, on the new information (D2–D5)

**Design period** 2016-01-01 → 2022-12-31 (2016 is warm-up).
Walk-forward inside it: fit on an expanding window from 2017-01-01,
predict one calendar year ahead, for OOS years **2019, 2020, 2021, 2022**.
**Holdout** 2023-01-02 → 2026-09-25, opened once (§0.2).

### 6.1 Features (sign expected in advance; z-scores trailing only)

| Feature | Definition | Expected sign |
|---|---|---|
| `fii_lr_z` | FII index-futures long/(long+short), z vs trailing 252 | + |
| `fii_lr_d5` | 5-session change in that ratio | + |
| `cli_lr_z` | Client ratio, z vs 252 | − |
| `pro_lr_z` | Pro ratio, z vs 252 | + |
| `fii_opt_z` | FII index options (call L − call S − put L + put S)/(sum), z vs 252 | + |
| `pcr_z` | NIFTY options total put OI / call OI (all expiries), z vs 252 | + |
| `vix_z` | India VIX, z vs 252 | + |
| `vix_d5` | 5-session log change in VIX | + |
| `buildup` | sign(fut return) × 1[Δ total OI notional > 0] | + |
| `oi_d5` | 5-session % change in total futures OI notional | two-sided |
| `basis_z` | annualised near-month basis over spot, z vs 252 | + |
| `turn_z` | futures notional turnover (all expiries), z vs 60 | two-sided |
| `ret1` | continuous-futures return on day *t* | two-sided |

### 6.2 Stages

- **A — information test (design period):** Spearman IC of each feature
  vs the §2 target, Newey–West t-stat, Benjamini–Hochberg at q = 0.10
  across the 13 features. Diagnostic only; not a trade.
- **B — rules:** for each feature, `e = sign(z)` (long/short) and
  `e = 1[z > 0]` (long/flat); `buildup` uses its value. Scored on the
  design OOS years.
- **C — ML:** L2 logistic regression (`C = 1`) and gradient boosting
  (`max_depth=3, lr=0.05, max_iter=200`) on all features; standardisation
  fitted inside each training window; long/short and long/flat.
- **D — fine-tuning (design period only):** z-window {126, 252},
  threshold {0, 0.5}, holding {1, 5} sessions, logistic `C` {0.1, 1, 10},
  GBM depth {2, 3} × lr {0.03, 0.1}. **Every setting counts in `N`.**
- **E — selection:** at most **three** finalists by design-OOS net Sharpe
  (best rule, best ML, one combination), frozen before the holdout.
- **F — holdout:** the finalists only, once.

## 7. Verdict tiers (fixed now)

- **CREDIBLE** — holdout net return > 0; holdout Sharpe > buy-and-hold on
  the same series; pooled OOS (2019–2022 walk-forward + holdout)
  block-bootstrap CI excludes zero (vs 0 for long/short, vs buy-and-hold
  for long/flat); deflated Sharpe at the final `N` ≥ 0.95.
- **PROMISING** — holdout net > 0 and beats the benchmark on the point
  estimate, but a CI includes zero or DSR < 0.95.
- **FAIL** — anything else. Reported as failed; §0.2 applies.

**Power, stated in advance:** ~930 holdout sessions give a Sharpe SE of
~0.52, so only SR ≳ 1.0 can show a CI excluding zero; pooled OOS
(~1,930 sessions) needs SR ≳ 0.7. A true SR of 0.5 will most likely land
in PROMISING or FAIL regardless of being real.

## 8. Disclosures

1. 2025–2026 NIFTY price outcomes were seen in campaign C2026-09-LOWTURN.
2. The 2026-09-07 → 09-25 price path was printed during data validation
   (not its relation to any feature).
3. No relationship between any §6.1 feature and returns has been
   computed before this file.
4. C2026-09-LOWTURN has two defects found while preparing this campaign,
   corrected separately: its code filled at close *t* while its
   pre-registration said close *t+1*, and it charged 0.02% STT after
   2026-04-01 instead of 0.05%.

## 9. Sources for the cost schedule

- STT 0.01% → 0.0125% from 2023-04-01; → 0.02% from 2024-10-01:
  [Wikipedia — Securities Transaction Tax](https://en.wikipedia.org/wiki/Securities_Transaction_Tax),
  [ICICI Direct](https://www.icicidirect.com/research/equity/finace/new-stt-rules-in-futures-and-options-trading)
- STT 0.02% → 0.05% from 2026-04-01:
  [Angel One](https://www.angelone.in/news/market-updates/stt-hike-on-f-o-trade-effective-today-april-1-check-revised-stt-on-nifty-50-lot),
  [ICICI Direct — Budget 2026](https://www.icicidirect.com/futures-and-options/articles/stt-changes-in-budget-2026-what-f-o-traders-need-to-know)
- Exchange charge 0.00183% → 0.00173% from 2024-10-01:
  [Zerodha Z-Connect](https://zerodha.com/z-connect/business-updates/revision-in-exchange-transaction-charges-and-securities-transaction-tax-from-october-1-2024)

---

# AMENDMENT 1 — 2026-09-28, after design stage E, BEFORE the holdout is opened

Recorded after the finalists were frozen (`finalists.json`) and before any
holdout return was computed. Every change below makes the gate *stricter*
or adds reporting; none changes a finalist.

**A1.1 Stricter CREDIBLE gate for all finalists.** All three finalists are
net long on the design sample (mean net exposure: FII rule +0.54, GBM
+0.20, blend +0.37), so a vs-zero test lets 2023–24 beta carry them.
CREDIBLE now requires the pooled out-of-sample block-bootstrap CI to exclude
zero **both vs zero and vs buy-and-hold**, in addition to §7's other
conditions. (Originally: vs B&H for long/flat, vs zero otherwise; the blend
would have been tested only vs zero.)

**A1.2 Holdout-only statistics are reported first.** The pooled CI (§7)
includes 2019–22, the sample the finalists were selected on, so it stays
the gate but is not the headline. Added to the output: holdout-only CIs vs
zero and vs B&H, and a paired block-bootstrap CI of the Sharpe
*difference* (strategy − B&H) on the holdout.

**A1.3 Deflated Sharpe trial set excludes the benchmark row.**

**A1.4 Weekend special sessions** (Diwali Muhurat 2016-10-30, 2019-10-27,
2020-11-14; Budget day 2020-02-01, and any later ones) are treated as
absent throughout, design and holdout alike, so the design panel's row
count cannot change between stages. Two genuine NSE archive gaps are also
absent: bhavcopy 2021-03-30 and participant OI 2016-02-10.

**A1.5 Design-period diagnostics seen before this amendment** (reported,
not gates):
- no §6.1 feature passes Benjamini–Hochberg at q = 0.10; the strongest,
  `pro_lr_z`, has the wrong sign (IC −0.067, p = 0.011);
- the FII-rule finalist's design edge is concentrated in the COVID window:
  +27.5% over 2020-02-15 → 04-30 against B&H −19.4%, and ex-COVID Sharpe
  1.22 vs B&H 1.04;
- GBM label-permutation placebo: real 1.63 vs placebo mean 0.37 (sd 0.52,
  0 of 20 ≥ real); FII-rule time-shift placebo: real 1.58 vs mean 0.45
  (1 of 20 ≥ real).
