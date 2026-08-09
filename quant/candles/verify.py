"""Candle aggregation verification.

Phase 03: verify that derived timeframes are faithful to the source 1m
data -- candle counts, volume sums, OHLC integrity, and wall-clock
boundary alignment.
"""

from __future__ import annotations

import json
from pathlib import Path

import polars as pl


def verify_aggregation(
    source_1m: pl.DataFrame,
    aggregated: pl.DataFrame,
    minutes: int,
    *,
    name: str = "derived",
) -> dict[str, object]:
    """Cross-check ``aggregated`` (a ``minutes``-minute regroup) against 1m source.

    Returns a JSON-serializable report:
        name, minutes, source_count, derived_count, checks, overall
    """
    checks: list[dict[str, object]] = []

    def add(name_: str, status: str, details: str, failures: int) -> None:
        checks.append(
            {
                "name": name_,
                "status": status,
                "details": details,
                "failures": failures,
            }
        )

    src = source_1m.sort("timestamp")
    agg = aggregated.sort("timestamp")
    n_src = src.height
    n_agg = agg.height

    # 1. Bucket size: every aggregated candle spans exactly ``minutes``
    #    1m bars (full sessions -> no trailing partial bucket expected).
    bucket = (src["timestamp"].dt.epoch("s") // (minutes * 60)).alias("bucket")
    sizes = (
        src.select(bucket)
        .group_by("bucket")
        .agg(pl.len().alias("bars"))
        .filter(pl.col("bars") != minutes)
    )
    off_sized = sizes.height
    add(
        "bucket_size",
        "pass" if off_sized == 0 else "warn",
        f"{off_sized} bucket(s) not containing exactly {minutes} bars",
        off_sized,
    )

    # 2. Total volume must match the source exactly (no data loss).
    total_src = int(src["volume"].sum())
    total_agg = int(agg["volume"].sum())
    volume_ok = total_src == total_agg
    add(
        "volume_sum",
        "pass" if volume_ok else "fail",
        f"1m={total_src} vs {minutes}m={total_agg}",
        0 if volume_ok else abs(total_src - total_agg),
    )

    # 3. OHLC integrity of aggregated candles.
    viol = int(
        agg.filter(
            (pl.col("high") < pl.col("low"))
            | (pl.col("high") < pl.col("open"))
            | (pl.col("high") < pl.col("close"))
            | (pl.col("low") > pl.col("open"))
            | (pl.col("low") > pl.col("close"))
        ).height
    )
    add(
        "ohlc_integrity",
        "pass" if viol == 0 else "fail",
        f"{viol} violations",
        viol,
    )

    # 4. Boundary alignment: bucket timestamps sit on wall-clock boundaries.
    minute_of_day = agg["timestamp"].dt.hour().cast(pl.Int64) * 60 + agg[
        "timestamp"
    ].dt.minute().cast(pl.Int64)
    off_boundary = int((minute_of_day % minutes != 0).sum())
    add(
        "boundary_alignment",
        "pass" if off_boundary == 0 else "fail",
        f"{off_boundary} timestamp(s) off a {minutes}-minute wall-clock grid",
        off_boundary,
    )

    # 5. First/last alignment: first bucket resumes on the first source
    #    minute; the last bucket opens no later than ``minutes`` before the
    #    last source minute.
    first_matches = agg["timestamp"][0] == src["timestamp"][0]
    last_ok = (
        int(src["timestamp"].dt.epoch("s")[-1]) - int(agg["timestamp"].dt.epoch("s")[-1])
        < minutes * 60
    )
    add(
        "edge_alignment",
        "pass" if first_matches and last_ok else "fail",
        f"first={first_matches}, last_within={last_ok}",
        0 if first_matches and last_ok else 1,
    )

    statuses = [c["status"] for c in checks]
    overall = "fail" if "fail" in statuses else "pass"

    return {
        "name": name,
        "minutes": minutes,
        "source_count": n_src,
        "derived_count": n_agg,
        "checks": checks,
        "overall": overall,
    }


def verify_month(
    source_1m_path: str | Path,
    processed_dir: str | Path,
    *,
    minutes: int,
    dataset: str | None = None,
) -> dict[str, object]:
    """Verify one stored processed timeframe against the raw source parquet.

    Writes ``verification_report.json`` into the processed timeframe dir.
    """
    src = pl.read_parquet(source_1m_path)
    agg = pl.read_parquet(Path(processed_dir) / "candles.parquet")
    report = verify_aggregation(src, agg, minutes, name=dataset or f"{minutes}m")
    out = Path(processed_dir) / "verification_report.json"
    out.write_text(json.dumps(report, indent=2), encoding="utf-8")
    return report
