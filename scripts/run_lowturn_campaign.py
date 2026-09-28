"""Run campaign C2026-09-LOWTURN end to end.

Pre-registration: ``plans/2026-09-27-low-turnover-preregistration.md``
(its SHA-256 is recorded in the seal and printed in the report).

The candidate list is frozen and nothing is tuned, so there is no
train-then-select step to bias: every overlay is scored on every split
and all of it is reported. The multiple-testing exposure is exactly the
5 pre-registered candidates, handled by the deflated Sharpe at N=5 and,
conservatively, N=20.
"""

from __future__ import annotations

import hashlib
import json
import sys
from datetime import date, datetime
from pathlib import Path

import numpy as np
import polars as pl

from quant.research.daily_overlay import (
    DAILY_SPLITS,
    SINGLE_ASSET_OVERLAYS,
    RunConfig,
    add_features,
    backtest,
    block_bootstrap_ci,
    expo_buy_hold,
    load_daily,
    metrics,
    slice_split,
    yearly_table,
)
from quant.research.multiple_testing import deflated_sharpe_ratio

CAMPAIGN = "C2026-09-LOWTURN"
PREREG = Path("plans/2026-09-27-low-turnover-preregistration.md")
OUT = Path("data/results/leaderboard") / CAMPAIGN
# --corrected (2026-09-28): fill at close t+1 as pre-registered in A1.2 (the
# original run filled at close t), dated cost schedule incl. 0.05% STT from
# 2026-04-01. Written to a subfolder so the original results stay intact.
CORRECTED = "--corrected" in sys.argv
if CORRECTED:
    OUT = OUT / "corrected_2026-09-28"
FILL_LAG = 1 if CORRECTED else 0


def lag(e: np.ndarray) -> np.ndarray:
    """Shift exposure so a close-t signal is entered at close t+FILL_LAG."""
    e = np.asarray(e, dtype=float)
    return np.concatenate([np.zeros(FILL_LAG), e[: len(e) - FILL_LAG]]) if FILL_LAG else e


SYMBOLS = ["NIFTY", "BANKNIFTY", "SENSEX"]


def seal() -> dict:
    OUT.mkdir(parents=True, exist_ok=True)
    if CORRECTED:  # a correction re-uses the original seal; it never re-seals
        return json.loads((OUT.parent / "prereg_seal.json").read_text(encoding="utf-8"))
    digest = hashlib.sha256(PREREG.read_bytes()).hexdigest()
    path = OUT / "prereg_seal.json"
    if path.exists():
        prior = json.loads(path.read_text(encoding="utf-8"))
        if prior["prereg_sha256"] != digest:
            print(
                "!! WARNING: pre-registration changed after the first run.\n"
                f"   sealed {prior['prereg_sha256'][:16]} != now {digest[:16]}"
            )
        return prior
    rec = {
        "campaign": CAMPAIGN,
        "prereg_sha256": digest,
        "sealed_at": datetime.now().isoformat(timespec="seconds"),
        "splits": {k: [d.isoformat() for d in v] for k, v in DAILY_SPLITS.items()},
        "n_trials_frozen": len(SINGLE_ASSET_OVERLAYS) - 1 + 1,  # H1-H4 + H5
    }
    path.write_text(json.dumps(rec, indent=2), encoding="utf-8")
    return rec


# ---- H5: cross-index relative momentum (needs two symbols jointly) ----


def h5_frames(cfg: RunConfig) -> tuple[pl.DataFrame, pl.DataFrame]:
    """Hold whichever of NIFTY/BANKNIFTY has the higher 60-day return.

    Benchmark is 50/50 buy-and-hold of the same pair. A switch exits one
    leg and enters the other -- two legs, i.e. one round trip -- which is
    charged by running each leg's exposure through the normal cost path.
    """
    a = add_features(load_daily("NIFTY"))
    b = add_features(load_daily("BANKNIFTY"))
    j = (
        a.select("d", "mom60", "gross_ret")
        .rename({"mom60": "m_a", "gross_ret": "g_a"})
        .join(
            b.select("d", "mom60", "gross_ret").rename({"mom60": "m_b", "gross_ret": "g_b"}),
            on="d",
            how="inner",
        )
        .sort("d")
    )

    ma, mb = j["m_a"].to_numpy(), j["m_b"].to_numpy()
    valid = np.isfinite(ma) & np.isfinite(mb)
    pick_a = np.where(valid & (ma >= mb), 1.0, 0.0)
    pick_b = np.where(valid & (ma < mb), 1.0, 0.0)

    fa = a.filter(pl.col("d").is_in(j["d"])).sort("d")
    fb = b.filter(pl.col("d").is_in(j["d"])).sort("d")

    strat = _combine(fa, fb, lag(pick_a), lag(pick_b), cfg)
    bench = _combine(fa, fb, np.full(len(j), 0.5), np.full(len(j), 0.5), cfg)
    return strat, bench


def _combine(fa, fb, ea, eb, cfg) -> pl.DataFrame:
    ba, bb = backtest(fa, ea, cfg), backtest(fb, eb, cfg)
    return pl.DataFrame(
        {
            "d": ba["d"],
            "exposure": ba["exposure"] + bb["exposure"],
            "gross_ret": ba["gross_ret"],
            "pos_ret": ba["pos_ret"] + bb["pos_ret"],
            "carry": ba["carry"] + bb["carry"],
            "tc": ba["tc"] + bb["tc"],
            "net_ret": ba["net_ret"] + bb["net_ret"],
        }
    )


# ------------------------------------------------------------- runner


def run(cfg: RunConfig, label: str) -> list[dict]:
    rows = []
    for sym in SYMBOLS:
        f = add_features(load_daily(sym))
        bench_bt = backtest(f, expo_buy_hold(f), cfg)
        for name, fn in SINGLE_ASSET_OVERLAYS.items():
            bt = backtest(f, lag(fn(f)), cfg)
            rows.extend(_score(bt, bench_bt, sym, name, label))
    sa, sb = h5_frames(cfg)
    rows.extend(_score(sa, sb, "NIFTY+BANKNIFTY", "H5_cross_index_mom", label))
    return rows


def _score(bt, bench, sym, name, label) -> list[dict]:
    out = []
    for split in ("train", "val", "test"):
        w, wb = slice_split(bt, split), slice_split(bench, split)
        if len(w) < 30:
            continue
        m = metrics(w)
        mb = metrics(wb)
        diff = w["net_ret"].to_numpy() - wb["net_ret"].to_numpy()
        ci = block_bootstrap_ci(diff) if name != "B0_buy_hold" else {}
        out.append(
            {
                "cfg": label,
                "symbol": sym,
                "strategy": name,
                "split": split,
                **{
                    k: m.get(k)
                    for k in (
                        "n_days",
                        "cagr",
                        "ann_vol",
                        "sharpe",
                        "max_dd",
                        "calmar",
                        "total_return",
                        "mean_bps",
                        "avg_exposure",
                        "turnover_per_yr",
                        "friction_pct_of_gross",
                    )
                },
                "bench_sharpe": mb.get("sharpe"),
                "bench_max_dd": mb.get("max_dd"),
                "bench_cagr": mb.get("cagr"),
                "d_sharpe": (m.get("sharpe") or 0) - (mb.get("sharpe") or 0),
                "vs_bench_mean_bps": ci.get("mean_bps"),
                "vs_bench_lo_bps": ci.get("mean_lo_bps"),
                "vs_bench_hi_bps": ci.get("mean_hi_bps"),
                "vs_bench_excl_zero": ci.get("excludes_zero"),
                "net_daily": w["net_ret"].to_numpy(),
            }
        )
    return out


def main() -> int:
    rec = seal()
    print(f"campaign {CAMPAIGN}  prereg sha256 {rec['prereg_sha256'][:16]}...")
    print(f"splits: {rec['splits']}\n")

    configs = [
        (RunConfig(), "base"),
        (RunConfig(friction_multiple=1.5), "friction x1.5"),
        (RunConfig(r_minus_q=0.03), "r-q=3%"),
        (RunConfig(r_minus_q=0.07), "r-q=7%"),
    ]
    all_rows = []
    for cfg, label in configs:
        all_rows.extend(run(cfg, label))

    df = pl.DataFrame([{k: v for k, v in r.items() if k != "net_daily"} for r in all_rows])
    OUT.mkdir(parents=True, exist_ok=True)
    df.write_parquet(OUT / "results.parquet")

    # deflated Sharpe on the base config, per split, across the frozen list
    base = [r for r in all_rows if r["cfg"] == "base"]
    dsr_rows = []
    for split in ("train", "val", "test"):
        cells = [r for r in base if r["split"] == split and r["strategy"] != "B0_buy_hold"]
        if not cells:
            continue
        trial_sharpes = [
            float(np.mean(r["net_daily"]) / np.std(r["net_daily"], ddof=1)) for r in cells
        ]
        for r in cells:
            for n_trials in (5, 20):
                res = deflated_sharpe_ratio(
                    list(r["net_daily"]), n_trials=n_trials, trial_sharpes=trial_sharpes
                )
                dsr_rows.append(
                    {
                        "split": split,
                        "symbol": r["symbol"],
                        "strategy": r["strategy"],
                        "n_trials": n_trials,
                        "dsr": res.deflated_sharpe,
                        "observed_sharpe_daily": res.observed_sharpe,
                        "expected_max_sharpe": res.expected_max_sharpe,
                    }
                )
    pl.DataFrame(dsr_rows).write_parquet(OUT / "dsr.parquet")

    # yearly table for the base config
    yr_rows = []
    for sym in SYMBOLS:
        f = add_features(load_daily(sym))
        for name, fn in SINGLE_ASSET_OVERLAYS.items():
            bt = backtest(f, lag(fn(f)), RunConfig())
            for row in yearly_table(bt.filter(pl.col("d") >= date(2006, 1, 1))).to_dicts():
                yr_rows.append({"symbol": sym, "strategy": name, **row})
    pl.DataFrame(yr_rows).write_parquet(OUT / "yearly.parquet")

    print(f"wrote {len(df)} result rows -> {OUT}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
