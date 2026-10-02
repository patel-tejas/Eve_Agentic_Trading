"""Shared synthetic data and specs for the Phase 15 tests."""

from __future__ import annotations

from datetime import datetime, timedelta

import numpy as np
import polars as pl


def intraday_candles(days: int = 22, minutes: int = 15, seed: int = 7) -> pl.DataFrame:
    """Random-walk NIFTY-like bars, 09:15 -> 15:15 on weekdays of July 2026."""
    rng = np.random.default_rng(seed)
    rows = []
    price = 24_000.0
    day = datetime(2026, 7, 1)
    made = 0
    while made < days:
        if day.weekday() < 5:
            t = day.replace(hour=9, minute=15)
            end = day.replace(hour=15, minute=15)
            while t <= end:
                o = price
                c = o + rng.normal(0, 18)
                h = max(o, c) + abs(rng.normal(0, 8))
                low = min(o, c) - abs(rng.normal(0, 8))
                rows.append(
                    {"timestamp": t, "open": o, "high": h, "low": low, "close": c,
                     "volume": float(rng.integers(1_000, 9_000))}
                )
                price = c
                t += timedelta(minutes=minutes)
            made += 1
        day += timedelta(days=1)
    return pl.DataFrame(rows, schema_overrides={"timestamp": pl.Datetime("ms")})


def write_processed(root, timeframe: str = "15m", **kw) -> None:
    d = root / "2026-07" / timeframe
    d.mkdir(parents=True, exist_ok=True)
    minutes = int(timeframe.rstrip("m"))
    intraday_candles(minutes=minutes, **kw).write_parquet(d / "candles.parquet")


def ind(name: str, offset: int = 0, output: str | None = None, **params) -> dict:
    out = {"kind": "indicator", "name": name, "params": params, "offset": offset}
    if output:
        out["output"] = output
    return out


def const(v: float) -> dict:
    return {"kind": "const", "value": v}


def cond(lhs: dict, cmp: str, rhs: dict | None = None, bars: int | None = None) -> dict:
    out: dict = {"lhs": lhs, "cmp": cmp}
    if rhs is not None:
        out["rhs"] = rhs
    if bars is not None:
        out["bars"] = bars
    return out


def long_spec(entry: list[dict], exit_any: list[dict] | None = None, **over) -> dict:
    spec = {
        "name": "test",
        "timeframe": "15m",
        "direction": "long_only",
        "entry": {"long": {"all": entry}},
        "exit": {"long": {"any": exit_any or []}},
        "risk": {"stop": {"mode": "pct", "value": 1.0}},
    }
    spec.update(over)
    return spec
