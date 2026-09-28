"""C2026-09-REALDATA Phase 2 (pre-registration section 6).

    python scripts/run_realdata_phase2.py design    # stages A-E, data <= 2022-12-31 only
    python scripts/run_realdata_phase2.py holdout   # stage F, once, finalists only

``design`` never reads a return dated after 2022-12-31: design rows are
also dropped when their target (close t+1 -> close t+2) lands in 2023.
``holdout`` refuses to run without a frozen finalists file, and refuses a
second time once the seal records the holdout as opened.
"""

from __future__ import annotations

import itertools
import json
import sys
from datetime import date, datetime
from pathlib import Path

import numpy as np
import polars as pl

from quant.backtest.india_costs import leg_bps
from quant.research.multiple_testing import deflated_sharpe_ratio
from quant.research.realdata_features import FEATURES, build_panel

OUT = Path("data/results/leaderboard/C2026-09-REALDATA")
SEAL = OUT / "prereg_seal.json"
FINALISTS = OUT / "finalists.json"
PANEL_CACHE = Path("data/processed/realdata/panel_design.parquet")  # built through DESIGN_END
DESIGN_END = date(2022, 12, 31)
OOS_YEARS = (2019, 2020, 2021, 2022)
FIT_START = date(2017, 1, 1)
HOLDOUT = (date(2023, 1, 2), date(2026, 9, 25))
TRADING_DAYS = 252
N_PHASE1 = 3
DEFAULT_Z = {"turn_z": 60}  # every other *_z feature defaults to 252
Z_BASE = {
    "fii_lr_z": "fii_lr",
    "cli_lr_z": "cli_lr",
    "pro_lr_z": "pro_lr",
    "fii_opt_z": "fii_opt",
    "pcr_z": "pcr",
    "vix_z": "indiavix_close",
    "basis_z": "basis_ann",
    "turn_z": "fut_turnover",
}


def default_z(feat: str) -> int:
    return DEFAULT_Z.get(feat, 252)


# ------------------------------------------------------------- backtest


def backtest(panel: pl.DataFrame, e: np.ndarray, *, friction_mult: float = 1.0) -> pl.DataFrame:
    """Daily net returns of exposure ``e`` on the continuous futures.

    ``e[t]`` is decided from day-t data (published after close t), entered
    at the settlement close of t+1, and so is HELD over return day t+2:
    ``held[tau] = e[tau-2]``. Trades at close tau move ``held[tau]`` to
    ``held[tau+1]``; on a roll close the whole old position is closed and
    the new one opened in the next contract (long AND short positions pay).
    """
    dates = panel["date"].to_list()
    ret = np.nan_to_num(panel["fut_ret"].to_numpy())
    roll = panel["roll_at_close"].to_numpy()
    price = panel["settle"].to_numpy()
    e = np.nan_to_num(np.asarray(e, dtype=float))
    held = np.concatenate([[0.0, 0.0], e[:-2]])
    nxt = np.concatenate([held[1:], [held[-1]]])
    cost = np.zeros(len(e))
    for i, d in enumerate(dates):
        cur, new = held[i], nxt[i]
        if roll[i]:
            legs = [
                ("sell" if cur > 0 else "buy", abs(cur)),
                ("buy" if new > 0 else "sell", abs(new)),
            ]
        else:
            delta = new - cur
            legs = [("buy" if delta > 0 else "sell", abs(delta))]
        for side, q in legs:
            if q > 1e-12:
                cost[i] += q * leg_bps(side, d, price=float(price[i])) / 1e4
    cost *= friction_mult
    return pl.DataFrame(
        {"date": dates, "held": held, "gross": held * ret, "cost": cost, "net": held * ret - cost}
    )


def perf(bt: pl.DataFrame) -> dict:
    net = bt["net"].to_numpy()
    if len(net) < 20:
        return {}
    sd = net.std(ddof=1)
    eq = np.cumprod(1 + net)
    years = len(net) / TRADING_DAYS
    return {
        "days": len(net),
        "sharpe": float(net.mean() / sd * np.sqrt(TRADING_DAYS)) if sd > 0 else float("nan"),
        "cagr": float(eq[-1] ** (1 / years) - 1) if eq[-1] > 0 else float("nan"),
        "max_dd": float((eq / np.maximum.accumulate(eq) - 1).min()),
        "total": float(eq[-1] - 1),
        "turnover_per_yr": float(np.abs(np.diff(bt["held"].to_numpy(), prepend=0)).sum() / years),
        "cost_per_yr": float(bt["cost"].sum() / years),
        "avg_abs_exposure": float(np.abs(bt["held"].to_numpy()).mean()),
    }


def in_years(bt: pl.DataFrame, years) -> pl.DataFrame:
    return bt.filter(pl.col("date").dt.year().is_in(list(years)))


def block_ci(
    x: np.ndarray, block: int = 20, n_boot: int = 5000, seed: int = 11
) -> tuple[float, float, bool]:
    rng = np.random.default_rng(seed)
    n = len(x)
    nb = int(np.ceil(n / block))
    starts = rng.integers(0, n, size=(n_boot, nb))
    idx = ((starts[:, :, None] + np.arange(block)) % n).reshape(n_boot, -1)[:, :n]
    means = x[idx].mean(axis=1)
    lo, hi = np.percentile(means, [2.5, 97.5])
    return float(lo * 1e4), float(hi * 1e4), bool(lo > 0)


# ---------------------------------------------------------- exposures


def rule_exposure(
    panel: pl.DataFrame,
    feat: str,
    *,
    mode: str,
    z_window: int | None = None,
    threshold: float = 0.0,
    holding: int = 1,
) -> np.ndarray:
    """Pre-registered rule: act on the sign of (expected sign) x feature.

    ``z_window=None`` means the feature's pre-registered default.
    """
    s = FEATURES[feat] or 1
    col = feat
    if z_window is None:
        z_window = default_z(feat)
    if feat.endswith("_z") and z_window != default_z(feat):
        c = pl.col(Z_BASE[feat])
        panel = panel.with_columns(
            ((c - c.rolling_mean(z_window)) / c.rolling_std(z_window)).alias("_zf")
        )
        col = "_zf"
    x = s * panel[col].to_numpy().astype(float)
    x = np.where(np.isfinite(x), x, 0.0)
    if mode == "LS":
        sig = np.where(x > threshold, 1.0, np.where(x < -threshold, -1.0, 0.0))
    else:
        sig = np.where(x > threshold, 1.0, 0.0)
    if holding > 1:
        sig = pl.Series(sig).rolling_mean(holding, min_samples=1).to_numpy()
    return sig


def ml_exposure(
    panel: pl.DataFrame,
    *,
    model: str,
    mode: str,
    holding: int = 1,
    C: float = 1.0,
    depth: int = 3,
    lr: float = 0.05,
    oos_years=OOS_YEARS,
    fit_end: date | None = None,
) -> np.ndarray:
    """Walk-forward: refit before each OOS year on an expanding window from
    2017, dropping the last 2 training rows (their target overlaps the OOS
    year). Scaler/model fitted on the training window only."""
    from sklearn.ensemble import HistGradientBoostingClassifier
    from sklearn.linear_model import LogisticRegression
    from sklearn.pipeline import make_pipeline
    from sklearn.preprocessing import StandardScaler

    feats = list(FEATURES)
    X = panel.select(feats).to_numpy().astype(float)
    y = panel["target"].to_numpy().astype(float)
    dts = panel["date"].to_list()
    years = np.array([d.year for d in dts])
    ok = np.isfinite(X).all(axis=1)
    sig = np.zeros(len(panel))
    for yr in oos_years:
        start = date(yr, 1, 1)
        tr = np.array([FIT_START <= d < start for d in dts]) & ok & np.isfinite(y)
        tr_idx = np.flatnonzero(tr)[:-2]
        if fit_end is not None:
            tr_idx = tr_idx[[dts[i] <= fit_end for i in tr_idx]]
        if len(tr_idx) < 200:
            continue
        if model == "logit":
            m = make_pipeline(StandardScaler(), LogisticRegression(C=C, max_iter=2000))
        else:
            m = HistGradientBoostingClassifier(
                max_depth=depth, learning_rate=lr, max_iter=200, random_state=0
            )
        m.fit(X[tr_idx], (y[tr_idx] > 0).astype(int))
        te = np.flatnonzero((years == yr) & ok)
        if len(te) == 0:
            continue
        p = m.predict_proba(X[te])[:, 1]
        sig[te] = np.where(p > 0.5, 1.0, -1.0) if mode == "LS" else np.where(p > 0.5, 1.0, 0.0)
    if holding > 1:
        sig = pl.Series(sig).rolling_mean(holding, min_samples=1).to_numpy()
    return sig


# --------------------------------------------------------------- stages


def newey_west_mean(u: np.ndarray, lag: int = 5) -> tuple[float, float]:
    u = u - u.mean()
    n = len(u)
    s = (u @ u) / n
    for k in range(1, lag + 1):
        w = 1 - k / (lag + 1)
        s += 2 * w * (u[k:] @ u[:-k]) / n
    return float(np.sqrt(s / n)), n


def stage_a(design: pl.DataFrame) -> list[dict]:
    from scipy.stats import norm, rankdata

    rows = []
    for f, sign in FEATURES.items():
        d = (
            design.select(f, "target")
            .drop_nulls()
            .filter(pl.col(f).is_finite() & pl.col("target").is_finite())
        )
        a = rankdata(d[f].to_numpy())
        b = rankdata(d["target"].to_numpy())
        za, zb = (a - a.mean()) / a.std(), (b - b.mean()) / b.std()
        u = za * zb
        ic = float(u.mean())
        se, n = newey_west_mean(za * zb)
        t = ic / se if se > 0 else float("nan")
        p = float(2 * (1 - norm.cdf(abs(t))))
        rows.append({"feature": f, "expected_sign": sign, "ic": ic, "t_nw": t, "p": p, "n": n})
    ps = np.array([r["p"] for r in rows])
    order = np.argsort(ps)
    m = len(ps)
    passed = np.zeros(m, dtype=bool)
    k_max = 0
    for rank, i in enumerate(order, 1):
        if ps[i] <= 0.10 * rank / m:
            k_max = rank
    for rank, i in enumerate(order, 1):
        passed[i] = rank <= k_max
    for r, ok in zip(rows, passed):
        r["bh_q10_pass"] = bool(ok)
        r["sign_as_expected"] = r["expected_sign"] == 0 or np.sign(r["ic"]) == r["expected_sign"]
    return rows


def design_run() -> int:
    seal = json.loads(SEAL.read_text())
    if seal.get("holdout_opened"):
        print("holdout already opened; design stage is frozen")
        return 2
    panel = build_panel(through=DESIGN_END)
    PANEL_CACHE.parent.mkdir(parents=True, exist_ok=True)
    panel.write_parquet(PANEL_CACHE)
    dts = panel["date"].to_list()
    # design rows: dated <= 2022-12-31 AND whose t+2 target is still in 2022
    t2 = dts[2:] + [None, None]
    keep = [d <= DESIGN_END and t is not None and t <= DESIGN_END for d, t in zip(dts, t2)]
    design = panel.filter(pl.Series(keep))
    assert design["date"].max() <= DESIGN_END
    print(
        f"panel {panel.height} rows {panel['date'].min()}..{panel['date'].max()}; "
        f"design {design.height} rows ..{design['date'].max()}"
    )

    trials: list[dict] = []

    def score(name: str, family: str, e: np.ndarray, cfg: dict) -> dict:
        bt = in_years(backtest(design, e), OOS_YEARS)
        rec = {
            "name": name,
            "family": family,
            "cfg": cfg,
            **perf(bt),
            "net_daily": bt["net"].to_numpy(),
        }
        trials.append(rec)
        return rec

    bench = score("B0_buy_hold", "benchmark", np.ones(design.height), {})

    # Stage A -- information test (diagnostic, counted in N)
    a_rows = stage_a(design)

    # Stage B -- rules at pre-registered defaults
    for f in FEATURES:
        for mode in ("LS", "LF"):
            score(
                f"B_{f}_{mode}",
                "rule",
                rule_exposure(design, f, mode=mode),
                {"feature": f, "mode": mode},
            )
    # Stage C -- ML at pre-registered defaults
    for model in ("logit", "gbm"):
        for mode in ("LS", "LF"):
            score(
                f"C_{model}_{mode}",
                "ml",
                ml_exposure(design, model=model, mode=mode),
                {"model": model, "mode": mode},
            )
    # Stage D -- fine-tuning grid, every setting counted
    for f in FEATURES:
        zs = (default_z(f), 126) if f.endswith("_z") else (default_z(f),)
        ths = (0.0, 0.5) if f.endswith("_z") else (0.0,)
        for z, th, hold, mode in itertools.product(zs, ths, (1, 5), ("LS", "LF")):
            if (z, th, hold) == (default_z(f), 0.0, 1):
                continue  # identical to stage B
            score(
                f"D_{f}_z{z}_t{th}_h{hold}_{mode}",
                "rule",
                rule_exposure(design, f, mode=mode, z_window=z, threshold=th, holding=hold),
                {"feature": f, "mode": mode, "z_window": z, "threshold": th, "holding": hold},
            )
    for hold, mode in itertools.product((1, 5), ("LS", "LF")):
        for C in (0.1, 1.0, 10.0):
            if (C, hold) == (1.0, 1):
                continue
            score(
                f"D_logit_C{C}_h{hold}_{mode}",
                "ml",
                ml_exposure(design, model="logit", mode=mode, C=C, holding=hold),
                {"model": "logit", "mode": mode, "C": C, "holding": hold},
            )
        for depth, lr in itertools.product((2, 3), (0.03, 0.1)):
            score(
                f"D_gbm_d{depth}_lr{lr}_h{hold}_{mode}",
                "ml",
                ml_exposure(design, model="gbm", mode=mode, depth=depth, lr=lr, holding=hold),
                {"model": "gbm", "mode": mode, "depth": depth, "lr": lr, "holding": hold},
            )

    cands = [
        t for t in trials if t["family"] != "benchmark" and np.isfinite(t.get("sharpe", np.nan))
    ]
    n_total = N_PHASE1 + len(FEATURES) + len(cands)

    # Stage E -- finalists: best rule, best ML, and their 50/50 blend
    best_rule = max((t for t in cands if t["family"] == "rule"), key=lambda t: t["sharpe"])
    best_ml = max((t for t in cands if t["family"] == "ml"), key=lambda t: t["sharpe"])
    finalists = [best_rule, best_ml]
    blend_cfg = {"blend_of": [best_rule["name"], best_ml["name"]]}
    e_rule = _exposure_from_cfg(design, best_rule["cfg"], OOS_YEARS)
    e_ml = _exposure_from_cfg(design, best_ml["cfg"], OOS_YEARS)
    blend = score("E_blend_rule_ml", "blend", 0.5 * e_rule + 0.5 * e_ml, blend_cfg)
    finalists.append(blend)
    n_total += 1

    trial_sharpes_daily = [
        np.mean(t["net_daily"]) / np.std(t["net_daily"], ddof=1)
        for t in cands + [blend]
        if np.std(t["net_daily"], ddof=1) > 0
    ]
    summary = []
    for t in finalists:
        dsr = deflated_sharpe_ratio(
            list(t["net_daily"]), n_trials=n_total, trial_sharpes=trial_sharpes_daily
        )
        z_lo, z_hi, z_ex = block_ci(t["net_daily"])
        b_lo, b_hi, b_ex = block_ci(t["net_daily"] - bench["net_daily"])
        summary.append(
            {k: v for k, v in t.items() if k != "net_daily"}
            | {
                "design_dsr": dsr.deflated_sharpe,
                "design_ci_vs_zero_bps": [z_lo, z_hi],
                "design_ci_vs_zero_excl": z_ex,
                "design_ci_vs_bh_bps": [b_lo, b_hi],
                "design_ci_vs_bh_excl": b_ex,
            }
        )

    out = {
        "generated_at": datetime.now().isoformat(timespec="seconds"),
        "prereg_sha256_prefix": seal["prereg_sha256"][:16],
        "design_oos_years": list(OOS_YEARS),
        "benchmark": {k: v for k, v in bench.items() if k != "net_daily"},
        "stage_a": a_rows,
        "n_trials_total": n_total,
        "finalists": summary,
        "top20_by_design_sharpe": [
            {k: v for k, v in t.items() if k != "net_daily"}
            for t in sorted(cands, key=lambda t: -t["sharpe"])[:20]
        ],
    }
    OUT.mkdir(parents=True, exist_ok=True)
    (OUT / "phase2_design.json").write_text(
        json.dumps(out, indent=2, default=str), encoding="utf-8"
    )
    FINALISTS.write_text(
        json.dumps(
            {
                "frozen_at": out["generated_at"],
                "n_trials_total": n_total,
                "finalists": [
                    {"name": t["name"], "family": t["family"], "cfg": t["cfg"]} for t in finalists
                ],
            },
            indent=2,
        ),
        encoding="utf-8",
    )
    pl.DataFrame(
        [
            {k: v for k, v in t.items() if k not in ("net_daily", "cfg")}
            | {"cfg": json.dumps(t["cfg"])}
            for t in trials
        ]
    ).write_parquet(OUT / "phase2_design_trials.parquet")
    print(
        json.dumps(
            {k: out[k] for k in ("benchmark", "n_trials_total", "finalists")}, indent=1, default=str
        )
    )
    return 0


def _exposure_from_cfg(panel: pl.DataFrame, cfg: dict, oos_years: tuple[int, ...]) -> np.ndarray:
    if "blend_of" in cfg:
        raise ValueError("blend exposures are built from their parts")
    if "feature" in cfg:
        return rule_exposure(
            panel,
            cfg["feature"],
            mode=cfg["mode"],
            z_window=cfg.get("z_window"),
            threshold=cfg.get("threshold", 0.0),
            holding=cfg.get("holding", 1),
        )
    return ml_exposure(
        panel,
        model=cfg["model"],
        mode=cfg["mode"],
        holding=cfg.get("holding", 1),
        C=cfg.get("C", 1.0),
        depth=cfg.get("depth", 3),
        lr=cfg.get("lr", 0.05),
        oos_years=oos_years,
    )


if __name__ == "__main__":
    cmd = sys.argv[1] if len(sys.argv) > 1 else "design"
    if cmd == "design":
        raise SystemExit(design_run())
    print("holdout stage lives in scripts/run_realdata_holdout.py")
    raise SystemExit(1)
