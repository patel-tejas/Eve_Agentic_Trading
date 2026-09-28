"""Forward paper-trading log for the frozen C2026-09-REALDATA finalists.

    python scripts/forward_paper_log.py          # once per trading day, after ~19:00 IST
    python scripts/forward_paper_log.py --no-refresh   # skip the downloads

This is the one holdout that can keep growing (pre-registration §0.3).
The finalists in ``finalists.json`` are frozen and never re-tuned here.

The log is APPEND-ONLY:
- a logged decision (finalist, decided, exposure) is never rewritten;
- every run re-derives all earlier decisions and ABORTS if any differs
  (a data revision or a code change must not silently rewrite history);
- a realised return is filled in once its session has closed, and is
  likewise verified on every later run;
- every row carries the hash of the code and of the finalists that produced it.

Columns: ``decided`` -- the date whose after-close data produced the signal;
``exposure`` -- entered at the settlement close of the next session;
``earns_on`` / ``net_ret`` -- the session that exposure earns and its return
net of dated costs (null until that session has closed).

Any later iteration of the models must start its OWN log with its own
start date; it may not be scored on this one.
"""

from __future__ import annotations

import hashlib
import json
import subprocess
import sys
from datetime import date, datetime, timedelta
from pathlib import Path

import numpy as np
import polars as pl

sys.path.insert(0, str(Path(__file__).resolve().parent))

from run_realdata_phase2 import (  # noqa: E402
    FINALISTS,
    OOS_YEARS,
    OUT,
    _exposure_from_cfg,
    backtest,
)

from quant.research.realdata_features import build_panel  # noqa: E402

FORWARD_START = date(2026, 9, 28)
LOG = OUT / "forward_log.parquet"
PY = sys.executable
TOL = 1e-9
CODE_FILES = [
    "quant/research/realdata_features.py",
    "quant/data/nse_archive.py",
    "quant/backtest/india_costs.py",
    "scripts/run_realdata_phase2.py",
]
SCHEMA = {
    "finalist": pl.Utf8,
    "decided": pl.Date,
    "exposure": pl.Float64,
    "earns_on": pl.Date,
    "net_ret": pl.Float64,
    "logged_at": pl.Utf8,
    "code_sha": pl.Utf8,
    "finalists_sha": pl.Utf8,
}


def _sha(paths: list[str]) -> str:
    h = hashlib.sha256()
    for p in paths:
        h.update(Path(p).read_bytes())
    return h.hexdigest()[:16]


def refresh_data(today: date) -> None:
    lo = (today - timedelta(days=14)).isoformat()
    for kind in ("bhav", "participant"):
        subprocess.run(
            [
                PY,
                "scripts/download_nse_fo.py",
                "--kind",
                kind,
                "--start",
                lo,
                "--end",
                today.isoformat(),
            ],
            check=True,
        )
    subprocess.run([PY, "scripts/download_index_daily.py", "--recent"], check=True)


def current_decisions(frozen: dict, today: date) -> pl.DataFrame:
    panel = build_panel()
    years = tuple(sorted(set(OOS_YEARS) | set(range(2023, today.year + 1))))
    parts = {f["name"]: f["cfg"] for f in frozen["finalists"]}

    def exposure(cfg: dict) -> np.ndarray:
        if "blend_of" in cfg:
            a, b = (exposure(parts[n]) for n in cfg["blend_of"])
            return 0.5 * a + 0.5 * b
        return _exposure_from_cfg(panel, cfg, years)

    dates = panel["date"].to_list()
    rows = []
    for fin in frozen["finalists"]:
        e = exposure(fin["cfg"])
        net = backtest(panel, e)["net"].to_numpy()
        for i, d in enumerate(dates):
            if d < FORWARD_START:
                continue
            k = i + 2  # decided at close d, entered at close d+1, earns d+2
            rows.append(
                {
                    "finalist": fin["name"],
                    "decided": d,
                    "exposure": float(e[i]),
                    "earns_on": dates[k] if k < len(dates) else None,
                    "net_ret": float(net[k]) if k < len(dates) else None,
                }
            )
    return pl.DataFrame(
        rows,
        schema={k: SCHEMA[k] for k in ("finalist", "decided", "exposure", "earns_on", "net_ret")},
    )


def main() -> int:
    today = date.today()
    if "--no-refresh" not in sys.argv:
        refresh_data(today)
    frozen = json.loads(FINALISTS.read_text(encoding="utf-8"))
    code_sha, fin_sha = _sha(CODE_FILES), _sha([str(FINALISTS)])
    fresh = current_decisions(frozen, today)
    log = pl.read_parquet(LOG) if LOG.exists() else pl.DataFrame(schema=SCHEMA)

    # 1. every logged decision must re-derive identically
    key = ["finalist", "decided"]
    chk = log.join(fresh, on=key, how="left", suffix="_now")
    missing = chk.filter(pl.col("exposure_now").is_null())
    if missing.height:
        raise SystemExit(
            f"ABORT: {missing.height} logged decisions no longer derivable; "
            f"first: {missing.row(0, named=True)}"
        )
    drift = chk.filter((pl.col("exposure") - pl.col("exposure_now")).abs() > TOL)
    if drift.height:
        raise SystemExit(
            f"ABORT: {drift.height} logged exposures changed; first: {drift.row(0, named=True)}"
        )
    realised = chk.filter(pl.col("net_ret").is_not_null())
    bad = realised.filter((pl.col("net_ret") - pl.col("net_ret_now")).abs() > TOL)
    if bad.height:
        raise SystemExit(
            f"ABORT: {bad.height} realised returns changed; first: {bad.row(0, named=True)}"
        )

    # 2. fill realised returns that became available since the last run
    now = datetime.now().isoformat(timespec="seconds")
    fill = chk.filter(pl.col("net_ret").is_null() & pl.col("net_ret_now").is_not_null()).select(
        *key, pl.col("earns_on_now").alias("earns_on_f"), pl.col("net_ret_now").alias("net_ret_f")
    )
    log = (
        log.join(fill, on=key, how="left")
        .with_columns(
            earns_on=pl.coalesce("earns_on", "earns_on_f"),
            net_ret=pl.coalesce("net_ret", "net_ret_f"),
        )
        .drop("earns_on_f", "net_ret_f")
    )

    # 3. append decisions never logged before
    new = fresh.join(log.select(key), on=key, how="anti").with_columns(
        logged_at=pl.lit(now), code_sha=pl.lit(code_sha), finalists_sha=pl.lit(fin_sha)
    )
    log = pl.concat([log, new.select(list(SCHEMA))], how="vertical_relaxed").sort(
        "finalist", "decided"
    )
    OUT.mkdir(parents=True, exist_ok=True)
    log.write_parquet(LOG)
    log.write_csv(LOG.with_suffix(".csv"))

    print(f"forward log since {FORWARD_START}: +{new.height} decisions, +{fill.height} realised")
    for name, g in log.group_by("finalist", maintain_order=True):
        done = g.drop_nulls("net_ret")
        cum = float((1 + done["net_ret"]).product() - 1) if done.height else 0.0
        last = g.sort("decided").tail(1).row(0, named=True)
        label = name[0] if isinstance(name, tuple) else name
        print(
            f"  {label}: {done.height} realised sessions, cumulative net {cum * 100:+.2f}%, "
            f"latest decision {last['decided']} -> exposure {last['exposure']:+.2f}"
        )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
