---
description: Use when running parameter search, walk-forward testing, or explaining training/validation/test splits and overfitting.
---

# Research Workflows

## Data split (default monthly)

- **Training**: first 23 days
- **Validation**: days 24–27
- **Test**: days 28–31

Parameter search uses ONLY the training window. Its top net P&L is in-sample — never present as expected performance.

## Parameter search

Default grid: fast EMA [5,7,9,12] × slow [15,18,21,25] × angle [20,25,30,35,40] × lookback [1,2,3,5] = 320 combos.
Quote: `positive_share`, `median_net_pnl`, best combo parameters. Prefer 5m or 15m for speed; 1m takes 1–2 min.

## Walk-forward (anti-overfitting check)

Three anchored steps with 5-day test windows:
1. Train days 1–15 → Test days 16–20
2. Train days 1–20 → Test days 21–25
3. Train days 1–25 → Test days 26–31

Each step: grid-search on train ONLY → apply best params to unseen test window. Always quote out-of-sample numbers.

## Experiment vault

Every backtest and compare run is automatically recorded. Use vault_query for "which configs beat the baseline?" — never recompute.

## Overfitting signals

- Train net P&L much greater than OOS net P&L
- Best config flips across walk-forward steps