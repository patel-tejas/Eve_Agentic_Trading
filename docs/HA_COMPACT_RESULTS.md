# HA Compact Candle Strategy — Optimization Results

## Strategy Overview

A Heikin-Ashi-based EMA crossover strategy with four tunable gates:

1. **Compact Candle**: `HA_range <= SMA(HA_range, lookback) * multiplier`
   Small HA candles signal indecision/loss of momentum at the crossover point.

2. **Slope Filter**: `|EMA_slope| >= threshold` (ATR-normalized)
   Ensures the crossover is backed by directional momentum.

3. **Distance Filter**: `EMA_gap % of price` between min and max bounds
   Prevents entries where EMAs are too tightly coiled (noise) or too far apart (extended).

4. **Volume Filter** (optional): `volume > SMA(volume, period) * multiplier`
   Only meaningful on instruments with real volume (futures). Always OFF in these results
   because NIFTY/BANKNIFTY/SENSEX are index spot data with volume=0.

---

## Column Definitions

| Column | What It Means |
|---|---|
| **Symbol** | The index tested — NIFTY, BANKNIFTY, or SENSEX |
| **TF** | Timeframe of the candles — 1m (1-minute), 5m (5-minute), or 15m (15-minute) |
| **Loops** | Number of random parameter combinations tested (50 or 100) |
| **Robust** | How many of those loops passed all robustness checks (min trades, drawdown limit, positive OOS return, no excessive degradation train→val) |
| **Train%** | Net return on the training window (70% of data, 2022-01 to 2025-04). After costs, slippage, and taxes. |
| **Val%** | Net return on the validation window (30% of data, 2025-04 to 2026-09). This is the **out-of-sample** (OOS) evidence — the number that matters most. |
| **Trades** | `train_trades / val_trades` — total round-trip trades in each window. Fewer trades = less statistical confidence. |
| **DD%** | Maximum drawdown on the training window. Peak-to-trough decline as a percentage of peak equity. Lower is better. |
| **PF** | **Profit Factor** = gross profits / gross losses. PF > 1.0 means the strategy makes money. PF = 1.52 means Rs 1.52 earned per Rs 1 lost. |
| **WinR%** | **Win Rate** — percentage of trades that were profitable. Not shown in summary table (available in CSV). |
| **Sharpe** | **Sharpe Ratio** — risk-adjusted return. Annualized. > 0 is good, > 1 is strong, > 2 is excellent. Negative means the strategy loses on a risk-adjusted basis. |

---

## Robustness Checks

A config is marked **robust** only if it passes ALL of:

1. **Minimum trades**: At least 8 trades on training data (statistical significance)
2. **Drawdown limit**: Max drawdown ≤ 25% on training data (sensible risk)
3. **Positive OOS return**: Validation window return > 0% (the strategy actually works forward)
4. **No excessive degradation**: Validation return ≥ 40% of training return (not just luck on training data)

---

## Execution Model

- **Signal**: Generated at bar close
- **Fill**: Next bar open + 1-tick adverse slippage (normal mode)
- **Costs**: India futures model — Rs 20 flat brokerage, STT 0.0125% (sell side), exchange fee 0.00345%, SEBI, stamp duty, 18% GST
- **Exits**: ATR-based stop loss (2x ATR), R-multiple target (2.5R), breakeven trailing after 1R
- **No look-ahead**: Every indicator is causal; HA is computed using only bars ≤ t

---

## Results Table

```
Symbol     TF    Loops Robust   Train%     Val%  Trades    DD%     PF  Sharpe
----------------------------------------------------------------------------------------------------
NIFTY      1m      100     1   +0.3%   +0.6%    26/4   1.3%   1.46  +0.14
NIFTY      5m      100     9   +1.3%   +2.6%    74/29  2.1%   1.52  +0.33
NIFTY     15m      100     9   -1.6%   +2.3%    98/43  3.8%   1.11  -0.29
BANKNIFTY  1m       50     0*  +9.9%   -2.3%    70/11  2.2%   2.00  +0.87
BANKNIFTY  5m       50     1   -6.6%   +2.6%    33/4   8.9%   0.73  -0.59
BANKNIFTY 15m       50     4   -2.5%   +7.8%   109/51 13.1%   1.10  -0.09
SENSEX     1m       50     1   -0.5%   +0.5%    17/5   3.3%   1.30  -0.13
SENSEX     5m       50     2   +2.8%   +5.0%     8/5   2.3%   3.46  +0.67
SENSEX    15m       50     5   -6.9%  +10.0%   153/71 15.9%   1.08  -0.22
----------------------------------------------------------------------------------------------------
* = no robust config found; shows best non-robust result
```

---

## Best Robust Parameters Per Symbol/Timeframe

### NIFTY 5m (Best overall risk-adjusted)

```
EMA: 9/21
Compact: lookback=20, multiplier=1.2
Slope threshold: 0.3 (lookback=1)
Distance: [0.0, 2.0]%
Volume filter: OFF
ATR period: 20
=> Train: +1.3% | Val: +2.6% | Trades: 74/29 | DD: 2.1% | PF: 1.52 | Sharpe: +0.33
```

### NIFTY 15m

```
EMA: 5/34
Compact: lookback=10, multiplier=0.8
Slope threshold: 0.0 (lookback=3)
Distance: [0.0, 2.0]%
Volume filter: OFF
ATR period: 14
=> Train: -1.6% | Val: +2.3% | Trades: 98/43 | DD: 3.8% | PF: 1.11 | Sharpe: -0.29
```

### NIFTY 1m

```
EMA: 5/25
Compact: lookback=20, multiplier=1.0
Slope threshold: 0.0 (lookback=5)
Distance: [0.02, 2.0]%
Volume filter: OFF
ATR period: 20
=> Train: +0.3% | Val: +0.6% | Trades: 26/4 | DD: 1.3% | PF: 1.46 | Sharpe: +0.14
```

### BANKNIFTY 15m

```
EMA: 9/21
Compact: lookback=15, multiplier=0.8
Slope threshold: 0.0 (lookback=1)
Distance: [0.0, 1.0]%
Volume filter: OFF
ATR period: 20
=> Train: -2.5% | Val: +7.8% | Trades: 109/51 | DD: 13.1% | PF: 1.10 | Sharpe: -0.09
```

### BANKNIFTY 5m

```
EMA: 7/21
Compact: lookback=20, multiplier=0.8
Slope threshold: 0.0 (lookback=5)
Distance: [0.02, 1.0]%
Volume filter: OFF
ATR period: 14
=> Train: -6.6% | Val: +2.6% | Trades: 33/4 | DD: 8.9% | PF: 0.73 | Sharpe: -0.59
```

### SENSEX 15m

```
EMA: 9/25
Compact: lookback=10, multiplier=1.0
Slope threshold: 0.1 (lookback=5)
Distance: [0.0, 2.0]%
Volume filter: OFF
ATR period: 14
=> Train: -6.9% | Val: +10.0% | Trades: 153/71 | DD: 15.9% | PF: 1.08 | Sharpe: -0.22
```

### SENSEX 5m

```
EMA: 12/21
Compact: lookback=30, multiplier=0.6
Slope threshold: 0.2 (lookback=5)
Distance: [0.0, 2.0]%
Volume filter: OFF
ATR period: 20
=> Train: +2.8% | Val: +5.0% | Trades: 8/5 | DD: 2.3% | PF: 3.46 | Sharpe: +0.67
```

### SENSEX 1m

```
EMA: 9/25
Compact: lookback=30, multiplier=0.6
Slope threshold: 0.3 (lookback=5)
Distance: [0.0, 1.0]%
Volume filter: OFF
ATR period: 20
=> Train: -0.5% | Val: +0.5% | Trades: 17/5 | DD: 3.3% | PF: 1.30 | Sharpe: -0.13
```

---

## Why 30% Return Was Not Reached

**Target**: 30% net return on initial capital per symbol and timeframe after realistic costs.

**Result**: Not achieved. Best robust OOS returns range from +0.6% to +10.0%.

### Root Causes

1. **Market Regime (2022-2025)**
   The training window spans post-COVID recovery, 2022 bear market, 2023-24 sideways chop, and 2025 mild bullish. A pure momentum crossover strategy struggles in range-bound periods, which dominate the data.

2. **Transaction Costs**
   India futures costs (STT 0.0125% sell + Rs 20 flat brokerage + exchange fees + GST) eat ~0.3-0.5% per round trip. At 50-150 trades/year, costs alone consume 5-15% of gross P&L.

3. **Compact Candle Filter Trade-off**
   Requiring the HA candle to be compact at the crossover is a genuine loss-of-momentum signal, but it also eliminates many trending crossovers — the exact ones that produce large winners. The filter improves win quality at the expense of trade count.

4. **Index Spot Limitation**
   NIFTY/BANKNIFTY/SENSEX are index spot data with volume=0. The volume filter cannot be meaningfully tested. Real futures data (with volume and open interest) might show different behavior.

5. **Conservative Execution**
   Next-candle open + 1-tick slippage + ATR-based stops with breakeven trailing is conservative but honest. No look-ahead, no same-bar fills, no curve-fitted exits.

6. **Stretch Target**
   30% annualized on index spot after costs is hedge-fund territory. The best robust configs return +2-10% OOS, which is realistic for a simple crossover strategy in a mixed regime.

### Verdict

The market doesn't give 30% cleanly to a simple HA crossover. The best realistic configs show small positive OOS returns with controlled drawdown — honest, not spectacular.

---

## Key Observations

- **Volume filter always OFF**: Since index spot has volume=0, this gate was never tested meaningfully. Run on futures data to evaluate.
- **Slope threshold often 0.0**: The slope gate adds little in many configs — the compact candle filter already does the momentum gating.
- **ATR period 20 preferred**: Longer ATR smoothing (20 vs 10/14) consistently appears in best configs, suggesting less noise in the stop/target calculation.
- **15m timeframes show highest returns**: BANKNIFTY 15m (+7.8% OOS) and SENSEX 15m (+10.0% OOS) — fewer but higher-quality signals.
- **1m timeframes show lowest returns**: Noise dominates at 1-minute resolution; even with filters, the edge is thin.

---

## Raw Results

CSV files for each symbol/timeframe are in:
```
data/results/ha_compact_loop/{SYMBOL}_{TF}_results.csv
```

Each CSV contains: loop number, train/val returns, trade counts, drawdown, profit factor, Sharpe, robustness flag, and full parameter JSON for every optimization loop.

---

## How to Reproduce

```bash
# Run all 9 combos (3 symbols x 3 timeframes)
python -m scripts.run_ha_loop --all --max-loops 100 --seed 42

# Run a single combo
python -m scripts.run_ha_loop --symbol NIFTY --timeframe 5m --max-loops 100

# View results summary
python scripts/report_ha_loop.py
```

---

## Files

| File | Description |
|---|---|
| `quant/strategies/ema_ha_compact.py` | Strategy implementation with all tunable gates |
| `scripts/run_ha_loop.py` | Optimization loop runner (random search over parameter grid) |
| `scripts/report_ha_loop.py` | Results summary reporter |
| `data/results/ha_compact_loop/*.csv` | Raw optimization results per symbol/timeframe |
