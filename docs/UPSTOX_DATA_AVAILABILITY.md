# What Upstox actually serves — measured, 2026-09-28

Every row below was probed live against the API in this session, not read
off the docs. Probe scripts were throwaway; the numbers are reproducible
with `UpstoxClient.get_historical_candles_v3`.

**Verdict: Upstox is reliable and it is the best data source this project
has.** It gave 22 years of daily index history for free and unauthenticated.
There is exactly one real gap — expired derivatives contracts — plus one
boundary worth planning around: intraday history starts 2022-01-03.

## 1. Endpoints

| Endpoint | Auth | Status |
|---|---|---|
| `GET /v3/historical-candle/{key}/{unit}/{interval}/{to}/{from}` | **none needed** | works |
| Instrument master (`assets.upstox.com/.../NSE.json.gz`) | none | works |
| `GET /v2/expired-instruments/future/contract` | token | **401 UDAPI1149 — Upstox Plus only** |
| `GET /v2/expired-instruments/historical-candle/...` | token | **401 UDAPI1149 — Upstox Plus only** |

The v3 historical endpoint needs **no credentials at all**. Passing the
analytics token changes nothing, including history depth (verified: 1-minute
requests for Jan 2018 / 2020 / 2021 return empty with *and* without auth).

## 2. Intervals and how far back each one reaches

| `unit`/`interval` | Works | Earliest data |
|---|---|---|
| `minutes/1`, `/3`, `/5`, `/15` | yes | **2022-01-03** |
| `minutes/30`, `hours/1`, `hours/4` | yes | **2022-01-03** |
| `days/1` | yes | **2005-01-03** (index) |
| `weeks/1` | yes | 2005 |
| `months/1` | yes | 2005 |

**The hard boundary: no intraday data before 2022-01-03, at any interval,
with or without a token.** Daily and coarser reach back to 2005. This is
why the low-turnover campaign had to run on daily bars — it is the only way
to get a training window containing 2008 and 2020.

## 3. Per-request span cap (`UDAPI1148 Invalid date range` if exceeded)

Measured breakpoints — chunk requests to stay under these:

| Interval | Largest span that worked | Smallest that failed |
|---|---|---|
| `minutes/1` | 30 d | 40 d |
| `minutes/5` | ~31 d | 40 d |
| `minutes/15` | ~31 d | 90 d |
| `minutes/30` | 90 d | 120 d |
| `hours/1` | 90 d | 180 d |
| `days/1` | 3,650 d (2,475 candles) | 4,000 d |
| `weeks/1` | 3,650 d + | — |
| `months/1` | 7,300 d (20 y, 240 candles) | — |

Pattern: **~1 month for 1–15 min, ~1 quarter for 30 min–hourly, ~1 decade
for daily.** The cap is on calendar span, not candle count (a 1-minute
30-day pull returns 7,874 candles fine, while a 15-minute 90-day pull
fails at 525).

## 4. Instruments confirmed working

All via `days/1`, unauthenticated:

- `NSE_INDEX|Nifty 50`, `NSE_INDEX|Nifty Bank`, `BSE_INDEX|SENSEX`
- `NSE_INDEX|India VIX` ← see §5
- `NSE_INDEX|Nifty Fin Service`, `NSE_INDEX|Nifty Midcap 50`,
  `NSE_INDEX|Nifty Next 50`
- `NSE_EQ|<ISIN>` — individual equities (tested `NSE_EQ|INE002A01018`)

So the whole NSE/BSE index and cash-equity universe is reachable.

## 5. India VIX is available — correcting an earlier claim

`RESULTS_2026-09-27_LOW_TURNOVER.md` originally listed India VIX as blocked
behind an expired Dhan token. **That was wrong.** Upstox serves it free and
unauthenticated:

| | Coverage |
|---|---|
| `days/1` | **2009-03-02** onward (1,687 sessions in one 2008–2016 pull) |
| `minutes/1`, `/5`, `/15`, `hours/1` | **2022-01-03** onward, full granularity |

Sanity-checked values look like real VIX: 11.57–56.07 across 2009–2016
(the 56 is the 2009 spike), 16.00–24.03 in Jan 2022, 10.34–12.84 in Aug
2026.

This matters because implied volatility is **not** derived from the index
price series, so a VIX-regime signal sits outside the price-only space that
both research campaigns have now exhausted. It is the cheapest remaining
avenue and it needs no subscription.

## 6. What is genuinely missing

1. **Expired futures/options contracts** — the only true paywall
   (UDAPI1149, Upstox Plus). Without it there is no deep futures history,
   so no real traded volume, no open interest, and no true tradeable
   futures prices before the current contract's listing date.
2. **Futures depth on the active contract only.** `v3` serves the live
   contract from its listing date — the Oct 2026 NIFTY future returned 28
   daily candles (2026-07-29 →) and empty for Jan 2026. Index *spot* is
   the only long price history available, and it carries `volume = 0` and
   `open_interest = 0`.
3. **Pre-2022 intraday**, as in §2.

## 7. Practical rules

- Use `require_auth=False`; the token adds nothing for historical candles.
- Chunk by the §3 caps. `scripts/download_index_daily.py` chunks daily at
  5 years; `quant/data/index_spot.py` chunks 1-minute at one calendar month.
- Pace requests (~0.4 s) — `index_spot.REQUEST_PACING_SECONDS`.
- Index candles have `volume = 0` by construction. Any volume-dependent
  idea needs futures data, i.e. §6 item 1.
