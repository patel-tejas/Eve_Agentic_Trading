"""C2026-09-REALDATA stage F: score the frozen finalists on the holdout, ONCE.

    python scripts/run_realdata_holdout.py --dry-run   # rehearsal on 2021-22 design data
    python scripts/run_realdata_holdout.py             # the one real opening

Pre-registration sections 0.2 and 7, as amended by A1. In a real run the
seal is marked opened *before* anything is computed, so a crash half-way
still counts as the one opening; a second invocation refuses to run.
``--dry-run`` exercises every line on a window inside the design period,
never touches the seal, and writes ``holdout_DRYRUN.json``.

The finalists' specifications are frozen; applying a frozen procedure
forward is part of it -- an ML finalist keeps its walk-forward refit
before each new calendar year on an expanding window, exactly as in the
design period.
"""

from __future__ import annotations

import json
import sys
from datetime import date, datetime
from pathlib import Path

import numpy as np
import polars as pl

sys.path.insert(0, str(Path(__file__).resolve().parent))

from run_realdata_phase2 import (  # noqa: E402
    FINALISTS,
    HOLDOUT,
    OOS_YEARS,
    OUT,
    PANEL_CACHE,
    SEAL,
    TRADING_DAYS,
    _exposure_from_cfg,
    backtest,
    block_ci,
    perf,
)

from quant.research.multiple_testing import deflated_sharpe_ratio  # noqa: E402
from quant.research.realdata_features import FEATURES, build_panel  # noqa: E402

DRY_RUN = "--dry-run" in sys.argv
WINDOW = (date(2021, 1, 1), date(2022, 12, 28)) if DRY_RUN else HOLDOUT
VERIFY_THROUGH = date(2022, 12, 28)


def sharpe(x: np.ndarray) -> float:
    sd = x.std(ddof=1)
    return float(x.mean() / sd * np.sqrt(TRADING_DAYS)) if sd > 0 else float("nan")


def sharpe_diff_ci(
    s: np.ndarray, b: np.ndarray, block: int = 20, n_boot: int = 5000, seed: int = 13
) -> tuple[float, float, float]:
    """Paired circular block bootstrap of Sharpe(strategy) - Sharpe(benchmark)."""
    rng = np.random.default_rng(seed)
    n = len(s)
    nb = int(np.ceil(n / block))
    starts = rng.integers(0, n, size=(n_boot, nb))
    idx = ((starts[:, :, None] + np.arange(block)) % n).reshape(n_boot, -1)[:, :n]
    ss, bb = s[idx], b[idx]
    d = (ss.mean(1) / ss.std(1, ddof=1) - bb.mean(1) / bb.std(1, ddof=1)) * np.sqrt(TRADING_DAYS)
    lo, hi = np.nanpercentile(d, [2.5, 97.5])
    return sharpe(s) - sharpe(b), float(lo), float(hi)


def yearly(bt: pl.DataFrame) -> list[dict]:
    return (
        bt.with_columns(y=pl.col("date").dt.year())
        .group_by("y")
        .agg(((1 + pl.col("net")).product() - 1).alias("ret"))
        .sort("y")
        .to_dicts()
    )


def main() -> int:
    seal = json.loads(SEAL.read_text(encoding="utf-8"))
    if seal.get("holdout_opened") and not DRY_RUN:
        print(f"REFUSED: holdout already opened at {seal.get('holdout_opened_at')}")
        return 2
    if not FINALISTS.exists():
        print("REFUSED: no frozen finalists; run the design stage first")
        return 2
    frozen = json.loads(FINALISTS.read_text(encoding="utf-8"))

    if not DRY_RUN:
        seal.update(
            holdout_opened=True,
            holdout_opened_at=datetime.now().isoformat(timespec="seconds"),
            finalists_frozen_at=frozen["frozen_at"],
        )
        SEAL.write_text(json.dumps(seal, indent=2), encoding="utf-8")

    # rebuild, then prove the design rows are unchanged: every feature is
    # trailing, so later data must not move a design row
    panel = build_panel(through=date(2023, 1, 31) if DRY_RUN else None)
    design_panel = pl.read_parquet(PANEL_CACHE)
    cols = ["date", "fut_ret", *FEATURES]
    old = design_panel.filter(pl.col("date") <= VERIFY_THROUGH).select(cols)
    new = panel.filter(pl.col("date") <= VERIFY_THROUGH).select(cols)
    assert old.height == new.height, (old.height, new.height)
    assert old["date"].to_list() == new["date"].to_list()
    for c in cols[1:]:
        a_, b_ = old[c].to_numpy().astype(float), new[c].to_numpy().astype(float)
        both = np.isfinite(a_) & np.isfinite(b_)
        assert (np.isfinite(a_) == np.isfinite(b_)).all() and np.allclose(a_[both], b_[both]), c
    print(
        f"design rows verified identical after rebuild ({old.height} rows, {len(cols) - 1} columns)"
    )

    years_all = tuple(sorted(set(OOS_YEARS) | set(range(WINDOW[0].year, WINDOW[1].year + 1))))
    parts = {f["name"]: f["cfg"] for f in frozen["finalists"]}

    def exposure(cfg: dict) -> np.ndarray:
        if "blend_of" in cfg:
            a, b = (exposure(parts[n]) for n in cfg["blend_of"])
            return 0.5 * a + 0.5 * b
        return _exposure_from_cfg(panel, cfg, years_all)

    def window(bt: pl.DataFrame) -> pl.DataFrame:
        return bt.filter((pl.col("date") >= WINDOW[0]) & (pl.col("date") <= WINDOW[1]))

    def design_oos(bt: pl.DataFrame) -> pl.DataFrame:
        return bt.filter(pl.col("date").dt.year().is_in(list(OOS_YEARS)))

    bench_full = backtest(panel, np.ones(panel.height))
    bench_h, bench_d = window(bench_full), design_oos(bench_full)
    bench_perf = perf(bench_h)
    bh = bench_h["net"].to_numpy()

    trials = pl.read_parquet(OUT / "phase2_design_trials.parquet").filter(
        pl.col("name") != "B0_buy_hold"  # A1.3
    )
    trial_sharpes_daily = [
        s / np.sqrt(TRADING_DAYS)
        for s in trials["sharpe"].to_list()
        if s is not None and np.isfinite(s)
    ]
    n_total = frozen["n_trials_total"]

    results = []
    for fin in frozen["finalists"]:
        e = exposure(fin["cfg"])
        full = backtest(panel, e)
        h, d = window(full), design_oos(full)
        hn = h["net"].to_numpy()
        pooled = np.concatenate([d["net"].to_numpy(), hn])
        pooled_b = np.concatenate([bench_d["net"].to_numpy(), bh])
        ph = perf(h)
        hz = block_ci(hn)
        hb = block_ci(hn - bh)
        pz = block_ci(pooled)
        pb = block_ci(pooled - pooled_b)
        sd_point, sd_lo, sd_hi = sharpe_diff_ci(hn, bh)
        dsr = deflated_sharpe_ratio(
            list(pooled), n_trials=n_total, trial_sharpes=trial_sharpes_daily
        )
        beats_bh = ph["sharpe"] > bench_perf["sharpe"]
        # A1.1: CREDIBLE needs BOTH pooled CIs to exclude zero
        if ph["total"] > 0 and beats_bh and pz[2] and pb[2] and dsr.deflated_sharpe >= 0.95:
            tier = "CREDIBLE"
        elif ph["total"] > 0 and beats_bh:
            tier = "PROMISING"
        else:
            tier = "FAIL"
        held = h["held"].to_numpy()
        results.append(
            {
                "name": fin["name"],
                "family": fin["family"],
                "cfg": fin["cfg"],
                "tier": tier,
                "holdout": ph,
                "holdout_by_year": yearly(h),
                "holdout_mean_net_exposure": float(held.mean()),
                "holdout_ci_vs_zero_bps": hz[:2],
                "holdout_ci_vs_zero_excl": hz[2],
                "holdout_ci_vs_bh_bps": hb[:2],
                "holdout_ci_vs_bh_excl": hb[2],
                "holdout_sharpe_minus_bh": sd_point,
                "holdout_sharpe_diff_ci": [sd_lo, sd_hi],
                "holdout_friction_x1.5": perf(window(backtest(panel, e, friction_mult=1.5))),
                "pooled_oos_days": len(pooled),
                "pooled_ci_vs_zero_bps": pz[:2],
                "pooled_ci_vs_zero_excl": pz[2],
                "pooled_ci_vs_bh_bps": pb[:2],
                "pooled_ci_vs_bh_excl": pb[2],
                "dsr_at_final_n": dsr.deflated_sharpe,
                "n_trials": n_total,
                "beats_bh_sharpe": beats_bh,
            }
        )

    out = {
        "dry_run": DRY_RUN,
        "opened_at": None if DRY_RUN else seal["holdout_opened_at"],
        "window": [str(x) for x in WINDOW],
        "benchmark": bench_perf,
        "benchmark_by_year": yearly(bench_h),
        "results": results,
    }
    name = "holdout_DRYRUN.json" if DRY_RUN else "holdout.json"
    (OUT / name).write_text(json.dumps(out, indent=2, default=str), encoding="utf-8")
    print(
        f"{'DRY RUN -- ' if DRY_RUN else ''}window {WINDOW[0]}..{WINDOW[1]}  "
        f"benchmark Sharpe {bench_perf['sharpe']:.2f}  total {bench_perf['total'] * 100:+.1f}%"
    )
    for r in results:
        hh = r["holdout"]
        print(
            f"  {r['name']:<32} {r['tier']:<9} Sharpe {hh['sharpe']:5.2f}  "
            f"total {hh['total'] * 100:+6.1f}%  "
            f"maxDD {hh['max_dd'] * 100:6.1f}%  net expo {r['holdout_mean_net_exposure']:+.2f}  "
            f"dSR {r['holdout_sharpe_minus_bh']:+.2f} [{r['holdout_sharpe_diff_ci'][0]:+.2f},"
            f"{r['holdout_sharpe_diff_ci'][1]:+.2f}]  DSR {r['dsr_at_final_n']:.3f}"
        )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
