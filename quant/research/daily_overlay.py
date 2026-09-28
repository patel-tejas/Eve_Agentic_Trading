"""Low-turnover daily exposure overlays on Indian index futures.

Campaign ``C2026-09-LOWTURN``. Pre-registration:
``plans/2026-09-27-low-turnover-preregistration.md``.

Why this module exists
----------------------
Campaign ``C2026-09-EMA-SMC`` ran ~33,000 intraday price-shape backtests
and passed 0 of 42 cells. The measured reason is not parameterisation: on
the index data in this repo the *intraday* leg (open->close) has negative
drift while the *overnight* leg (close->open) carries all of it, so every
strategy in that campaign traded the losing half of the day.

The obvious response -- hold overnight only -- was measured and rejected
before this module was written: at a corrected round-trip friction of
~2.9 bps plus ~1.8 bps/night of futures carry, the entire gross edge
sits in the first minute after the open, and the 09:15 index print is an
auction-derived value that is not transactable.

What is left is the region the prior campaign never searched. At ~2.9 bps
a round trip, trading 250x/year costs ~725 bps/year, so friction only
stops mattering when turnover is low. This module therefore manages
*exposure* on daily closes and rebalances rarely.

Conventions that matter
-----------------------
- **Fill rule**: the signal uses closes up to and including day ``t``;
  the exposure it sets is earned over ``t -> t+1``. Rebalance costs are
  charged on day ``t``, the day the trade happens. There is no same-bar
  fill and the opening print is never used.
- **Exposure** is a continuous fraction of notional in ``[0, cap]``.
  Lot granularity is a reported caveat, not modelled.
- **Carry and roll are charged to every long hold, including the
  buy-and-hold benchmark.** In/out overlays pay them only while long, so
  omitting them from the benchmark biases the comparison.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import date
from pathlib import Path

import numpy as np
import polars as pl

from quant.backtest import india_costs

DAILY_ROOT = Path("data/processed/index_daily")
TRADING_DAYS = 252

# Frozen splits for THIS campaign. DISCOVERY_SPLITS in protocol.py is
# deliberately not touched, so the prior campaign's protocol_hash() is
# unchanged and its seal stays valid.
DAILY_SPLITS: dict[str, tuple[date, date]] = {
    "train": (date(2006, 1, 1), date(2024, 12, 31)),
    "val": (date(2025, 1, 1), date(2025, 12, 31)),
    "test": (date(2026, 1, 1), date(2026, 9, 5)),
}
WARMUP_START = date(2005, 1, 3)

# STT on futures SALES rose 0.0125% -> 0.02% effective 2024-10-01.
STT_CHANGE = date(2024, 10, 1)
STT_OLD, STT_NEW = 0.000125, 0.0002


@dataclass(frozen=True)
class CostModel:
    """Per-leg Indian index-futures friction, as a fraction of notional."""

    # None = the dated statutory schedule in quant.backtest.india_costs
    # (corrected 2026-09-28: 0.00345% was the cash-segment rate and 0.003%
    # the intraday-equity stamp duty; futures pay 0.0019%/0.00173% and 0.002%).
    exchange_rate: float | None = None
    sebi_rate: float = 0.000001
    stamp_rate: float = 0.00002  # buy leg only
    gst_rate: float = 0.18
    brokerage_flat: float = 20.0  # INR per order
    notional_per_order: float = 1_560_000.0  # ~1 NIFTY lot, for the flat fee
    slippage_ticks: float = 1.0
    tick_rupees: float = 0.10
    price_level: float = 24_000.0
    # None keeps the dated statutory schedule (0.01% -> 0.0125% on
    # 2023-04-01 -> 0.02% on 2024-10-01 -> 0.05% on 2026-04-01). An explicit
    # value overrides it, which is what makes a
    # zero-friction control run possible; every other component can
    # already be zeroed, and STT should not be the one exception.
    stt_override: float | None = None

    def stt_rate(self, on: date) -> float:
        if self.stt_override is not None:
            return self.stt_override
        return india_costs.stt_sell_rate(on)

    def leg_bps(self, *, side: str, on: date) -> float:
        """Friction for one leg, in bps of the traded notional."""
        stt = self.stt_rate(on) if side == "sell" else 0.0
        stamp = self.stamp_rate if side == "buy" else 0.0
        exch = (
            self.exchange_rate if self.exchange_rate is not None else india_costs.exchange_rate(on)
        )
        brokerage = self.brokerage_flat / self.notional_per_order
        gst = (brokerage + exch) * self.gst_rate
        slip = self.slippage_ticks * self.tick_rupees / self.price_level
        total = stt + stamp + exch + self.sebi_rate + brokerage + gst + slip
        return total * 1e4

    def round_trip_bps(self, on: date) -> float:
        return self.leg_bps(side="buy", on=on) + self.leg_bps(side="sell", on=on)


@dataclass(frozen=True)
class RunConfig:
    """Everything that can change a number, in one frozen object."""

    r_minus_q: float = 0.053  # futures carry: financing minus dividend yield
    friction_multiple: float = 1.0  # stress knob; 1.5 is a required robustness run
    costs: CostModel = field(default_factory=CostModel)
    monthly_roll: bool = True


# ---------------------------------------------------------------- data


def load_daily(symbol: str) -> pl.DataFrame:
    path = DAILY_ROOT / symbol / "daily.parquet"
    if not path.exists():
        raise FileNotFoundError(f"{path} missing; run scripts/download_index_daily.py first")
    return (
        pl.read_parquet(path)
        .select("d", "open", "high", "low", "close")
        .sort("d")
        .unique(subset=["d"], keep="first")
        .sort("d")
    )


def add_features(df: pl.DataFrame) -> pl.DataFrame:
    """Signal inputs. Every one uses only closes at or before its own row."""
    logret = (pl.col("close") / pl.col("close").shift(1)).log()
    return df.with_columns(
        logret=logret,
        gross_ret=pl.col("close") / pl.col("close").shift(1) - 1,
        sma200=pl.col("close").rolling_mean(200),
        mom252=pl.col("close") / pl.col("close").shift(TRADING_DAYS) - 1,
        mom60=pl.col("close") / pl.col("close").shift(60) - 1,
        rv20=logret.rolling_std(20) * np.sqrt(TRADING_DAYS),
    )


# ---------------------------------------------------- exposure overlays
# Each returns exposure decided at close t, earned over t -> t+1.
# Parameter values are the frozen literature defaults in the
# pre-registration and are NOT tuned.

TARGET_VOL = 0.12
REBALANCE_BAND = 0.25
EXPOSURE_CAP = 1.0


def _banded(raw: np.ndarray, band: float = REBALANCE_BAND) -> np.ndarray:
    """Hold the previous exposure until the target moves by ``band``.

    Turnover control. Without it a vol-target overlay retrades daily and
    friction dominates, which is the whole trap this campaign avoids.
    """
    out = np.zeros_like(raw)
    current = 0.0
    for i, want in enumerate(raw):
        if not np.isfinite(want):
            out[i] = 0.0
            continue
        if abs(want - current) > band:
            current = want
        out[i] = current
    return out


def expo_buy_hold(f: pl.DataFrame) -> np.ndarray:
    """B0: always fully long. The benchmark, and it pays carry and roll."""
    return np.ones(len(f))


def expo_vol_managed(f: pl.DataFrame) -> np.ndarray:
    """H1: scale exposure by target_vol / realised_vol (Moreira & Muir 2017)."""
    rv = f["rv20"].to_numpy()
    with np.errstate(divide="ignore", invalid="ignore"):
        raw = np.clip(TARGET_VOL / rv, 0.0, EXPOSURE_CAP)
    return _banded(raw)


def expo_tsmom(f: pl.DataFrame) -> np.ndarray:
    """H2: long while the trailing 12-month return is positive (MOP 2012)."""
    m = f["mom252"].to_numpy()
    return np.where(np.isfinite(m) & (m > 0), 1.0, 0.0)


def expo_sma200(f: pl.DataFrame) -> np.ndarray:
    """H3: long while close is above its 200-day average."""
    c, s = f["close"].to_numpy(), f["sma200"].to_numpy()
    return np.where(np.isfinite(s) & (c > s), 1.0, 0.0)


def expo_sma200_volmanaged(f: pl.DataFrame) -> np.ndarray:
    """H4: H3's gate with H1's sizing."""
    return expo_sma200(f) * expo_vol_managed(f)


SINGLE_ASSET_OVERLAYS = {
    "B0_buy_hold": expo_buy_hold,
    "H1_vol_managed": expo_vol_managed,
    "H2_tsmom_12m": expo_tsmom,
    "H3_sma200": expo_sma200,
    "H4_sma200_volmanaged": expo_sma200_volmanaged,
}


# ------------------------------------------------------------ backtest


def backtest(f: pl.DataFrame, exposure: np.ndarray, cfg: RunConfig | None = None) -> pl.DataFrame:
    """Daily net returns for one exposure path.

    ``daily_net[t] = e[t-1]*gross[t] - carry(t-1->t)*e[t-1] - tc[t]``

    ``tc[t]`` is the cost of moving from ``e[t-1]`` to ``e[t]`` at close
    ``t`` plus, on a month end, the roll on whatever is still held. The
    exposure earning day ``t``'s return was fixed at close ``t-1``, so
    nothing here can see its own outcome.
    """
    cfg = cfg or RunConfig()
    dates = f["d"].to_list()
    gross = np.nan_to_num(f["gross_ret"].to_numpy(), nan=0.0)
    e = np.asarray(exposure, dtype=float)
    n = len(f)

    cal_days = np.ones(n)
    for i in range(1, n):
        cal_days[i] = max((dates[i] - dates[i - 1]).days, 1)

    month_end = np.zeros(n, dtype=bool)
    for i in range(n - 1):
        if dates[i].month != dates[i + 1].month:
            month_end[i] = True

    prev_e = np.concatenate([[0.0], e[:-1]])
    carry = cfg.r_minus_q / 365.0 * cal_days * prev_e

    tc = np.zeros(n)
    for i in range(n):
        delta = e[i] - (e[i - 1] if i else 0.0)
        if abs(delta) > 1e-12:
            side = "buy" if delta > 0 else "sell"
            tc[i] += abs(delta) * cfg.costs.leg_bps(side=side, on=dates[i]) / 1e4
        if cfg.monthly_roll and month_end[i] and abs(e[i]) > 0:  # shorts roll too
            tc[i] += abs(e[i]) * cfg.costs.round_trip_bps(dates[i]) / 1e4
    tc *= cfg.friction_multiple

    net = prev_e * gross - carry - tc
    return pl.DataFrame(
        {
            "d": dates,
            "exposure": e,
            "gross_ret": gross,
            "pos_ret": prev_e * gross,
            "carry": carry,
            "tc": tc,
            "net_ret": net,
        }
    )


# ------------------------------------------------------------- metrics


def _max_drawdown(net: np.ndarray) -> float:
    eq = np.cumprod(1.0 + net)
    return float((eq / np.maximum.accumulate(eq) - 1.0).min())


def metrics(bt: pl.DataFrame) -> dict[str, float]:
    net = bt["net_ret"].to_numpy()
    n = len(net)
    if n < 2:
        return {}
    mu, sd = float(net.mean()), float(net.std(ddof=1))
    years = n / TRADING_DAYS
    total = float(np.prod(1.0 + net))
    cagr = total ** (1.0 / years) - 1.0 if total > 0 and years > 0 else float("nan")
    mdd = _max_drawdown(net)
    gross_sum = float(bt["pos_ret"].sum())
    fric_sum = float(bt["tc"].sum() + bt["carry"].sum())
    turn = float(np.abs(np.diff(bt["exposure"].to_numpy(), prepend=0.0)).sum())
    return {
        "n_days": n,
        "cagr": cagr,
        "ann_vol": sd * np.sqrt(TRADING_DAYS),
        "sharpe": (mu / sd) * np.sqrt(TRADING_DAYS) if sd > 0 else float("nan"),
        "max_dd": mdd,
        "calmar": cagr / abs(mdd) if mdd < 0 else float("nan"),
        "total_return": total - 1.0,
        "mean_bps": mu * 1e4,
        "avg_exposure": float(bt["exposure"].mean()),
        "turnover_per_yr": turn / years if years > 0 else float("nan"),
        "friction_pct_of_gross": (fric_sum / gross_sum * 100.0) if gross_sum > 0 else float("nan"),
    }


def slice_split(bt: pl.DataFrame, split: str) -> pl.DataFrame:
    lo, hi = DAILY_SPLITS[split]
    return bt.filter((pl.col("d") >= lo) & (pl.col("d") <= hi))


# ----------------------------------------------------------- inference


def block_bootstrap_ci(
    diff: np.ndarray,
    *,
    block: int = 20,
    n_boot: int = 10_000,
    seed: int = 7,
    alpha: float = 0.05,
) -> dict[str, float]:
    """Circular block bootstrap CI for the mean and Sharpe of ``diff``.

    Blocks, not iid draws: daily index returns and an overlay's exposure
    are both autocorrelated, and an iid bootstrap would understate the
    interval. Used for the paired (strategy - benchmark) series, which is
    the pre-registered primary test.
    """
    rng = np.random.default_rng(seed)
    n = len(diff)
    if n < block * 2:
        return {}
    n_blocks = int(np.ceil(n / block))
    starts = rng.integers(0, n, size=(n_boot, n_blocks))
    idx = (starts[:, :, None] + np.arange(block)[None, None, :]) % n
    samples = diff[idx.reshape(n_boot, -1)[:, :n]]
    means = samples.mean(axis=1)
    sds = samples.std(axis=1, ddof=1)
    with np.errstate(divide="ignore", invalid="ignore"):
        sharpes = np.where(sds > 0, means / sds * np.sqrt(TRADING_DAYS), np.nan)
    lo, hi = 100 * alpha / 2, 100 * (1 - alpha / 2)
    return {
        "mean_bps": float(diff.mean() * 1e4),
        "mean_lo_bps": float(np.percentile(means, lo) * 1e4),
        "mean_hi_bps": float(np.percentile(means, hi) * 1e4),
        "sharpe": float(diff.mean() / diff.std(ddof=1) * np.sqrt(TRADING_DAYS)),
        "sharpe_lo": float(np.nanpercentile(sharpes, lo)),
        "sharpe_hi": float(np.nanpercentile(sharpes, hi)),
        "excludes_zero": bool(np.percentile(means, lo) > 0),
    }


def yearly_table(bt: pl.DataFrame) -> pl.DataFrame:
    return (
        bt.with_columns(y=pl.col("d").dt.year())
        .group_by("y")
        .agg(
            ((1.0 + pl.col("net_ret")).product() - 1.0).alias("ret"),
            pl.len().alias("n"),
        )
        .sort("y")
    )
