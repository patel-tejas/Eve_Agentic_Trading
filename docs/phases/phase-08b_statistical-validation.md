# Phase 08b — Statistical Validation

## Goal

Make the phase-08 parameter search state how much of its result is search luck,
and make every research run reproducible from a hashed receipt.

## Why This Phase Exists

Phase 08 sweeps 320 parameter combinations and reports the one with the highest
net P&L. Under a null where every combination is worthless, the *maximum* of 320
draws is comfortably positive, and it grows with how many were tried. Reporting
that maximum without saying how many were tried is the most common way a
research process fools itself.

Nothing in phase 08 corrected for that. This phase adds the corrections.

Ported in spirit from [HKUDS/Vibe-Trading](https://github.com/HKUDS/Vibe-Trading)
(MIT) — specifically its `quantlib/multipletesting.py`, `quantlib/crossvalidation.py`,
`backtest/validation.py` and `backtest/run_card.py`. Implementations here are
written against this project's Polars/NumPy stack rather than copied; the
underlying statistics are from Bailey & López de Prado and Benjamini & Hochberg.

## Deliverables

| Module | What it answers |
|---|---|
| `quant/research/_stats.py` | Normal CDF/PPF, moments, per-period Sharpe (no SciPy dependency) |
| `quant/research/significance.py` | Is this better than random? (permutation test, bootstrap Sharpe CI) |
| `quant/research/multiple_testing.py` | Is this better than the luckiest of N trials? (PSR, deflated Sharpe, BH-FDR, PBO/CSCV) |
| `quant/research/validate.py` | One call: run the grid, apply all four tests, return a verdict |
| `quant/research/run_card.py` | A hashed, self-describing receipt for one run |
| `quant/research/walk_forward.py` | Explicit, configurable embargo between train and test |

## Key Concepts

### Deflated Sharpe Ratio

The number to publish beside any "best parameters" claim.

```
observed Sharpe          what the grid winner scored (per-period)
      ↓
expected max Sharpe      what the best of N worthless trials
                         reaches by luck, given their dispersion
      ↓
deflated Sharpe          P(true Sharpe > that luck benchmark),
                         adjusted for sample length, skew, kurtosis
```

Above **0.95** the edge survives the multiplicity correction. Near 0.5 the
winner is indistinguishable from the luckiest of N coin flips — the expected
outcome for a grid search over a single month of data.

The unit test `test_deflation_demotes_the_luckiest_of_many_worthless_trials`
pins the demonstration: 320 columns of pure noise, and the best column's
undeflated confidence exceeds 0.95 while its deflated confidence does not.

### Annualisation is the trap

`parameter_grid_search` reports an **annualised** Sharpe. The probabilistic and
deflated Sharpe ratios are defined on **per-period** Sharpes. Mixing them
inflates trial dispersion by √252 and makes the deflation meaningless.

`validate_parameter_search` derives per-period Sharpes from each trial's own
daily returns rather than reading the `sharpe` metric column. Use it instead of
wiring the pieces by hand.

### Permutation test

Shuffles the *order* of realised trade P&Ls and asks how often a random ordering
beats the real one. Path-dependent statistics (drawdown, equity-curve shape)
depend on sequence; total P&L does not — so `statistic="total_pnl"` returns
exactly `p == 1.0` by construction, as a self-check.

### PBO / CSCV

Cuts the timeline into blocks, and for every balanced in-sample/out-of-sample
recombination asks whether the in-sample winner stays good out-of-sample. PBO
above **0.5** means the selection procedure is worse than picking at random.

### Embargo

```
│ Training window          │ E │ Test window │
                             ↑
                     embargo_days = 1 (default)
```

Without a gap, a position opened near `train_end` is still open when the test
window starts, so the same bars inform both the parameter choice and the score
that choice is judged by. The default of 1 day reproduces the schedule phase 08
already produced — it is now named and documented rather than an accident of the
arithmetic. Raise it above the strategy's maximum holding period if that ever
exceeds one session.

### Run card

`run_card.json` + `run_card.md` per run directory, holding the config, a stable
`config_hash` over canonical JSON (sorted keys, so insertion order never changes
it), the metrics, the validation verdicts, and a SHA-256 of every artifact file.
`verify_run_card()` re-hashes and reports `mismatched` / `missing` / `unexpected`.

This is what makes the README's "the quant engine is the deterministic source of
truth" checkable rather than merely asserted.

## Usage

```python
from quant.research.validate import validate_parameter_search
from quant.research.run_card import write_run_card

report = validate_parameter_search(candles, window=train_window)
print("\n".join(report.summary_lines()))

write_run_card(
    run_dir,
    run_id="RE-2026-07",
    config={"grid": grid, "period": "2026-07"},
    metrics=report.best_metrics,
    validation=report.to_dict(),
)
```

`SearchValidation.credible` is True only when every test that ran came back
favourable. A test that could not run is recorded in `skipped` and makes the
verdict False — a skip is never counted as a pass.

## Data Contracts

`BacktestResult` gained a `daily_returns` field: the per-day return series that
`compute_metrics` previously computed inline and discarded. Every test in this
phase consumes it. `GridResult` gained `returns_by_date` and `trade_pnls`;
neither appears in `to_row`, so the parquet grid output is unchanged.

## Dependencies

NumPy only — already a project dependency. Deliberately no SciPy: the two
normal-distribution functions needed are implemented in `_stats.py`
(`norm_ppf` is Acklam's approximation plus one Halley refinement, verified to
round-trip `norm_cdf` to 1e-12).

## Definition of Done

- [x] Deflated Sharpe demotes the winner of 320 noise trials below 0.95
- [x] Permutation test reports a strictly positive p-value (Davison–Hinkley +1)
- [x] BH reproduces the 1995 paper's worked example (2 of 10 at α=0.05)
- [x] PBO is >0.5 on noise and <0.5 when one trial has a real edge
- [x] Default embargo reproduces the existing phase-08 walk-forward schedule
- [x] Run card detects tampered, missing and unexpected artifacts
- [x] 73 unit tests, no network, all seeded

## Not In This Phase

Strategy decay monitoring, agent numeric grounding, live order gates and the
hash-chained audit ledger — see the Vibe-Trading review notes. Those belong to
phases 09–14.
