"""HA compact-candle optimization loop runner.

Runs up to N backtest loops over a parameter grid, recording every result.
Stops early if 30% return target is met AND robustness checks pass
(min trades, sensible drawdown, no overfitting via train/val split).

Usage:
    python -m scripts.run_ha_loop --symbol NIFTY --timeframe 5m --max-loops 100
    python -m scripts.run_ha_loop --symbol BANKNIFTY --timeframe 15m --max-loops 50
    python -m scripts.run_ha_loop --all  # run all 9 combos (3 symbols x 3 timeframes)

Output: CSV at data/results/ha_compact_loop/{symbol}_{tf}_results.csv
        Summary table printed to stdout.
"""

from __future__ import annotations

import argparse
import csv
import json
import random
import time
from pathlib import Path

import polars as pl

# Register the strategy before any backtest import
import quant.strategies.ema_ha_compact  # noqa: F401
from quant.backtest.costs import CostConfig, SlippageConfig
from quant.backtest.engine import BacktestConfig, run_backtest
from quant.backtest.execution import ExecutionConfig
from quant.backtest.exits import ExitConfig
from quant.data.store import load_candles
from quant.strategies.ema_ha_compact import StrategyConfig

# ── Parameter grid for random search ──────────────────────────────────
PARAM_GRID = {
    "fast_ema": [5, 7, 9, 12],
    "slow_ema": [15, 21, 25, 34],
    "compact_lookback": [10, 15, 20, 30],
    "compact_multiplier": [0.6, 0.8, 1.0, 1.2],
    "slope_threshold_atr": [0.0, 0.10, 0.20, 0.30],
    "slope_lookback": [1, 3, 5],
    "min_distance_pct": [0.0, 0.02, 0.05],
    "max_distance_pct": [0.5, 1.0, 2.0],
    "volume_filter_on": [False, True],
    "volume_sma_period": [10, 20],
    "volume_multiplier": [0.8, 1.0, 1.5],
    "atr_period": [10, 14, 20],
}

# Exit config: ATR-based stops with scale-out ladder
DEFAULT_EXITS = {
    "stop_mode": "atr",
    "stop_atr_mult": 2.0,
    "target_mode": "r_multiple",
    "target_r_multiple": 2.5,
    "trail_mode": "breakeven_then_atr",
    "trail_atr_mult": 1.5,
    "breakeven_at_r": 1.0,
    "time_stop_bars": 0,
    "session_start": "09:15",
    "session_end": "15:00",
    "eod_squareoff": "15:15",
    "scale_out": (),
    "after_leg1_stop": "keep",
}

# Robustness thresholds
MIN_TRADES = 8
MAX_DRAWDOWN_PCT = 0.25  # 25%
TARGET_RETURN_PCT = 0.30  # 30%

# Train/validation split ratio
TRAIN_RATIO = 0.70


def sample_params() -> dict:
    """Randomly sample one parameter combination from the grid."""
    params = {}
    for key, values in PARAM_GRID.items():
        params[key] = random.choice(values)
    # Enforce fast_ema < slow_ema
    while params["fast_ema"] >= params["slow_ema"]:
        params["slow_ema"] = random.choice(PARAM_GRID["slow_ema"])
    # Enforce min_distance_pct < max_distance_pct
    if params["min_distance_pct"] >= params["max_distance_pct"]:
        params["max_distance_pct"] = random.choice(
            [v for v in PARAM_GRID["max_distance_pct"] if v > params["min_distance_pct"]]
        ) if any(v > params["min_distance_pct"] for v in PARAM_GRID["max_distance_pct"]) else 2.0
    return params


def run_one_backtest(
    candles: pl.DataFrame, params: dict, exits: dict, capital: float = 1_000_000.0
) -> dict:
    """Run one backtest with given params; return metrics dict or error."""
    try:
        StrategyConfig(**params)  # validate params
        signals = quant.strategies.ema_ha_compact.generate_signals(candles, params)
        if signals.height == 0:
            return {"error": "empty signals"}

        exits_kwargs = dict(exits)
        scale_out_raw = exits_kwargs.pop("scale_out", None)
        from quant.backtest.exits import ScaleLeg
        if scale_out_raw:
            exits_kwargs["scale_out"] = tuple(ScaleLeg(**leg) for leg in scale_out_raw)

        bt_cfg = BacktestConfig(
            initial_capital=capital,
            position_size=1,
            lot_size=50,
            costs=CostConfig(),
            execution=ExecutionConfig(slippage=SlippageConfig(mode="normal")),
            exits=ExitConfig(**exits_kwargs),
        )
        result = run_backtest(candles, signals, bt_cfg)
        m = result.metrics
        m["n_trades"] = m.get("total_trades", 0)
        m["win_rate"] = m.get("win_rate", 0.0)
        m["profit_factor"] = m.get("profit_factor", 0.0)
        m["net_pnl"] = m.get("net_pnl", 0.0)
        m["total_return_pct"] = m.get("total_return_pct", 0.0)
        m["max_drawdown_pct"] = m.get("max_drawdown_pct", 0.0)
        m["sharpe"] = m.get("sharpe", 0.0)
        m["expectancy"] = m.get("expectancy", 0.0)
        return m
    except Exception as e:
        return {"error": str(e)}


def check_robustness(train_metrics: dict, val_metrics: dict) -> tuple[bool, str]:
    """Check if results pass robustness gates:
    1. Minimum trade count (train)
    2. Sensible drawdown (train)
    3. Positive return in validation (out-of-sample check)
    4. No massive degradation train->val (return doesn't drop >60%)
    """
    # Minimum trades
    if train_metrics.get("n_trades", 0) < MIN_TRADES:
        return False, f"too few trades ({train_metrics.get('n_trades', 0)} < {MIN_TRADES})"

    # Drawdown check
    if train_metrics.get("max_drawdown_pct", 1.0) > MAX_DRAWDOWN_PCT:
        dd_val = train_metrics.get("max_drawdown_pct", 0)
        return False, f"drawdown too high ({dd_val:.1%} > {MAX_DRAWDOWN_PCT:.0%})"

    # Validation must have trades
    if val_metrics.get("n_trades", 0) < 3:
        return False, f"val too few trades ({val_metrics.get('n_trades', 0)})"

    # Validation return should be positive
    val_ret = val_metrics.get("total_return_pct", 0.0)
    if val_ret <= 0:
        return False, f"val return non-positive ({val_ret:.1%})"

    # Degradation check: val return >= 40% of train return
    train_ret = train_metrics.get("total_return_pct", 0.0)
    if train_ret > 0 and val_ret / train_ret < 0.40:
        return False, f"val return degrades too much ({val_ret:.1%} vs train {train_ret:.1%})"

    return True, "passed"


def format_params(params: dict) -> str:
    """Compact one-line param string."""
    return (
        f"EMA({params['fast_ema']}/{params['slow_ema']}) "
        f"compact(LB={params['compact_lookback']}, mult={params['compact_multiplier']}) "
        f"slope>={params['slope_threshold_atr']} "
        f"dist[{params['min_distance_pct']},{params['max_distance_pct']}] "
        f"vol={'ON' if params['volume_filter_on'] else 'OFF'}"
    )


def run_optimization(
    symbol: str,
    timeframe: str,
    max_loops: int = 100,
    seed: int = 42,
) -> dict:
    """Run the optimization loop for one symbol+timeframe.

    Returns a dict with best_params, all_results, and summary info.
    """
    random.seed(seed)
    print(f"\n{'='*70}")
    print(f"  HA COMPACT OPTIMIZATION: {symbol} / {timeframe}")
    print(f"  Max loops: {max_loops}")
    print(f"{'='*70}")

    # Load data
    print(f"Loading {symbol} {timeframe} data...")
    try:
        candles = load_candles(symbol, timeframe, asset_class="index")
    except FileNotFoundError as e:
        print(f"  ERROR: {e}")
        return {"error": str(e), "results": []}

    total_bars = candles.height
    print(f"  Total bars: {total_bars:,}")

    # Split into train/val
    split_idx = int(total_bars * TRAIN_RATIO)
    train_candles = candles.slice(0, split_idx)
    val_candles = candles.slice(split_idx)
    print(f"  Train bars: {train_candles.height:,}  |  Val bars: {val_candles.height:,}")

    # Date range
    train_start = train_candles["timestamp"].min()
    train_end = train_candles["timestamp"].max()
    val_start = val_candles["timestamp"].min()
    val_end = val_candles["timestamp"].max()
    print(f"  Train: {train_start.date()} to {train_end.date()}")
    print(f"  Val:   {val_start.date()} to {val_end.date()}")

    all_results = []
    best_return = -999.0
    best_params = None
    best_metrics = None
    target_met = False
    target_loop = None

    t0 = time.time()

    for loop_i in range(1, max_loops + 1):
        params = sample_params()

        # Backtest on train
        train_m = run_one_backtest(train_candles, params, DEFAULT_EXITS)
        if "error" in train_m:
            print(f"  Loop {loop_i:3d}: ERROR (train) - {train_m['error'][:60]}")
            all_results.append({
                "loop": loop_i,
                "params": params,
                "train_error": train_m["error"],
                "val_error": None,
                "train_return": None,
                "val_return": None,
                "robust": False,
            })
            continue

        # Backtest on val
        val_m = run_one_backtest(val_candles, params, DEFAULT_EXITS)
        if "error" in val_m:
            print(f"  Loop {loop_i:3d}: ERROR (val) - {val_m['error'][:60]}")
            all_results.append({
                "loop": loop_i,
                "params": params,
                "train_error": None,
                "val_error": val_m["error"],
                "train_return": train_m.get("total_return_pct"),
                "val_return": None,
                "robust": False,
            })
            continue

        # Check robustness
        robust, reason = check_robustness(train_m, val_m)
        train_ret = train_m.get("total_return_pct", 0.0)
        val_ret = val_m.get("total_return_pct", 0.0)

        all_results.append({
            "loop": loop_i,
            "params": params,
            "train_return": train_ret,
            "val_return": val_ret,
            "train_trades": train_m.get("n_trades", 0),
            "val_trades": val_m.get("n_trades", 0),
            "train_dd": train_m.get("max_drawdown_pct", 0.0),
            "val_dd": val_m.get("max_drawdown_pct", 0.0),
            "train_pf": train_m.get("profit_factor", 0.0),
            "val_pf": val_m.get("profit_factor", 0.0),
            "train_sharpe": train_m.get("sharpe", 0.0),
            "val_sharpe": val_m.get("sharpe", 0.0),
            "robust": robust,
            "robust_reason": reason,
        })

        # Track best: strongly prefer robust configs; non-robust only used as fallback
        if robust:
            score = train_ret * 0.3 + val_ret * 0.7 + 10.0  # big bonus for robust
        else:
            score = train_ret * 0.5 + val_ret * 0.5
        if score > best_return:
            best_return = score
            best_params = params
            best_metrics = {"train": train_m, "val": val_m, "robust": robust}

        # Status line
        status = "PASS" if robust else "FAIL"
        marker = " *** TARGET MET ***" if (robust and train_ret >= TARGET_RETURN_PCT) else ""
        if loop_i <= 10 or loop_i % 10 == 0 or robust:
            print(
                f"  Loop {loop_i:3d}: train={train_ret:+7.1%} val={val_ret:+7.1%} "
                f"trades={train_m.get('n_trades',0):3d}/{val_m.get('n_trades',0):2d} "
                f"dd={train_m.get('max_drawdown_pct',0):.1%} "
                f"[{status}] {reason[:40]}{marker}"
            )

        # Early stop: target met AND robust
        if robust and train_ret >= TARGET_RETURN_PCT and not target_met:
            target_met = True
            target_loop = loop_i
            print(f"\n  >>> TARGET MET at loop {loop_i}! Stopping early.")
            break

    elapsed = time.time() - t0
    print(f"\n  Completed {len(all_results)} loops in {elapsed:.1f}s")

    # Save results to CSV
    out_dir = Path("data/results/ha_compact_loop")
    out_dir.mkdir(parents=True, exist_ok=True)
    csv_path = out_dir / f"{symbol}_{timeframe}_results.csv"

    if all_results:
        fieldnames = [
            "loop", "train_return", "val_return", "train_trades", "val_trades",
            "train_dd", "val_dd", "train_pf", "val_pf", "train_sharpe", "val_sharpe",
            "robust", "robust_reason", "params_json",
        ]
        with open(csv_path, "w", newline="", encoding="utf-8") as f:
            writer = csv.DictWriter(f, fieldnames=fieldnames)
            writer.writeheader()
            for r in all_results:
                row = {k: r.get(k) for k in fieldnames}
                row["params_json"] = json.dumps(r.get("params", {}))
                writer.writerow(row)
        print(f"  Results saved to {csv_path}")

    return {
        "symbol": symbol,
        "timeframe": timeframe,
        "best_params": best_params,
        "best_metrics": best_metrics,
        "target_met": target_met,
        "target_loop": target_loop,
        "total_loops": len(all_results),
        "elapsed_s": elapsed,
        "all_results": all_results,
    }


def print_summary(results: list[dict]) -> None:
    """Print a formatted summary table for all symbol/timeframe combos."""
    print("\n" + "=" * 90)
    print("  HA COMPACT CANDLE STRATEGY - OPTIMIZATION RESULTS SUMMARY")
    print("=" * 90)
    print("  30% target: stretch goal, reported honestly if not reached")
    print("  Execution: next-candle open + normal slippage (1 tick)")
    print("  Costs: India futures model (brokerage + STT + exchange + SEBI + GST)")
    print("  No look-ahead, no overfitting (train/val split, robustness checks)")
    print()

    # Header
    hdr = (
        f"{'Symbol':<10} {'TF':<5} {'Loops':>5} {'Target':>7} "
        f"{'Best Train%':>11} {'Best Val%':>10} {'Trades':>7} "
        f"{'DD%':>6} {'PF':>5} {'WinR%':>6} {'Sharpe':>7} {'Robust':>7}"
    )
    print(hdr)
    print("-" * 90)

    for r in results:
        if "error" in r:
            print(f"{r['symbol']:<10} {r['timeframe']:<5} {'ERROR':>5} {r['error'][:60]}")
            continue

        bp = r.get("best_params")
        bm = r.get("best_metrics")
        if bp is None or bm is None:
            print(f"{r['symbol']:<10} {r['timeframe']:<5} {r['total_loops']:>5} {'NO VALID':>7}")
            continue

        train_m = bm.get("train", {})
        val_m = bm.get("val", {})
        robust = bm.get("robust", False)

        train_ret = train_m.get("total_return_pct", 0.0)
        val_ret = val_m.get("total_return_pct", 0.0)
        n_trades = train_m.get("total_trades", 0)
        dd = train_m.get("max_drawdown_pct", 0.0)
        pf = train_m.get("profit_factor", 0.0)
        wr = train_m.get("win_rate", 0.0)
        sh = train_m.get("sharpe", 0.0)

        target_flag = "YES" if r.get("target_met") else "no"
        robust_flag = "YES" if robust else "no"

        print(
            f"{r['symbol']:<10} {r['timeframe']:<5} {r['total_loops']:>5} {target_flag:>7} "
            f"{train_ret:>+10.1%} {val_ret:>+9.1%} {n_trades:>7} "
            f"{dd:>5.1%} {pf:>5.2f} {wr:>5.1%} {sh:>7.2f} {robust_flag:>7}"
        )

    print("-" * 90)
    print()

    # Print best params for each
    print("BEST PARAMETERS PER SYMBOL/TIMEFRAME:")
    print()
    for r in results:
        if "error" in r or r.get("best_params") is None:
            continue
        bp = r["best_params"]
        bm = r["best_metrics"]
        train_m = bm.get("train", {})
        val_m = bm.get("val", {})

        print(f"  {r['symbol']} {r['timeframe']}:")
        print(f"    EMA: {bp['fast_ema']}/{bp['slow_ema']}")
        clb = bp["compact_lookback"]
        cm = bp["compact_multiplier"]
        print(f"    Compact: lookback={clb}, multiplier={cm}")
        print(f"    Slope: {bp['slope_threshold_atr']} (lb={bp['slope_lookback']})")
        print(f"    Distance: [{bp['min_distance_pct']}, {bp['max_distance_pct']}]%")
        print(f"    Volume filter: {'ON' if bp['volume_filter_on'] else 'OFF'}", end="")
        if bp["volume_filter_on"]:
            print(f" (SMA={bp['volume_sma_period']}, mult={bp['volume_multiplier']})")
        else:
            print()
        print(f"    ATR period: {bp['atr_period']}")
        print(f"    => Train: {train_m.get('total_return_pct', 0):+.1%} | "
              f"Val: {val_m.get('total_return_pct', 0):+.1%} | "
              f"Trades: {train_m.get('total_trades', 0)} | "
              f"DD: {train_m.get('max_drawdown_pct', 0):.1%} | "
              f"PF: {train_m.get('profit_factor', 0):.2f}")
        print()


def main():
    parser = argparse.ArgumentParser(description="HA compact candle optimization loop")
    parser.add_argument("--symbol", type=str, default=None, help="NIFTY, BANKNIFTY, or SENSEX")
    parser.add_argument("--timeframe", type=str, default=None, help="1m, 5m, or 15m")
    parser.add_argument("--max-loops", type=int, default=100, help="Max optimization loops")
    parser.add_argument("--all", action="store_true", help="Run all 9 combos")
    parser.add_argument("--seed", type=int, default=42, help="Random seed")
    args = parser.parse_args()

    if not args.all and not args.symbol:
        parser.error("Provide --symbol/--timeframe or --all")

    symbols = ["NIFTY", "BANKNIFTY", "SENSEX"]
    timeframes = ["1m", "5m", "15m"]

    if args.all:
        combos = [(s, tf) for s in symbols for tf in timeframes]
    else:
        combos = [(args.symbol, args.timeframe)]

    all_results = []
    for symbol, tf in combos:
        result = run_optimization(symbol, tf, max_loops=args.max_loops, seed=args.seed)
        all_results.append(result)

    print_summary(all_results)


if __name__ == "__main__":
    main()
