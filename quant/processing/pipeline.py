"""Monthy processing pipeline.

Phase 02+03: validate raw 1m candles, resample to higher timeframes,
compute EMA/angle indicators on every timeframe, and store derived
datasets with audit metadata.

Layout:
    data/raw/futures/NIFTY/2026-07/candles_1m.parquet          (input)
    data/raw/futures/NIFTY/2026-07/validation_report.json       (output)
    data/processed/futures/NIFTY/2026-07/{1m,5m,15m}/candles.parquet
    data/processed/futures/NIFTY/2026-07/{1m,5m,15m}/dataset_metadata.json
"""

from __future__ import annotations

import json
from pathlib import Path

import polars as pl

from quant.candles.aggregation import aggregate_candles
from quant.candles.verify import verify_aggregation
from quant.indicators.angle import add_ema_angle
from quant.indicators.ema import add_ema

DEFAULT_TIMEFRAMES = (1, 5, 15)
DEFAULT_EMA_PERIODS = (9, 15)
DEFAULT_ANGLE = {"lookback": 1, "scale": 1000.0}
DATASET_SCHEMA = {
    "timestamp": pl.Datetime("ms"),
    "instrument": pl.Utf8,
    "security_id": pl.Utf8,
    "exchange": pl.Utf8,
    "instrument_type": pl.Utf8,
    "expiry": pl.Date,
    "open": pl.Float64,
    "high": pl.Float64,
    "low": pl.Float64,
    "close": pl.Float64,
    "volume": pl.Int64,
    "open_interest": pl.Int64,
    "lot_size": pl.Int64,
    "tick_size": pl.Float64,
}


def add_indicators(
    frame: pl.DataFrame,
    *,
    ema_periods: tuple[int, ...] = DEFAULT_EMA_PERIODS,
    angle_lookback: int = 1,
    angle_scale: float = 1000.0,
) -> pl.DataFrame:
    """Attach EMA(period) and EMA-angle columns for each period."""
    out = frame
    for period in ema_periods:
        out = add_ema(out, period)
        out = add_ema_angle(
            out,
            f"ema_{period}",
            lookback=angle_lookback,
            scale=angle_scale,
        )
    return out


def process_month(
    *,
    year: int,
    month: int,
    raw_root: str | Path = "data/raw/futures/NIFTY",
    processed_root: str | Path = "data/processed/futures/NIFTY",
    timeframes: tuple[int, ...] = DEFAULT_TIMEFRAMES,
    ema_periods: tuple[int, ...] = DEFAULT_EMA_PERIODS,
    angle_lookback: int = 1,
    angle_scale: float = 1000.0,
) -> dict[str, object]:
    """Process one harvest month: validate 1m, resample, add indicators, store."""
    raw_root = Path(raw_root)
    processed_root = Path(processed_root)
    month_dir = raw_root / f"{year:04d}-{month:02d}"
    candles_path = month_dir / "candles_1m.parquet"
    if not candles_path.exists():
        raise FileNotFoundError(f"Missing raw dataset: {candles_path}")

    # 1. Validate source 1m data -> audit report stored next to raw data
    from quant.data.validation import validate_dataset

    raw = pl.read_parquet(candles_path).sort("timestamp")
    report = validate_dataset(raw, f"{year:04d}-{month:02d}_1m", interval_minutes=1)
    report.save(month_dir / "validation_report.json")
    if report.overall_status == "fail":
        raise RuntimeError(f"Validation failed for {year:04d}-{month:02d}: {report.errors}")

    # 2. Resample + indicators per timeframe
    processed_month = processed_root / f"{year:04d}-{month:02d}"
    results: dict[str, object] = {}
    for tf in timeframes:
        frame = raw if tf == 1 else aggregate_candles(raw, tf)
        frame = add_indicators(
            frame,
            ema_periods=ema_periods,
            angle_lookback=angle_lookback,
            angle_scale=angle_scale,
        )
        out_dir = processed_month / f"{tf}m"
        out_dir.mkdir(parents=True, exist_ok=True)
        out_path = out_dir / "candles.parquet"
        frame.write_parquet(out_path)
        metadata = {
            "dataset": f"NIFTY_FUT_{year:04d}-{month:02d}_{tf}m",
            "source": str(candles_path),
            "parent_timeframe": "1m" if tf == 1 else "1m-resampled",
            "timeframe_minutes": tf,
            "bars": frame.height,
            "indicators": {
                "ema_periods": list(ema_periods),
                "angle": {"lookback": angle_lookback, "scale": angle_scale},
            },
            "price_cols": ["open", "high", "low", "close", "volume", "open_interest"],
        }
        metadata_path = out_dir / "dataset_metadata.json"
        metadata_path.write_text(json.dumps(metadata, indent=2), encoding="utf-8")
        results[f"{tf}m"] = {"path": str(out_path), "bars": frame.height}

    # 3. Verify every derived timeframe against the raw 1m source
    verification: dict[str, dict[str, object]] = {}
    for tf in timeframes:
        if tf == 1:
            continue
        out_dir = processed_month / f"{tf}m"
        vreport = verify_aggregation(
            raw,
            pl.read_parquet(out_dir / "candles.parquet"),
            tf,
            name=f"NIFTY_FUT_{year:04d}-{month:02d}_{tf}m",
        )
        (out_dir / "verification_report.json").write_text(
            json.dumps(vreport, indent=2), encoding="utf-8"
        )
        verification[f"{tf}m"] = vreport["overall"]

    return {
        **results,
        "validation": report.overall_status,
        "verification": verification,
    }
