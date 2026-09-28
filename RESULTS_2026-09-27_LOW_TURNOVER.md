# Where the Money Actually Is — and Isn't

**Campaign `C2026-09-LOWTURN`, 2026-09-27.**
Pre-registration: `plans/2026-09-27-low-turnover-preregistration.md`,
sealed by SHA-256 `9ca409a337c916c3…` at the campaign's first run
(`data/results/leaderboard/C2026-09-LOWTURN/prereg_seal.json`).

> **Disclosure:** that file was edited twice *after* sealing — a wrong
> citation and one sentence describing H5's switch cost as "two round
> trips" when it is one. Both are editorial; no split, candidate,
> parameter, cost assumption or pass/fail condition changed. Both edits are
> listed verbatim at the end of the pre-registration and both hashes are
> recorded in `prereg_post_seal_edits.json`, so the discrepancy is
> auditable rather than erased.


> ## ⚠ CORRECTION — 2026-09-28 (read this first)
>
> Two defects in this campaign were found while preparing the next one,
> and the campaign was re-run with both fixed. Results:
> `data/results/leaderboard/C2026-09-LOWTURN/corrected_2026-09-28/`.
> The original numbers below are left in place, not rewritten.
>
> 1. **Fill timing.** The pre-registration (A1.2) says *fill at the close
>    of day t+1*; the code filled at the close of day *t*, the same close the
>    signal was computed from. Corrected run: one-session lag.
> 2. **Costs.** STT on futures sales rose to **0.05% on 2026-04-01**
>    (Budget 2026); this run charged 0.02%. It also used the cash-market
>    exchange charge (0.00345% vs futures 0.0019%/0.00173%), 0.003% stamp
>    duty (futures: 0.002%), and 0.0125% STT before 2023-04-01 (actual:
>    0.01%). Corrected run: the dated schedule in
>    `quant/backtest/india_costs.py`. **A NIFTY round trip now costs ~6 bps
>    (~₹940), not the ~2.9 bps quoted in §1–2.**
>
> **What changed:**
>
> | Claim | Original | Corrected |
> |---|---|---|
> | Verdict | 0 of 5 pass | **0 of 5 pass (unchanged)** |
> | Any paired CI excluding zero | none | **none (unchanged)** |
> | BANKNIFTY H3 train CAGR / Sharpe / max DD | 8.25% / 0.50 / −33.6% | **4.94% / 0.34 / −50.2%** |
> | BANKNIFTY H3 matched-vol edge | +3.33pp | **−1.64pp** |
> | BANKNIFTY H3 train DSR (N=5) | 0.958 | no longer in the top 3 (top is H5 at 0.916) |
> | NIFTY H4 train max DD (B&H −61.7%) | −24.5% | **−23.5%** (drawdown finding holds) |
> | SENSEX H4 train max DD (B&H −63.4%) | −21.3% | −24.4% (holds) |
> | NIFTY H3 validation-2025 Sharpe (B&H 0.43) | −0.43 | **+0.51** |
>
> **How to read it.** The overall conclusion — no return edge over
> holding, roughly half the drawdown at similar risk-adjusted return for
> the NIFTY/SENSEX overlays — survives. The one result that looked like a
> genuine edge (BANKNIFTY H3) was substantially an artifact of filling on
> the signal's own close. And a single-session change in fill timing
> flips NIFTY H3's 2025 Sharpe from −0.43 to +0.51: these overlays are
> **fragile to execution timing**, which is itself a reason not to trade
> them as an edge. §7b's cash table was computed with the original fill
> and has not been re-verified.

---

## Bottom line

**On 22 years of data across three Indian indices, with a pre-registered
protocol and a frozen candidate list, I did not find a strategy that beats
simply holding the index with statistical significance — in any
timeframe. The one result I stand behind is risk, not return: a 200-day
trend filter with volatility-scaled sizing delivered about the same
risk-adjusted return as buy-and-hold with roughly half the maximum
drawdown, over 19 years including 2008 and 2020. That finding was
contradicted by 2025 and supported by the 2026 decline in two of three
markets.**

I also found a structural reason the previous 33,000-backtest campaign
could not work, which is section 1.

I am not going to dress this up. You asked for profit and you were
explicit that you did not want overfitting, and those two requirements
collided: every configuration that showed large profit failed
out-of-sample or failed the multiplicity correction. Section 6 is the
honest reckoning; sections 7–8 are what I think is worth acting on.

---

## 1. The structural problem with every intraday strategy tested so far

I split each day's return into the **overnight** leg (previous close →
open) and the **intraday** leg (open → close), train split only:

| Symbol | Overnight | Intraday | Full day |
|---|---|---|---|
| NIFTY | **+8.25 bps/day** (t = 4.16) | −3.87 bps/day | +4.37 |
| BANKNIFTY | **+6.32 bps/day** (t = 2.63) | −1.18 bps/day | +5.11 |
| SENSEX | **+6.32 bps/day** (t = 3.13) | −2.15 bps/day | +4.15 |

**The entire equity premium accrues overnight.** The intraday leg is
negative on all three indices.

The consequence for the previous campaign — the 9/15 EMA, the
Heikin-Ashi variants, all five SMC/ICT strategies — is that every one of
them squared off at the end of the day. **A strategy that is flat
overnight forfeits 100% of the equity premium.** It does not get the
tailwind that makes a long-only index position work; every rupee it makes
must come from timing skill alone, net of ~2.9 bps per round trip. That
is a far harder problem than it looks, and it is a much better
explanation of 0/42 than "the parameters were wrong."

> **What this does *not* say.** Those strategies traded both long and
> short, and a negative intraday drift *pays* a short (+3.87 bps gross on
> NIFTY). So the sign of the intraday drift alone does not doom them —
> the forfeited premium plus the cost hurdle does. I cannot test the
> long-vs-short split directly: the prior leaderboard stores only
> aggregate metrics per trial, not per-trade direction.

This overnight/intraday split is a documented anomaly, not my idea —
Haghani, Ragulin & Dewey (2022), which won the 2024 Harry Markowitz
award, call it "the grandmother of all market anomalies."

### Why you asked about 1m/5m/15m and I moved to daily

You asked for the best result in any timeframe, naming 1-, 5- and
15-minute. I tested those first and I am not ignoring them — I am
reporting that the evidence says they are the *hardest* place to look
here, for two compounding reasons:

1. They forfeit the entire equity premium (above).
2. A round trip costs **~2.9 bps**. Trade 250 times a year and you pay
   ~725 bps/year before you are right about anything.

Friction only stops mattering when turnover is low, which is why the study
moved to daily exposure management. That is a conclusion from the data,
not a preference.

## 2. I corrected a stale cost model (this matters)

The repo hard-coded **STT at 0.0125%**. STT on futures *sales* rose to
**0.02%** effective **1 October 2024** — ~0.75 bps more per round trip, on
an effect worth ~8 bps. Every number here uses the date-correct rate.

Corrected friction per round trip: **~2.9 bps** (brokerage ₹20/leg, STT,
exchange 0.00345%, SEBI, stamp 0.003%, GST 18%, 1 tick slippage), plus
**futures carry ~1.8 bps/night** (r − q ≈ 5.3%/yr over a
0.74-calendar-day hold, averaging in weekends).

## 3. The obvious trade — hold overnight only — does not survive

If all the drift is overnight, hold overnight and be flat all day. Tested
first, rejected:

| NIFTY, exit fill | Gross | Net of costs + carry | t | Sharpe |
|---|---|---|---|---|
| 09:15 first tick | 8.25 bps | **3.56** | 1.79 | 1.05 |
| 09:16 | 5.55 | 0.86 | 0.45 | 0.26 |
| 09:20 | 4.95 | 0.26 | 0.13 | 0.08 |
| 09:30 | 4.82 | 0.13 | 0.06 | 0.04 |

**The entire edge lives in the first minute** — and the 09:15 index print
is not tradeable, being computed from the pre-open auction. BANKNIFTY and
SENSEX net ~zero or negative at every realistic fill, and futures
buy-and-hold beats overnight-only on BANKNIFTY outright.

Two further checks against it: on 23 sessions of real NIFTY futures data
the basis is ~48 bps and decaying, and futures overnight returns differ
from spot's with a standard deviation of 19.3 bps/night — larger than the
whole edge. (That sample is too small to *calibrate* a 3 bps effect —
SE ≈ 8 bps — so I use it to bound risk, not to price the trade.)
Independently, the NY Fed's *The Disappearing Overnight Drift* (Jul 2026)
reports the US version faded after 2021, and the two ETFs launched to
harvest it (NSPY, NIWM) closed after 14 months.

## 4. Method — what makes this different from the last campaign

The previous campaign tested ~20,000 configurations. That is
self-defeating: the deflated Sharpe ratio asks "is this better than the
luckiest of N tries?", and at N = 20,000 the bar is nearly unreachable
*even if a real edge exists*. This campaign froze **five** candidates with
**literature-standard parameter values that were never tuned**.

- **Data extended 7×.** The 1-minute archive starts 2022-01, too short to
  warm up a 200-day filter. Upstox v3 serves *daily* index candles back to
  2005 unauthenticated, so I downloaded **5,377 sessions × 3 symbols
  (2005-01-03 → 2026-09-04)** — `scripts/download_index_daily.py`.
- **Splits, extended backward only** (val and test untouched): train
  **2006–2024** (~4,710 sessions, now including 2008, 2011, 2015-16, 2018,
  2020), val **2025** (249), test **2026** (168).
- **Fill rule:** signal from closes up to day *t*, position earned
  *t → t+1*. No same-bar fill; the opening print is never used.
- **Carry and the monthly roll are charged to the benchmark too** — in/out
  strategies pay them only while long, so omitting them from buy-and-hold
  would have quietly flattered every candidate.
- **The benchmark is not zero.** It is futures buy-and-hold net of carry
  and roll: NIFTY Sharpe 0.37, BANKNIFTY 0.40, SENSEX 0.37.
- **Sanity check run before any split was scored:** the daily engine
  reproduces the independent 1m-based buy-and-hold figure (NIFTY 2.41 vs
  2.22 bps/day, Sharpe 0.43 vs 0.40; the residual is NSE's official close
  being a last-30-min VWAP rather than the last tick).

> **Return basis.** Because r − q is charged, every return and Sharpe in
> §5 is an **excess return over cash**. When an overlay is flat its excess
> return is 0, which is correct. Do not compare these Sharpes to a
> raw-price-return Sharpe; that mistake is the subject of §7.

Candidates: **H1** volatility-managed exposure (Moreira & Muir 2017),
**H2** 12-month time-series momentum (Moskowitz-Ooi-Pedersen 2012),
**H3** 200-day trend filter, **H4** H3 gate with H1 sizing, **H5**
cross-index relative momentum (NIFTY vs BANKNIFTY).

## 5. Results (all figures are excess returns over cash)

### Train, 2006–2024 (19 years)

| Symbol | Strategy | CAGR | Sharpe | vs B&H | Max DD | B&H DD | Calmar | B&H Calmar |
|---|---|---|---|---|---|---|---|---|
| NIFTY | B&H | 5.78% | 0.37 | — | −61.7% | −61.7% | 0.094 | 0.094 |
| NIFTY | H1 | 3.95% | 0.38 | +0.01 | **−32.1%** | −61.7% | **0.123** | 0.094 |
| NIFTY | H4 | 3.03% | 0.35 | −0.02 | **−24.5%** | −61.7% | **0.124** | 0.094 |
| BANKNIFTY | B&H | 7.49% | 0.40 | — | −70.8% | −70.8% | 0.106 | 0.106 |
| BANKNIFTY | **H3** | **8.25%** | **0.50** | **+0.11** | **−33.6%** | −70.8% | **0.246** | 0.106 |
| BANKNIFTY | H4 | 4.14% | 0.42 | +0.03 | **−21.6%** | −70.8% | **0.192** | 0.106 |
| SENSEX | B&H | 5.76% | 0.37 | — | −63.4% | −63.4% | 0.091 | 0.091 |
| SENSEX | H1 | 4.53% | 0.41 | +0.05 | **−29.8%** | −63.4% | **0.152** | 0.091 |

Drawdowns roughly halve; Sharpe is about unchanged; Calmar improves
1.3–2.3×. **Not one candidate's paired bootstrap CI against buy-and-hold
excludes zero** — on 4,710 sessions.

### Validation, 2025 — every candidate underperformed

NIFTY B&H Sharpe 0.42 vs H3 −0.43 and H4 −0.35; BANKNIFTY B&H 0.88 vs H3
0.24. A choppy year with no crash: the filters paid costs, got whipsawed,
and had no left tail to avoid.

### Test, 2026 (period returns over 0.67 years, not annualized)

| Symbol | Strategy | Period return | Max DD | Avg exposure |
|---|---|---|---|---|
| NIFTY | B&H | −12.02% | −16.3% | 1.00 |
| NIFTY | H3 / H4 | **−8.31% / −8.26%** | **−9.0% / −8.9%** | 0.22 |
| SENSEX | B&H | −13.63% | −17.3% | 1.00 |
| SENSEX | H3 / H4 | **−8.33% / −8.32%** | **−8.9%** | 0.16 |
| BANKNIFTY | B&H | **−7.37%** | −18.9% | 1.00 |
| BANKNIFTY | H3 | −12.96% | −15.1% | 0.52 |
| BANKNIFTY | H4 | −9.46% | −11.5% | 0.45 |

**Mixed, and I am not going to round it up.** On NIFTY and SENSEX the
trend filter went defensive and lost ~4–5 pp less with about half the
drawdown. **On BANKNIFTY it lost 5.6 pp *more* than buy-and-hold** (H1 was
the best BANKNIFTY overlay, at −5.91%). Since NIFTY and SENSEX are ~0.99
correlated and count as one market, that is "helped in one of two
independent markets, hurt in the other." Drawdown was lower in all three.
Every paired CI includes zero, the underpowered outcome pre-registered in
§A1.4 — 168 sessions cannot resolve this.

> Sharpe inverts in a losing period: H3's test Sharpe (−2.37) looks worse
> than B&H's (−1.19) *because* it cut volatility while returns were
> negative. Period return and drawdown are the meaningful metrics here.

### The cleanest test of "is there a return edge": matched volatility

Scale each overlay to the benchmark's volatility, then compare CAGR:

| | NIFTY | BANKNIFTY | SENSEX |
|---|---|---|---|
| H1 | +0.21pp | −1.60pp | +1.03pp |
| H2 | −2.66pp | −7.17pp | −0.55pp |
| H3 | −0.73pp | **+3.33pp** | +0.04pp |
| H4 | −0.45pp | +0.79pp | +0.18pp |

Scattered around zero. **At equal risk there is no return advantage.**

### Pre-registered gate: 0 of 5 pass

| Condition | Result |
|---|---|
| Paired bootstrap vs B&H excludes zero | **FAIL** — all 5, all splits |
| No calendar year worse than B&H by >15pp | **FAIL** — all 5, all on **2009** (−28 to −58pp: the filters were still out of the market during the post-crash rebound) |
| Positive in ≥60% of years | mixed (47–67%) |
| Turnover friction < 20% of gross | **PASS** — 2.0–4.3% (tc only, excluding carry) |
| Robust to +50% friction, r−q ∈ {3%, 5.3%, 7%} | **PASS** — the Calmar advantage holds at every setting |
| Drawdown co-primary | **PASS** — robustly, all symbols, all splits |

Deflated Sharpe: on train, BANKNIFTY H3 reaches 0.958 at N = 5 (0.926 at
N = 20) — but this measures Sharpe > 0, and buy-and-hold's Sharpe is
positive too, so it is not evidence of an edge *over holding*. On
validation the best deflated Sharpe across all candidates is 0.68.

### One post-hoc test, labelled as such

India's most-cited calendar anomaly, turn-of-the-month (long only the last
3 + first 3 trading days of each month, ~29% time in market):

| Split | NIFTY Sharpe | B&H | CI vs zero |
|---|---|---|---|
| Train 2006–24 | **0.68** | 0.37 | **excludes zero** on all 3 symbols |
| Val 2025 | −0.04 | 0.42 | includes zero |
| Test 2026 | −0.09 | −1.19 | includes zero |

Strong and highly significant for 19 years, then **nothing in the last 20
months** — precisely the decay the Indian calendar-anomaly literature
predicts. Not pre-registered; reported as exploratory.

## 6. The honest answer to "I want profit"

On 22 years of data across three indices, pre-registered, with the test
split scored only after the candidate list was frozen: **no strategy I
tested, and none of the ~33,000 tested before, produces a statistically
credible excess return over simply holding the index.** Everything that
looked strongly profitable in-sample — turn-of-month at Sharpe 0.68,
BANKNIFTY H3 at Sharpe 0.50, the previous campaign's +₹242,841 HA-ladder
cell — failed out-of-sample or failed the multiplicity correction.

That does not mean profit is impossible. It means **this dataset — daily
and intraday price bars on three highly-correlated Indian indices, carrying
no volume, no open interest and no options data — is close to
exhausted for price-shape signals.** They have now been searched hard twice,
and the second search was designed specifically to avoid the first one's
statistical trap. The binding constraint is the information in the data,
not the cleverness of the search.

## 7. What is worth acting on

**a) The futures instrument cost is small if your margin earns interest —
and about 6%/yr if it doesn't.** I want to correct something I nearly got
wrong here. Measured on the same basis, the drag of rolling long futures
versus holding the index is only **0.36 pp/yr** (roll + transaction costs;
NIFTY B&H CAGR 5.78% with the monthly roll vs 6.14% without). It is *not*
the ~5.3%/yr carry figure — a fully collateralized futures position
(margin in a liquid fund or pledged securities earning ≈ r) earns
approximately the index's total return minus that 0.36 pp, because the
financing embedded in the futures basis is offset by the interest your
collateral earns.

The cost becomes real only if your margin sits **idle** at the broker
earning nothing, in which case you forgo ≈ r (currently ~5.5–6.5%/yr).
That is a genuine and commonly-overlooked retail cost, and the fix is
operational, not strategic: **hold margin in an interest-bearing form.**
For its size, this is likely worth more than any signal in this study.

**b) The one result I stand behind is the §5 train table, and it is about
risk.** Over 19 years including 2008 and 2020, the trend/volatility
overlays produced about the same excess-return Sharpe as buy-and-hold with
roughly **half the maximum drawdown** (NIFTY −24.5% vs −61.7%; BANKNIFTY
−21.6% vs −70.8%), lifting Calmar 1.3–2.3×. That held at every friction
and carry setting tested.

Read it as "a better-behaved way to hold the index," not as an edge:
matched-volatility returns are indistinguishable, no CI excludes zero,
2025 contradicted it, and 2026 supported it in only one of two
independent markets. If large drawdowns are what would actually make you
abandon a position, that is worth something. If you want excess return, it
is not there.

**c) Stop searching price-only intraday signals on these three indices.**
Sections 1 and 6 are the argument.

## 8. The unlocks that would actually change the answer

All three are data, not code, and all are blocked on access I do not have:

1. **Real futures history with volume and open interest, 2022–2025.** The
   code path exists (`UpstoxClient.get_expired_historical_candles`), but
   `/v2/expired-instruments/…` now returns **401 UDAPI1149 — requires an
   Upstox Plus subscription.** The single most valuable addition: it
   removes the index-spot proxy, gives real tradeable prices, and adds
   volume/OI as genuinely new information.
2. ~~**India VIX** requires the expired Dhan token.~~ **CORRECTED
   2026-09-28 — this was wrong, and it was the one item here that is not
   actually blocked.** Upstox serves India VIX (`NSE_INDEX|India VIX`)
   free and unauthenticated: **daily back to 2009-03-02**, and **1m/5m/15m/
   hourly back to 2022-01-03**. Implied volatility is not derived from the
   index price series, so a VIX-regime signal sits outside the space both
   campaigns exhausted — making this the cheapest remaining avenue, at zero
   cost and available now. Measured coverage:
   `docs/UPSTOX_DATA_AVAILABILITY.md`. (Dhan's token is still expired,
   DH-901, but what it would add is open interest and options data, not
   VIX.)
3. **Options data** (Dhan serves 5 years of expired-options minute data
   with IV and OI). PCR, IV skew and OI buildup are genuinely different
   information. This was the previous campaign's own top recommendation
   and it remains the right one.

## 9. Caveats worth stating plainly

- Index data is **spot proxy**: volume and open interest are identically
  zero, so no flow signal was testable.
- **No volatility signal was tested, and that was an avoidable gap.** I
  believed India VIX was unavailable; it is served free by Upstox (daily to
  2009, intraday to 2022). See `docs/UPSTOX_DATA_AVAILABILITY.md`.
- Exposure is modelled as a **continuous fraction of notional**. One NIFTY
  lot is ~₹15.6L, so at retail capital H1/H4 collapse to a 0/1/2-lot
  decision and the rebalance band is coarse. This is an implementability
  limit, not modelled as an edge.
- Fills use NSE's official daily close (a last-30-min VWAP), which differs
  from the last tick by a median 4.4–5.5 bps. Symmetric between entry and
  exit, so it is tracking error rather than a systematic cost.
- The worst single overnight gap in the sample was **349 bps** (~₹50k+ per
  NIFTY lot). Overnight gap risk cannot be stopped out; Sharpe understates
  it.
- Test-split discipline: the candidate list and all parameters were frozen
  and sealed before test was scored, and nothing was changed afterwards.
  The turn-of-month test in §5 is explicitly post-hoc and is excluded from
  the gate.

## 10. Where everything is

| What | Where |
|---|---|
| Pre-registration + amendment | `plans/2026-09-27-low-turnover-preregistration.md` |
| Seal (SHA-256 of the above) | `data/results/leaderboard/C2026-09-LOWTURN/prereg_seal.json` |
| Post-seal edit disclosure | `data/results/leaderboard/C2026-09-LOWTURN/prereg_post_seal_edits.json` |
| Overlays, costs, carry, bootstrap | `quant/research/daily_overlay.py` |
| Campaign runner | `scripts/run_lowturn_campaign.py` |
| Deep daily data downloader | `scripts/download_index_daily.py` |
| Tests (18, all passing) | `tests/test_phase12_daily_overlay.py` |
| Per-cell results / DSR / yearly | `data/results/leaderboard/C2026-09-LOWTURN/*.parquet` |
| Measured Upstox data availability | `docs/UPSTOX_DATA_AVAILABILITY.md` |
| Daily data (5,377 × 3) | `data/processed/index_daily/{NIFTY,BANKNIFTY,SENSEX}/daily.parquet` |

Test suite: **333 passing**, 4 pre-existing failures unrelated to this
work (documented in `plans/PROGRESS.md`), ruff clean.

**Nothing here should be traded live as an edge.** §7b is a risk result,
not a return result, and its own validation year contradicts it.

### Sources

- [Night Moves: Is the Overnight Drift the Grandmother of All Market Anomalies? — Haghani, Ragulin & Dewey (2022), JOIM Q2 2024](https://papers.ssrn.com/sol3/papers.cfm?abstract_id=4139328)
- [The Overnight Drift — Boyarchenko, Larsen & Whelan, NY Fed SR 917 / RFS 36(9) 2023](https://www.newyorkfed.org/medialibrary/media/research/staff_reports/sr917.pdf)
- [The Disappearing Overnight Drift — Liberty Street Economics, Jul 2026](https://libertystreeteconomics.newyorkfed.org/2026/07/the-disappearing-overnight-drift/)
- [Asset Pricing: A Tale of Night and Day — Hendershott, Livdan & Rösch, JFE 138(3) 2020](https://ideas.repec.org/a/eee/jfinec/v138y2020i3p635-662.html)
- [New STT Rules in F&O Trading Effective from 1st October 2024 — ICICI Direct](https://www.icicidirect.com/research/equity/finace/new-stt-rules-in-futures-and-options-trading)
- [An Enquiry into the Persistence of Turn-of-the-Month Effect on Stock Markets in India — Tadepalli, Jain & Metri (2022)](https://journals.sagepub.com/doi/abs/10.1177/2278533721994713)
- [Month-of-the-Year Effect: Empirical Evidence from Indian Stock Market — Asia-Pacific Financial Markets](https://pmc.ncbi.nlm.nih.gov/articles/PMC8742668/)
- [The overnight drift: why markets move when you're asleep — Zerodha](https://inthemoneybyzerodha.substack.com/p/the-overnight-drift-why-markets-move)
