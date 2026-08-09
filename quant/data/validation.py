"""Dataset validation.

Phase 02: timestamp checks, duplicate detection, OHLC integrity,
volume/OI sanity, trading-hours continuity, validation reports.

Checks run against the canonical candle schema. The report is JSON-serializable
and stored next to the raw dataset for the audit trail.
"""

from __future__ import annotations

import json
from dataclasses import dataclass, field
from datetime import datetime
from pathlib import Path

import polars as pl

EXPECTED_BARS_PER_DAY_1M = 375


@dataclass(frozen=True)
class CheckResult:
    """Outcome of one validation check."""

    name: str
    status: str  # pass | warn | fail
    details: str = ""
    failures: int = 0

    def to_dict(self) -> dict[str, object]:
        return {
            "name": self.name,
            "status": self.status,
            "details": self.details,
            "failures": self.failures,
        }


@dataclass
class ValidationReport:
    """Aggregated validation output."""

    dataset: str
    total_candles: int
    date_range: tuple[datetime, datetime]
    trading_days: int
    checks: list[CheckResult] = field(default_factory=list)
    overall_status: str = "pass"
    warnings: list[str] = field(default_factory=list)
    errors: list[str] = field(default_factory=list)

    def to_dict(self) -> dict[str, object]:
        return {
            "dataset": self.dataset,
            "total_candles": self.total_candles,
            "date_range": [dt.isoformat() for dt in self.date_range],
            "trading_days": self.trading_days,
            "checks": [c.to_dict() for c in self.checks],
            "overall_status": self.overall_status,
            "warnings": self.warnings,
            "errors": self.errors,
        }

    def save(self, path: str | Path) -> None:
        Path(path).write_text(json.dumps(self.to_dict(), indent=2), encoding="utf-8")


def validate_dataset(
    frame: pl.DataFrame,
    dataset: str,
    *,
    interval_minutes: int = 1,
) -> ValidationReport:
    """Run all checks against a candle frame and aggregate results."""
    checks: list[CheckResult] = []
    warnings: list[str] = []
    errors: list[str] = []

    ts = frame["timestamp"]
    n = frame.height
    expected_per_day = EXPECTED_BARS_PER_DAY_1M // interval_minutes

    # 1. Timestamps: monotonic and unique
    monotonic = bool((ts == ts.sort()).all())
    checks.append(CheckResult("timestamp_monotonic", "pass" if monotonic else "fail"))
    if not monotonic:
        errors.append("timestamps are not monotonically increasing")

    dup_count = int(frame.group_by("timestamp").agg(pl.len()).filter(pl.col("len") > 1).height)
    checks.append(
        CheckResult("no_duplicates", "pass" if dup_count == 0 else "fail", failures=dup_count)
    )
    if dup_count:
        errors.append(f"{dup_count} duplicate timestamps")

    # 2. Market hours (NSE F&O: 09:15 - 15:30 IST, bar opens only)
    out_of_hours = int(
        frame.filter(
            (pl.col("timestamp").dt.hour() < 9)
            | (pl.col("timestamp").dt.hour() > 15)
            | ((pl.col("timestamp").dt.hour() == 9) & (pl.col("timestamp").dt.minute() < 15))
            | ((pl.col("timestamp").dt.hour() == 15) & (pl.col("timestamp").dt.minute() >= 30))
        ).height
    )
    checks.append(
        CheckResult(
            "market_hours",
            "pass" if out_of_hours == 0 else "fail",
            failures=out_of_hours,
        )
    )
    if out_of_hours:
        errors.append(f"{out_of_hours} candles outside market hours")

    # 3. Daily bar counts (missing / extra bars)
    by_day = frame.group_by(pl.col("timestamp").dt.date()).agg(pl.len().alias("bars"))
    off_days = int(by_day.filter(pl.col("bars") != expected_per_day).height)
    checks.append(
        CheckResult(
            "daily_bar_counts",
            "pass" if off_days == 0 else "warn",
            details=f"{off_days} day(s) with != {expected_per_day} bars",
            failures=off_days,
        )
    )
    if off_days:
        warnings.append(
            f"{off_days} day(s) with unexpected bar counts ({expected_per_day} expected)"
        )

    # 4. OHLC integrity and value sanity
    ohlc_violations = int(
        frame.filter(
            (pl.col("high") < pl.col("low"))
            | (pl.col("high") < pl.col("open"))
            | (pl.col("high") < pl.col("close"))
            | (pl.col("low") > pl.col("open"))
            | (pl.col("low") > pl.col("close"))
            | (pl.col("open") <= 0)
            | (pl.col("high") <= 0)
            | (pl.col("low") <= 0)
            | (pl.col("close") <= 0)
            | pl.any_horizontal(pl.col("open", "high", "low", "close").is_null())
        ).height
    )
    checks.append(
        CheckResult(
            "ohlc_integrity",
            "pass" if ohlc_violations == 0 else "fail",
            failures=ohlc_violations,
        )
    )
    if ohlc_violations:
        errors.append(f"{ohlc_violations} OHLC integrity violations")

    # 5. Volume sanity
    negative_volume = int(frame.filter(pl.col("volume") < 0).height)
    zero_volume = int(frame.filter(pl.col("volume") == 0).height)
    checks.append(
        CheckResult(
            "volume_sanity",
            "fail" if negative_volume else ("warn" if zero_volume else "pass"),
            details=f"{negative_volume} negative, {zero_volume} zero-volume bars",
            failures=negative_volume + zero_volume,
        )
    )
    if negative_volume:
        errors.append(f"{negative_volume} candles with negative volume")
    elif zero_volume:
        warnings.append(f"{zero_volume} zero-volume candles")

    # 5. Open interest sanity (negative values; intraday bar-to-bar jumps > 25%)
    #    Overnight changes are skipped: the first bar of each day compares
    #    against nothing rather than the previous day's last bar.
    negative_oi = int(frame.filter(pl.col("open_interest") < 0).height)
    oi_jumps = 0
    if n > 1:
        prev = pl.col("open_interest").shift(1)
        ratio = (pl.col("open_interest") - prev).abs() / prev.clip(lower_bound=1.0)
        same_day_prev = pl.col("timestamp").dt.date().shift(1) == pl.col("timestamp").dt.date()
        oi_jumps = int(
            frame.with_columns(ratio.alias("_r"), same_day_prev.alias("_same"))
            .filter(pl.col("_same") & (pl.col("_r") > 0.25))
            .height
        )
    checks.append(
        CheckResult(
            "open_interest_sanity",
            "fail" if negative_oi else ("warn" if oi_jumps else "pass"),
            details=f"{negative_oi} negative, {oi_jumps} jumps > 25%",
            failures=negative_oi + oi_jumps,
        )
    )
    if negative_oi:
        errors.append(f"{negative_oi} candles with negative open interest")
    elif oi_jumps:
        warnings.append(f"{oi_jumps} bars with OI change > 25%")

    # 6. Continuity: no intraday spacing gaps
    if interval_minutes == 1 and n > 1:
        same_day = pl.col("timestamp").dt.date().shift(1) == pl.col("timestamp").dt.date()
        wrong_step = pl.col("timestamp").dt.epoch("s").diff() != 60
        intraday_gaps = int(
            frame.with_columns(same_day.alias("_same")).filter(pl.col("_same") & wrong_step).height
        )
        missing = max(0, expected_per_day * by_day.height - n)
        checks.append(
            CheckResult(
                "continuity",
                "warn" if intraday_gaps or missing else "pass",
                details=f"{intraday_gaps} intraday gaps, ~{missing} missing bars",
                failures=intraday_gaps + missing,
            )
        )
    else:
        checks.append(CheckResult("continuity", "pass", details="n/a"))

    statuses = [c.status for c in checks]
    if "fail" in statuses:
        overall = "fail"
    elif "warn" in statuses:
        overall = "pass_with_warnings"
    else:
        overall = "pass"

    return ValidationReport(
        dataset=dataset,
        total_candles=n,
        date_range=(ts.min(), ts.max()),
        trading_days=by_day.height,
        checks=checks,
        overall_status=overall,
        warnings=warnings,
        errors=errors,
    )


def validate_month(
    candle_path: str | Path,
    *,
    dataset: str | None = None,
    interval_minutes: int = 1,
) -> ValidationReport:
    """Validate a stored candles parquet file into an audit report."""
    path = Path(candle_path)
    frame = pl.read_parquet(path)
    name = dataset or path.stem
    report = validate_dataset(frame, name, interval_minutes=interval_minutes)
    report.save(path.with_name("validation_report.json"))
    return report
