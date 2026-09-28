# Pre-registration — Campaign C2026-09-LOWTURN

**Written BEFORE any validation or test split was scored.** Amended once
(2026-09-27, same session) to fix five methodology defects found in
review, all *before* any split was scored. No amendment after scoring.

Author: research session 2026-09-27. Protocol: `quant/research/protocol.py`
(`DISCOVERY_SPLITS`, unchanged): train 2022-01-01..2024-12-31,
val 2025-01-01..2025-12-31, test 2026-01-01..2026-09-05.

---

## 1. Why a new campaign (the diagnosis that motivates it)

Campaign `C2026-09-EMA-SMC` ran ~33,000 backtests over 6 intraday
price-shape strategy families and passed 0 of 42 cells. This campaign
starts from a *measured* reason for that failure rather than another
search of the same space.

Measured on the train split only (1m/5m index data, 739 sessions):

| Symbol | Overnight (close->open) | Intraday (open->close) |
|---|---|---|
| NIFTY | **+8.25 bps/day** (t=4.16) | -3.87 bps/day |
| BANKNIFTY | **+6.32 bps/day** (t=2.63) | -1.18 bps/day |
| SENSEX | **+6.32 bps/day** (t=3.13) | -2.15 bps/day |

Every strategy in the prior campaign was intraday with end-of-day
square-off. All of them traded the leg of the day whose drift is
*negative*. That is a structural headwind, not a tuning problem, and it
explains the 0/42 result better than "the parameters were wrong".

This is the documented overnight/intraday anomaly (Haghani, Ragulin & Dewey 2022 call it
"the grandmother of all market anomalies"; Boyarchenko, Larsen & Whelan,
*The Overnight Drift*, NY Fed SR 917 / RFS 36(9) 2023; Hendershott,
Livdan & Roesch, *Asset Pricing: A Tale of Night and Day*, JFE 138(3)
2020. Note NY Fed's *The Disappearing Overnight Drift* (Jul 2026) reports
the US effect faded post-2021, and the NightShares overnight ETFs
(NSPY/NIWM) closed after 14 months.)

## 2. Why the obvious trade (overnight-only) is NOT the candidate

Tested first, and rejected on measured friction, before any tuning:

Corrected friction — the repo's cost model was **stale**: STT on futures
sales rose 0.0125% -> **0.02%** effective 2024-10-01. Round-trip friction
is **~2.9 bps**, plus futures carry (r-q ~5.3%/yr over a 0.74-calendar-day
hold, ~1.8 bps/night average including weekends).

NIFTY overnight hold, train split, net of both:

| Exit fill | Gross | Net | t | Sharpe |
|---|---|---|---|---|
| 09:15 first tick | 8.25 | **3.56** | 1.79 | 1.05 |
| 09:16 | 5.55 | 0.86 | 0.45 | 0.26 |
| 09:20 | 4.95 | 0.26 | 0.13 | 0.08 |

The entire edge lives in the first minute, and the 09:15 index print is
an auction-derived value that is not transactable. BANKNIFTY and SENSEX
net ~0 or negative at every realistic fill, and futures buy-and-hold
(net Sharpe 0.40) beats overnight-only on BANKNIFTY. **Rejected.**

## 3. The actual hypothesis of this campaign

> At ~2.9 bps round-trip friction, a strategy trading 250 times a year
> pays ~725 bps/yr. The prior campaign searched only high-turnover
> intraday space, where friction is a first-order cost. The unexplored,
> cost-viable region is **low-turnover daily/swing exposure management**,
> where the same friction is a rounding error.

The benchmark to beat is therefore not zero but **futures buy-and-hold
net of carry**: NIFTY Sharpe 0.40, BANKNIFTY 0.43, SENSEX 0.36 (train).

## 4. Frozen candidate list (this is the complete list; N_trials is small by design)

All use **daily closes only** — never the 09:15 opening print, which
section 2 showed is both decisive and untrustworthy. All parameter values
are fixed here at their standard literature values and are **not tuned**.

| ID | Hypothesis | Params (fixed) | Source |
|---|---|---|---|
| H1 | Vol-managed long: scale exposure by target_vol/realized_vol | target 12% ann, 20d realized, rebalance band 25% | Moreira & Muir, JF 2017 |
| H2 | Time-series momentum: long if trailing 12m return > 0, else flat | 252d | Moskowitz-Ooi-Pedersen, JFE 2012 |
| H3 | Trend filter: long if close > 200d SMA, else flat | 200d | classic |
| H4 | H3 entry combined with H1 sizing | as above | — |
| H5 | Cross-index relative momentum: hold the stronger of NIFTY/BANKNIFTY | 60d | cross-sectional momentum |
| B0 | Benchmark: futures buy-and-hold, net of carry | — | — |

**N_trials = 5** (plus benchmark). This is deliberate: the prior
campaign's ~20,000 configurations made its own deflated-Sharpe bar
mathematically unreachable. A small pre-registered list keeps the
multiple-testing penalty negligible.

## 5. Robustness conditions — REQUIRED to pass, not alternatives to choose from

A candidate must survive **all** of these, not the best of them:

1. Net of the corrected cost model (STT 0.02% post-2024-10-01) **and**
   futures carry on every calendar day held.
2. Sign-consistent: positive net return in **each** train year
   (2022, 2023, 2024) and in val.
3. Net Sharpe **> the buy-and-hold benchmark** on the same window.
4. Robust to +50% friction (a stress multiple), still beating B0.
5. Turnover low enough that friction is < 20% of gross return.

## 6. Evidence standard, fixed before val is opened

- **Val is scored once**, after the train ranking is final.
- Sharpe is computed from **daily** equity returns (N = sessions: 740 /
  249 / 168), not per-trade, which is the correct N for a Sharpe test.
- Bootstrap CI on **pooled val+test** daily returns. Power note fixed in
  advance: 168 test sessions alone can only exclude zero at SR ~2.4;
  pooled val+test needs ~1.5. A candidate with SR ~0.9 **will not** show
  a CI excluding zero, and that will be reported as "underpowered", not
  as "no edge" and not as "edge confirmed".
- Deflated Sharpe computed at **N_trials = 5**.
- NIFTY and SENSEX are ~0.99 correlated and count as **one** market, not
  two confirmations. BANKNIFTY is the second market.

## 7. Known data limitations (recorded, not worked around)

- Index data is **spot proxy**: volume and open interest are identically
  zero. No volume/flow signal is testable.
- Real futures data on disk is 31 sessions (2026-07, 2026-08) — enough to
  calibrate basis (~48 bps, decaying) but *not* enough to calibrate a
  ~3 bps execution effect (SE ~8 bps at n=23).
- Upstox expired-instrument history (which would give real futures
  volume/OI for 2022-2025) now requires a paid **Upstox Plus** plan: 401
  UDAPI1149. The Dhan access token is **expired** (DH-901), so India VIX
  and any Dhan history are unavailable this session. Both are recorded as
  concrete unlocks, not as excuses.

---

# AMENDMENT 1 (pre-scoring) — methodology fixes

Five defects were found in review of sections 4-6 above. All are fixed
here, **before any split was scored**. Where this amendment conflicts
with sections 4-6, the amendment governs.

## A1.1 Longer training window (fixes: 200/252d warmup ate all of 2022)

Sections 4-6 assumed the 1-minute archive (train = 739 sessions from
2022-01). A 252-day lookback leaves almost no signal in 2022, and
2023-24 is an uninterrupted bull run — a window where a trend or
volatility overlay structurally *cannot* show the drawdown reduction it
exists for.

Upstox v3 serves **daily** index candles back to 2005 unauthenticated
(`scripts/download_index_daily.py`, chunked at 5y to avoid UDAPI1148).
Downloaded: **5,377 sessions per symbol, 2005-01-03 .. 2026-09-04.**

Frozen splits for this campaign (a **new** constant, `DAILY_SPLITS`;
`DISCOVERY_SPLITS` is NOT edited, so the prior campaign's
`protocol_hash()` is unchanged):

| Split | Range | Sessions |
|---|---|---|
| warmup | 2005-01-03 .. 2005-12-31 | ~250 (metrics excluded) |
| **train** | 2006-01-01 .. 2024-12-31 | ~4,710 |
| **val** | 2025-01-01 .. 2025-12-31 | 249 |
| **test** | 2026-01-01 .. 2026-09-05 | 168 |

Train is extended **backward only**. Val and test are unchanged and stay
frozen. Train now contains 2008, 2011, 2015-16, 2018 and 2020.

## A1.2 Fill rule (fixes: unspecified, allowed look-ahead)

**Signal from closes up to and including day t; fill at the close of day
t+1.** Exposure `e_t` set at close t is earned over t -> t+1. No
same-bar fills, and the 09:15 opening print is never used.

Caveat recorded: NSE's official daily close is a last-30-minute VWAP of
constituents, not the last tick, so it differs from the 1m-derived close
by a median 4.4-5.5 bps (opens match to 0.000 bps). For a strategy
turning over 10-30x/year this is tracking error, not a systematic cost,
and it is symmetric between entry and exit.

## A1.3 Sizing is continuous notional (fixes: hidden lot/capital params)

Exposure is a **continuous fraction of notional, capped at 1.0x**. No
capital figure, no lot rounding, no leverage above 1x.

Caveat recorded separately: one NIFTY lot is ~Rs 15.6L notional, so at
retail capital H1/H4 collapse to a 0/1/2-lot decision and the rebalance
band is coarse. Reported as an implementability limit, not modelled as
an edge.

## A1.4 Decision rules (fixes: point-estimate comparison, wrong year rule)

- **Primary test replaces old condition #3:** a **paired bootstrap** of
  daily (strategy - benchmark) returns, 10,000 resamples, reporting a CI
  on both the mean difference and the Sharpe difference. A
  point-estimate "higher Sharpe" no longer counts as passing.
- **Power stated in advance:** with strategy/benchmark correlation ~0.8
  and 417 OOS sessions, the SE of a Sharpe difference is ~0.5.
  "Beats B&H out-of-sample" is therefore **expected to be underpowered**.
  `indistinguishable from B&H` is hereby a **named, reportable outcome**,
  neither a pass nor a failure, and it is the single most likely result.
- **Old condition #2 ("positive in every year") is withdrawn** — it
  rejects a trend filter precisely for the whipsaw years it is designed
  to sit out. Replaced by: **no calendar year worse than the benchmark by
  more than 15 percentage points**, and **positive in >= 60% of calendar
  years**.
- **Max drawdown is a co-primary metric** alongside Sharpe. Drawdown
  reduction at equal-or-better Sharpe is an explicitly acceptable form
  of success, declared here before scoring.

## A1.5 Carry and roll charged symmetrically (fixes: flattered in/out vs B&H)

- **Carry** `(r-q)/365 x calendar_days x exposure` on every calendar day
  held, long only.
- **Roll:** one futures round trip per month charged to **every** long
  hold, **including the B&H benchmark** (previously B&H paid only
  "~0.03"). In/out strategies pay carry and roll only while long, so
  omitting it on B&H biased the comparison toward them.
- **`r-q` in {3%, 5.3%, 7%} is a required robustness condition**, not a
  single point value: the RBI repo rate ranged 4%-8% over 2005-2026.
- H5's benchmark is **50/50 NIFTY/BANKNIFTY B&H**. A switch exits one leg
  and enters the other: two legs, i.e. **one round trip**, which is what
  the cost path charges.

## A1.6 Reproduction check before val is opened

The daily backtester must reproduce the independently-computed 1m-based
B&H train figures (NIFTY net 2.22 bps/day, Sharpe 0.40 on 2022-2024)
within tolerance before any split is scored. This catches sign and carry
bugs cheaply.

## A1.7 Deflated Sharpe reported at two trial counts

`N_trials = 5` (this campaign's frozen list) **and** `N_trials ~ 20`
(conservatively including the ~12 overnight exit/symbol variants
inspected in section 2 before this list was frozen). Both are reported;
the larger is the honest one for a reader who counts section 2 as search.

## A1.8 Status of this file

This file is **not** committed by the session (the harness commits only
on request). Integrity is established instead by a SHA-256 of this file
recorded in the campaign seal written at first run, and printed in the
final report.

---

# POST-SEAL EDITORIAL CORRECTIONS (disclosed, not hidden)

This file was sealed by SHA-256 at the campaign's first run
(`9ca409a337c916c3…`). It was then edited **twice, editorially only**, which
means the sealed hash no longer matches the file. Rather than re-seal and
quietly erase the discrepancy, both edits are listed here verbatim so a
reader can verify that **no split, candidate, parameter value, cost
assumption, or pass/fail condition was altered**:

1. **Citation fix** (§1): "Haghani & White 2022" -> "Haghani, Ragulin &
   Dewey 2022". The paper is *Night Moves*, JOIM Q2 2024, 2024 Harry
   Markowitz award. Wrong co-authors; corrected.
2. **Cost-description fix** (§A1.5): H5's switch cost read "**two** round
   trips (exit one leg, enter the other)". A switch is two *legs*, i.e.
   **one round trip** — which is what the code always charged. The prose
   was wrong, not the code, so the wording was corrected and no number
   changed.

Both edits were made after the test split had been scored, which is
exactly why they are disclosed rather than absorbed. Neither is capable of
moving a result: the first is a bibliography entry and the second
describes a cost the implementation already applied. The current file's
hash is recorded in `prereg_post_seal_edits.json` next to the seal.
