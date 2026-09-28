"""C2026-09-REALDATA Phase 1: intraday on real NIFTY futures (D1).

Pre-registration section 5. Three trials only:

- P1a / P1b -- the prior campaign's frozen NIFTY ``orb_vwap`` configs,
  unchanged except that VWAP is now computed from real traded volume.
- P1c -- one gradient-boosting model on 5-minute bars, fitted on window A
  only, fixed hyper-parameters.

Windows: A 2026-07-01..08-12 (the user's 31 sessions), B 08-13..09-04,
C 09-07..09-25. Every D1 session is in the 0.05% STT regime.
"""

from __future__ import annotations

import json
from datetime import date, time
from pathlib import Path

import numpy as np
import polars as pl

import quant.strategies.orb_vwap  # noqa: F401  (registers the strategy)
from quant.backtest.costs import CostConfig, SlippageConfig
from quant.backtest.engine import BacktestConfig, run_backtest
from quant.backtest.execution import ExecutionConfig
from quant.backtest.exits import ExitConfig
from quant.backtest.india_costs import cost_config_for, leg_bps
from quant.backtest.market import MarketContext
from quant.candles.aggregation import aggregate_candles
from quant.strategies.base import STRATEGY_REGISTRY

OUT = Path("data/results/leaderboard/C2026-09-REALDATA")
D1_PATH = Path("data/processed/futures_continuous/NIFTY_2026Q3_1m.parquet")
WINDOWS = {
    "A_0701_0812": (date(2026, 7, 1), date(2026, 8, 12)),
    "B_0813_0904": (date(2026, 8, 13), date(2026, 9, 4)),
    "C_0907_0925": (date(2026, 9, 7), date(2026, 9, 25)),
}
FROZEN = {
    "P1a_orb_vwap_5m": (
        5,
        {"atr_period": 14, "min_or_atr": 1.5, "or_minutes": 30, "require_vwap": True},
    ),
    "P1b_orb_vwap_15m": (
        15,
        {"atr_period": 14, "min_or_atr": 0.5, "or_minutes": 30, "require_vwap": True},
    ),
}
EXITS = ExitConfig(eod_squareoff="15:15", stop_mode="signal", target_mode="signal")
LOT, TICK = 65, 0.10
CAPITAL = 1_000_000.0
BASE_COLS = ["timestamp", "open", "high", "low", "close", "volume", "open_interest"]


# ------------------------------------------------------------------ D1


def build_d1() -> pl.DataFrame:
    """Aug-2026 contract for July (disk), Sep-2026 contract from 2026-08-03."""
    jul = pl.read_parquet("data/raw/futures/NIFTY/2026-07/candles_1m.parquet").select(BASE_COLS)
    sep = pl.read_parquet(
        "data/raw/futures/NIFTY/upstox_v3/NIFTY_FUT_29_SEP_26/candles_1m.parquet"
    ).select(BASE_COLS)
    disk_aug = pl.read_parquet("data/raw/futures/NIFTY/2026-08/candles_1m.parquet").select(
        BASE_COLS
    )

    # the disk August file IS the Sep contract; the API copy must agree with it
    chk = disk_aug.join(sep, on="timestamp", suffix="_api")
    bad = (
        chk.filter((pl.col("close") - pl.col("close_api")).abs() > 1e-6).height
        + chk.filter(pl.col("volume") != pl.col("volume_api")).height
    )
    print(f"cross-check disk Aug 3-12 vs API Sep contract: {chk.height} bars, {bad} mismatches")

    d1 = pl.concat(
        [
            jul.with_columns(pl.lit("NIFTY FUT 25 AUG 26").alias("contract")),
            sep.filter(pl.col("timestamp").dt.date() >= date(2026, 8, 3)).with_columns(
                pl.lit("NIFTY FUT 29 SEP 26").alias("contract")
            ),
        ]
    )
    t = pl.col("timestamp").dt.time()
    d1 = (
        d1.filter((t >= time(9, 15)) & (t <= time(15, 29)))
        .unique(subset=["timestamp"])
        .sort("timestamp")
        .with_columns(
            pl.lit(LOT).alias("lot_size"),
            pl.lit(TICK * 100).alias("tick_size"),  # paise, the processed-data convention
            pl.lit("futures").alias("price_source"),
            pl.lit("NIFTY").alias("instrument"),
        )
    )
    D1_PATH.parent.mkdir(parents=True, exist_ok=True)
    d1.write_parquet(D1_PATH)
    days = d1["timestamp"].dt.date().n_unique()
    print(
        f"D1: {d1.height} bars, {days} sessions, {d1['timestamp'].min()} .. {d1['timestamp'].max()}"
    )
    return d1


# --------------------------------------------------------------- metrics


def window_metrics(daily: pl.DataFrame, trades: pl.DataFrame | None, lo: date, hi: date) -> dict:
    """``daily`` has one row per session with that session's net P&L (INR)."""
    w = daily.filter((pl.col("d") >= lo) & (pl.col("d") <= hi))
    pnl = w["net"].to_numpy()
    sd = pnl.std(ddof=1) if len(pnl) > 1 else float("nan")
    out = {
        "sessions": len(pnl),
        "net_pnl": float(pnl.sum()),
        "gross_pnl": float(w["gross"].sum()),
        "sharpe_daily_ann": float(pnl.mean() / sd * np.sqrt(252))
        if sd and sd > 0
        else float("nan"),
        "positive_days": int((pnl > 0).sum()),
    }
    if trades is not None:
        t = trades.filter(
            (pl.col("exit_time").dt.date() >= lo) & (pl.col("exit_time").dt.date() <= hi)
        )
        wins = t.filter(pl.col("net_pnl") > 0)["net_pnl"].sum()
        losses = -t.filter(pl.col("net_pnl") < 0)["net_pnl"].sum()
        out.update(
            trades=t.height,
            win_rate=float((t["net_pnl"] > 0).mean()) if t.height else float("nan"),
            profit_factor=float(wins / losses) if losses > 0 else float("nan"),
        )
    return out


def sessions_frame(frame: pl.DataFrame) -> pl.DataFrame:
    return frame.select(pl.col("timestamp").dt.date().unique().sort().alias("d"))


# ----------------------------------------------------- P1a / P1b (frozen)


def run_frozen(d1: pl.DataFrame, costs: CostConfig) -> dict:
    results = {}
    for name, (minutes, params) in FROZEN.items():
        frame = aggregate_candles(d1, minutes)
        spec = STRATEGY_REGISTRY["orb_vwap"]
        sig = spec.generate_signals(frame, params)
        proxy = bool(sig["vwap_is_proxy"][0]) if "vwap_is_proxy" in sig.columns else None

        # mechanical check (not a P&L trial): does real VWAP now bind?
        no_vwap = spec.generate_signals(frame, {**params, "require_vwap": False})
        sig_col = "signal_type"
        n_with = sig.filter(pl.col(sig_col).is_in(["BUY", "SELL"])).height
        n_without = no_vwap.filter(pl.col(sig_col).is_in(["BUY", "SELL"])).height

        cfg = BacktestConfig(
            market=MarketContext(
                symbol="NIFTY", price_source="futures", lot_size=LOT, tick_size_rupees=TICK
            ),
            costs=costs,
            execution=ExecutionConfig(slippage=SlippageConfig(mode="normal", tick_size=TICK)),
            exits=EXITS,
            position_size=1,
            initial_capital=CAPITAL,
        )
        res = run_backtest(frame, sig, cfg)
        tr = res.trades
        per_day = (
            tr.group_by(pl.col("exit_time").dt.date().alias("d")).agg(
                pl.col("net_pnl").sum().alias("net"), pl.col("gross_pnl").sum().alias("gross")
            )
            if tr.height
            else pl.DataFrame({"d": [], "net": [], "gross": []})
        )
        daily = sessions_frame(frame).join(per_day, on="d", how="left").fill_null(0.0)
        results[name] = {
            "timeframe_min": minutes,
            "params": params,
            "vwap_is_proxy": proxy,
            "entry_signals_with_vwap_filter": n_with,
            "entry_signals_without_vwap_filter": n_without,
            "windows": {k: window_metrics(daily, tr, lo, hi) for k, (lo, hi) in WINDOWS.items()},
        }
    return results


# ----------------------------------------------------------- P1c (ML)


def ml_features(d1: pl.DataFrame) -> pl.DataFrame:
    f = aggregate_candles(d1, 5).with_columns(
        d=pl.col("timestamp").dt.date(),
        tod=((pl.col("timestamp").dt.hour() - 9) * 60 + pl.col("timestamp").dt.minute() - 15),
    )
    tp = (pl.col("high") + pl.col("low") + pl.col("close")) / 3
    f = f.with_columns(
        vwap=((tp * pl.col("volume")).cum_sum() / pl.col("volume").cum_sum()).over("d"),
        r1=(pl.col("close") / pl.col("close").shift(1)).log().over("d"),
        r3=(pl.col("close") / pl.col("close").shift(3)).log().over("d"),
        r6=(pl.col("close") / pl.col("close").shift(6)).log().over("d"),
        doi3=(pl.col("open_interest") / pl.col("open_interest").shift(3) - 1).over("d"),
        hl=(pl.col("high") - pl.col("low")) / pl.col("close"),
        # target: return the fill actually earns -- enter open t+1, hold one bar
        y=(pl.col("open").shift(-2) / pl.col("open").shift(-1) - 1).over("d"),
        hold_start=pl.col("tod").shift(-1).over("d"),
    ).with_columns(dvwap=pl.col("close") / pl.col("vwap") - 1)
    # relative volume vs the same bar-of-day over the previous 10 sessions (causal)
    f = (
        f.sort("tod", "d")
        .with_columns(
            relvol=(
                pl.col("volume") / pl.col("volume").shift(1).rolling_mean(10, min_samples=3)
            ).over("tod")
        )
        .sort("timestamp")
    )
    return f


FEATS = ["r1", "r3", "r6", "dvwap", "relvol", "doi3", "tod", "hl"]
DEAD_BAND = 1e-4
FLAT_FROM_TOD = 360  # 15:15 is 360 minutes after 09:15


def run_ml(d1: pl.DataFrame) -> dict:
    from sklearn.ensemble import HistGradientBoostingRegressor

    f = ml_features(d1)
    lo_a, hi_a = WINDOWS["A_0701_0812"]
    ok = pl.all_horizontal(pl.col(c).is_not_null() & pl.col(c).is_finite() for c in [*FEATS, "y"])
    train = f.filter(ok & (pl.col("d") >= lo_a) & (pl.col("d") <= hi_a))
    model = HistGradientBoostingRegressor(
        max_depth=3, learning_rate=0.05, max_iter=200, random_state=0
    )
    model.fit(train.select(FEATS).to_numpy(), train["y"].to_numpy())

    X = f.select(FEATS).to_numpy()
    usable = (
        f.select(pl.all_horizontal(pl.col(c).is_not_null() & pl.col(c).is_finite() for c in FEATS))
        .to_series()
        .to_numpy()
    )
    pred = np.full(len(f), np.nan)
    pred[usable] = model.predict(X[usable])
    pos = np.where(pred > DEAD_BAND, 1.0, np.where(pred < -DEAD_BAND, -1.0, 0.0))
    hold_start = f["hold_start"].to_numpy()
    pos[
        (~np.isfinite(pred))
        | ~np.isfinite(hold_start.astype(float))
        | (hold_start >= FLAT_FROM_TOD)
    ] = 0.0

    f = f.with_columns(pos=pos, pred=pred)
    rows = []
    for d, g in f.group_by("d", maintain_order=True):
        p = g["pos"].to_numpy()
        y = np.nan_to_num(g["y"].to_numpy())
        px = g["close"].to_numpy()
        notional = LOT * px
        gross = float((p * y * notional).sum())
        prev = np.concatenate([[0.0], p[:-1]])
        steps = np.concatenate([p - prev, [-p[-1]]])  # final step closes whatever is left
        cost = 0.0
        day = d[0]
        for k, s in enumerate(steps):
            if s == 0:
                continue
            side = "buy" if s > 0 else "sell"
            cost += (
                abs(s)
                * leg_bps(side, day, price=float(px[min(k, len(px) - 1)]))
                / 1e4
                * notional[min(k, len(px) - 1)]
            )
        rows.append(
            {"d": day, "gross": gross, "net": gross - cost, "legs": float(np.abs(steps).sum())}
        )
    daily = pl.DataFrame(rows).sort("d")
    out = {
        "hyperparameters": {"max_depth": 3, "learning_rate": 0.05, "max_iter": 200},
        "train_rows": train.height,
        "windows": {},
    }
    for k, (lo, hi) in WINDOWS.items():
        m = window_metrics(daily, None, lo, hi)
        m["round_trips"] = float(
            daily.filter((pl.col("d") >= lo) & (pl.col("d") <= hi))["legs"].sum() / 2
        )
        out["windows"][k] = m
    return out


def main() -> int:
    d1 = build_d1()
    regime = cost_config_for(date(2026, 7, 1))  # every D1 session is after 2026-04-01
    results = {
        "prereg_sha256_prefix": json.loads((OUT / "prereg_seal.json").read_text())["prereg_sha256"][
            :16
        ],
        "cost_regime": {"stt_sell": regime.stt_rate, "exchange": regime.exchange_rate},
        "frozen_2026_costs": run_frozen(d1, regime),
        # diagnostic only -- same signals, the prior campaign's cost constants
        "frozen_prior_cost_model_diagnostic": run_frozen(d1, CostConfig()),
        "P1c_ml": run_ml(d1),
        "n_trials_phase1": 3,
    }
    OUT.mkdir(parents=True, exist_ok=True)
    (OUT / "phase1.json").write_text(json.dumps(results, indent=2, default=str), encoding="utf-8")
    print(json.dumps(results, indent=1, default=str))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
