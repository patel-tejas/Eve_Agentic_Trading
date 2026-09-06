# EMA Backtest Report (Simulated)

- Loop branch: hermes-loop
- Strategy: EMA fine-tune on 5min / 15min
- Symbols: NIFTY, BANKNIFTY (BN), SENSEX
- Mode: Simulation only (no live capital)
- Target: 30% return
- Logic: EMA cross + trend filter; iterate params until simulated PNL >= 30%
- Status: Script generated; bounded iterations only — unbounded live loop NOT executed per user safety scope (backtest-only confirmation).
- PNL: simulated cycle results written by script output (not guaranteed live).
