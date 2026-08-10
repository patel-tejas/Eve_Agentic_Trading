# Research Workflows (Phase 08)

## Golden rule: calibration never touches test data

- **Training** = first 23 days of the month (default train split).
- **Validation** = days 24–27. **Test** = days 28–31.
- `parameter_search` runs on the **training window only**. Its top net P&L
  is in-sample; never present it as expected performance.

## Parameter search

- Default grid: fast EMA [5,7,9,12] × slow [15,18,21,25] × angle
  [20,25,30,35,40] × lookback [1,2,3,5] = 320 combos (fast < slow enforced).
- Result rows carry `RE-####` experiment IDs; sorted by net P&L.
- Summary stats to quote: `positive_share`, `median_net_pnl`, best combo.
- 1m on a full month is the slowest (~1-2 min); prefer 5m/15m for quick
  checks or narrow the grid.

## Walk-forward (the anti-overfitting check)

Three anchored steps (5-day test windows):

1. Train 1–15 → Test 16–20
2. Train 1–20 → Test 21–25
3. Train 1–25 → Test 26–31

Each step: grid-search on train ONLY → apply best params to the unseen
test window → record `test_net_pnl`. Quote OOS numbers, not train numbers.

## Vault

Every backtest/compare run is recorded into the experiment vault. For
"which config beat the baseline?" questions use `vault_query` rather than
recomputing.

## Robustness signals

- Overfitting signals: train net ≫ OOS net, or best combo flips between
  walk-forward steps.