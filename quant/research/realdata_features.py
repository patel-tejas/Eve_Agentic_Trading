"""C2026-09-REALDATA Phase 2: daily panel from NSE bhavcopy, participant OI,
India VIX and NIFTY spot.

Everything here implements pre-registration sections 2-4 and 6.1:

- continuous near-month futures, rolled at the settlement close of the 3rd
  trading session before expiry, expiry read from the data;
- returns within one contract (settle to settle), so the real basis is in
  the returns and no carry is modelled;
- OI and turnover as NOTIONAL summed across all expiries (units x settle,
  turnover in rupees), never raw contract counts;
- participant positioning as ratios only;
- every z-score trailing (causal at each row);
- the target for a day-t row is the return of close t+1 -> close t+2,
  because day-t NSE files are published after the close and the fill is
  at the next settlement close.
"""

from __future__ import annotations

import glob
from datetime import date
from pathlib import Path

import numpy as np
import polars as pl

from quant.data.nse_archive import normalise, parse_participant_oi

BHAV_DIR = Path("data/raw/nse/fo_bhav")
PART_DIR = Path("data/raw/nse/participant_oi")
DAILY_DIR = Path("data/processed/index_daily")
ROLL_SESSIONS_BEFORE_EXPIRY = 3


# ------------------------------------------------------------------ load


def load_bhav(through: date | None = None) -> pl.DataFrame:
    frames = []
    for f in sorted(glob.glob(str(BHAV_DIR / "*" / "*_raw.parquet"))):
        d = date.fromisoformat(f"{Path(f).name[:4]}-{Path(f).name[4:6]}-{Path(f).name[6:8]}")
        if through is not None and d > through:
            continue  # also avoids reading a file a live download is still writing
        raw = pl.read_parquet(f)
        if raw.height == 0:
            continue
        frames.append(normalise(raw, d))
    return pl.concat(frames, how="vertical_relaxed").sort("date", "instrument", "expiry")


def load_participants(through: date | None = None) -> pl.DataFrame:
    frames = []
    for f in sorted(glob.glob(str(PART_DIR / "*" / "*.csv"))):
        n = Path(f).stem
        d = date(int(n[:4]), int(n[4:6]), int(n[6:8]))
        if through is not None and d > through:
            continue
        p = parse_participant_oi(Path(f).read_text(encoding="utf-8", errors="replace"), d)
        if p.height:
            frames.append(p)
    return pl.concat(frames, how="vertical_relaxed").sort("date", "participant")


def load_daily_close(symbol: str) -> pl.DataFrame:
    return pl.read_parquet(DAILY_DIR / symbol / "daily.parquet").select(
        pl.col("d").alias("date"), pl.col("close").alias(f"{symbol.lower()}_close")
    )


# ---------------------------------------------------- continuous futures


def continuous_futures(bhav: pl.DataFrame) -> pl.DataFrame:
    """Near-month series with the pre-registered roll rule.

    ``held`` for return day t is the contract held over (close t-1, close t],
    chosen at close t-1: roll to the next expiry once the near contract has
    ``ROLL_SESSIONS_BEFORE_EXPIRY`` or fewer sessions left after that close.
    """
    fut = bhav.filter(pl.col("instrument") == "FUT").select(
        "date", "expiry", "settle", "oi", "value_rs"
    )
    sessions = fut["date"].unique().sort().to_list()
    idx = {d: i for i, d in enumerate(sessions)}
    by_date = {d: g for d, g in fut.group_by("date")}
    by_date = {k[0] if isinstance(k, tuple) else k: v for k, v in by_date.items()}

    def sessions_left_after(d: date, expiry: date) -> int:
        # trading sessions in (d, expiry]; expiry is itself a session
        j = idx.get(expiry)
        if (
            j is None
        ):  # expiry fell on a non-session (holiday shift) -- count to the last session <= expiry
            j = max(i for s, i in idx.items() if s <= expiry)
        return j - idx[d]

    rows = []
    prev_held: date | None = None
    for k in range(1, len(sessions)):
        t_prev, t = sessions[k - 1], sessions[k]
        live = by_date[t_prev].filter(pl.col("expiry") >= t).sort("expiry")
        expiries = live["expiry"].to_list()
        if not expiries:
            continue
        near = expiries[0]
        held = (
            expiries[1]
            if sessions_left_after(t_prev, near) <= ROLL_SESSIONS_BEFORE_EXPIRY
            and len(expiries) > 1
            else near
        )
        p0 = by_date[t_prev].filter(pl.col("expiry") == held)["settle"]
        p1 = by_date[t].filter(pl.col("expiry") == held)["settle"]
        if p0.len() == 0 or p1.len() == 0:
            continue
        rows.append(
            {
                "date": t,
                "held_expiry": held,
                "settle_prev": float(p0[0]),
                "settle": float(p1[0]),
                "fut_ret": float(p1[0]) / float(p0[0]) - 1.0,
                # a roll trade happens at close t_prev when the held contract changed
                "rolled_into": prev_held is not None and held != prev_held,
                "days_to_expiry": (held - t).days,
            }
        )
        prev_held = held
    out = pl.DataFrame(rows).sort("date")
    # roll flag on the TRADE day: the close at which the switch is executed
    return out.with_columns(roll_at_close=pl.col("rolled_into").shift(-1).fill_null(False))


# --------------------------------------------------------------- features


def _z(col: str, window: int) -> pl.Expr:
    c = pl.col(col)
    return (c - c.rolling_mean(window)) / c.rolling_std(window)


def build_panel(through: date | None = None) -> pl.DataFrame:
    bhav = load_bhav(through)
    cont = continuous_futures(bhav)

    fut = bhav.filter(pl.col("instrument") == "FUT")
    fut_agg = fut.group_by("date").agg(
        (pl.col("oi") * pl.col("settle")).sum().alias("oi_notional"),
        pl.col("value_rs").sum().alias("fut_turnover"),
    )
    opt = bhav.filter(pl.col("instrument") == "OPT")
    opt_agg = opt.group_by("date").agg(
        pl.col("oi").filter(pl.col("opt_type") == "PE").sum().alias("put_oi"),
        pl.col("oi").filter(pl.col("opt_type") == "CE").sum().alias("call_oi"),
    )

    part = load_participants(through)
    wide = part.filter(pl.col("participant").is_in(["FII", "CLIENT", "PRO"])).with_columns(
        lr=pl.col("fut_idx_long") / (pl.col("fut_idx_long") + pl.col("fut_idx_short")),
        opt_net=(
            pl.col("opt_idx_call_long")
            - pl.col("opt_idx_call_short")
            - pl.col("opt_idx_put_long")
            + pl.col("opt_idx_put_short")
        )
        / (
            pl.col("opt_idx_call_long")
            + pl.col("opt_idx_call_short")
            + pl.col("opt_idx_put_long")
            + pl.col("opt_idx_put_short")
        ),
    )
    part_w = (
        wide.filter(pl.col("participant") == "FII")
        .select("date", pl.col("lr").alias("fii_lr"), pl.col("opt_net").alias("fii_opt"))
        .join(
            wide.filter(pl.col("participant") == "CLIENT").select(
                "date", pl.col("lr").alias("cli_lr")
            ),
            on="date",
            how="left",
        )
        .join(
            wide.filter(pl.col("participant") == "PRO").select(
                "date", pl.col("lr").alias("pro_lr")
            ),
            on="date",
            how="left",
        )
    )

    spot = load_daily_close("NIFTY")
    vix = load_daily_close("INDIAVIX")

    p = (
        cont.join(fut_agg, on="date", how="left")
        .join(opt_agg, on="date", how="left")
        .join(part_w, on="date", how="left")
        .join(spot, on="date", how="left")
        .join(vix, on="date", how="left")
        .sort("date")
    )
    p = p.with_columns(
        pcr=pl.col("put_oi") / pl.col("call_oi"),
        basis_ann=(pl.col("settle") / pl.col("nifty_close") - 1.0)
        * 365.0
        / pl.col("days_to_expiry").clip(lower_bound=1),
        oi_chg=pl.col("oi_notional") / pl.col("oi_notional").shift(1) - 1.0,
    )
    p = p.with_columns(
        fii_lr_z=_z("fii_lr", 252),
        fii_lr_d5=pl.col("fii_lr") - pl.col("fii_lr").shift(5),
        cli_lr_z=_z("cli_lr", 252),
        pro_lr_z=_z("pro_lr", 252),
        fii_opt_z=_z("fii_opt", 252),
        pcr_z=_z("pcr", 252),
        vix_z=_z("indiavix_close", 252),
        vix_d5=(pl.col("indiavix_close") / pl.col("indiavix_close").shift(5)).log(),
        buildup=(pl.col("fut_ret").sign() * (pl.col("oi_chg") > 0).cast(pl.Float64)),
        oi_d5=pl.col("oi_notional") / pl.col("oi_notional").shift(5) - 1.0,
        basis_z=_z("basis_ann", 252),
        turn_z=_z("fut_turnover", 60),
        ret1=pl.col("fut_ret"),
        # pre-registration section 2: a day-t row earns close t+1 -> close t+2
        target=pl.col("fut_ret").shift(-2),
    )
    return p


FEATURES: dict[str, int] = {  # name -> expected sign (0 = two-sided)
    "fii_lr_z": +1,
    "fii_lr_d5": +1,
    "cli_lr_z": -1,
    "pro_lr_z": +1,
    "fii_opt_z": +1,
    "pcr_z": +1,
    "vix_z": +1,
    "vix_d5": +1,
    "buildup": +1,
    "oi_d5": 0,
    "basis_z": +1,
    "turn_z": 0,
    "ret1": 0,
}


def finite(x: np.ndarray) -> np.ndarray:
    return np.isfinite(x)
