"""Phase 03 unit tests: candle aggregation rules + verification.

Polars only; no network access.
"""

from __future__ import annotations

from datetime import date, datetime, timedelta

import polars as pl

from quant.candles.aggregation import aggregate_candles
from quant.candles.verify import verify_aggregation


def _candle_row(ts: datetime, price: float) -> dict:
    return {
        "timestamp": ts,
        "open": price,
        "high": price + 1,
        "low": price - 1,
        "close": price + 0.5,
        "volume": 100,
        "open_interest": 1000 + int(price),
    }


def _session_rows(day: date, n_bars: int = 375, start_price: float = 100.0):
    base = datetime(2026, 7, 1, 9, 15) + timedelta(days=(day - date(2026, 7, 1)).days)
    return [_candle_row(base + timedelta(minutes=i), start_price + i) for i in range(n_bars)]


def test_5m_boundaries_align_to_clock():
    df = pl.DataFrame(
        _session_rows(date(2026, 7, 1)), schema_overrides={"timestamp": pl.Datetime("ms")}
    )
    agg = aggregate_candles(df, 5)
    times = agg["timestamp"].to_list()
    assert times[0] == datetime(2026, 7, 1, 9, 15)
    assert times[1] == datetime(2026, 7, 1, 9, 20)
    assert times[-1] == datetime(2026, 7, 1, 15, 25)
    assert all(t.minute % 5 == 0 for t in times)
    assert agg.height == 375 // 5


def test_15m_boundaries_align_to_clock():
    frame = pl.DataFrame(
        _session_rows(date(2026, 7, 1)), schema_overrides={"timestamp": pl.Datetime("ms")}
    )
    agg = aggregate_candles(frame, 15)
    times = agg["timestamp"].to_list()
    assert times[0] == datetime(2026, 7, 1, 9, 15)
    assert times[1] == datetime(2026, 7, 1, 9, 30)
    assert times[-1] == datetime(2026, 7, 1, 15, 15)
    assert all(t.minute % 15 == 0 for t in times)
    assert agg.height == 375 // 15


def test_aggregate_rules_open_high_low_close_volume_oi():
    rows = _session_rows(date(2026, 7, 1), n_bars=5)
    frame = pl.DataFrame(rows, schema_overrides={"timestamp": pl.Datetime("ms")})
    agg = aggregate_candles(frame, 5)
    assert agg["open"][0] == 100.0
    assert agg["high"][0] == 105.0
    assert agg["low"][0] == 99.0
    assert agg["close"][0] == 104.5
    assert agg["volume"][0] == 500
    assert agg["open_interest"][0] == rows[-1]["open_interest"]


def test_buckets_never_cross_day_boundary():
    rows = _session_rows(date(2026, 7, 1)) + _session_rows(date(2026, 7, 2))
    frame = pl.DataFrame(rows, schema_overrides={"timestamp": pl.Datetime("ms")})
    agg = aggregate_candles(frame, 5)
    with_day = agg.with_columns(pl.col("timestamp").dt.date().alias("day_of"))
    days = with_day.group_by("day_of").agg(pl.len())
    assert {int(r["len"]) for r in days.to_dicts()} == {75}
    first_days = with_day.group_by("day_of").agg(pl.col("timestamp").min())
    assert first_days["timestamp"].to_list() == [
        datetime(2026, 7, 1, 9, 15),
        datetime(2026, 7, 2, 9, 15),
    ]


def test_aggregation_preserves_metadata_columns():
    rows = _session_rows(date(2026, 7, 1), n_bars=5)
    frame = pl.DataFrame(rows, schema_overrides={"timestamp": pl.Datetime("ms")})
    frame = frame.with_columns(
        pl.lit("NIFTY_FUT", dtype=pl.Utf8).alias("instrument"),
        pl.lit(1333, dtype=pl.Int64).alias("security_id"),
    )
    agg = aggregate_candles(frame, 5)
    assert agg["instrument"].unique().to_list() == ["NIFTY_FUT"]
    assert agg["security_id"].unique().to_list() == [1333]


def test_verify_passes_on_valid_derivation():
    frame = pl.DataFrame(
        _session_rows(date(2026, 7, 1)), schema_overrides={"timestamp": pl.Datetime("ms")}
    )
    for minutes in (5, 15):
        agg = aggregate_candles(frame, minutes)
        report = verify_aggregation(frame, agg, minutes, name=f"x{minutes}m")
        assert report["overall"] == "pass"
        names = {c["name"]: c["status"] for c in report["checks"]}
        assert names == {
            "bucket_size": "pass",
            "volume_sum": "pass",
            "ohlc_integrity": "pass",
            "boundary_alignment": "pass",
            "edge_alignment": "pass",
        }
        assert report["derived_count"] == 375 // minutes


def test_verify_catches_off_boundary_and_volume_drift():
    frame = pl.DataFrame(
        _session_rows(date(2026, 7, 1)), schema_overrides={"timestamp": pl.Datetime("ms")}
    )
    agg = aggregate_candles(frame, 5)
    tampered = agg.with_columns((pl.col("volume") + 1).alias("volume"))
    report = verify_aggregation(frame, tampered, 5, name="tampered")
    names = {c["name"]: c["status"] for c in report["checks"]}
    assert names["volume_sum"] == "fail"


def test_verify_warns_on_partial_final_bucket():
    frame = pl.DataFrame(
        _session_rows(date(2026, 7, 1), n_bars=11),
        schema_overrides={"timestamp": pl.Datetime("ms")},
    )
    agg = aggregate_candles(frame, 5)
    report = verify_aggregation(frame, agg, 5, name="partial")
    names = {c["name"]: c["status"] for c in report["checks"]}
    assert names["bucket_size"] == "warn"


def test_trailing_empty_bucket_is_not_created():
    frame = pl.DataFrame(
        _session_rows(date(2026, 7, 1), n_bars=375),
        schema_overrides={"timestamp": pl.Datetime("ms")},
    )
    agg = aggregate_candles(frame, 5)
    assert agg.height == 75


def test_verify_month_writes_report(tmp_path):
    frame = pl.DataFrame(
        _session_rows(date(2026, 7, 1)), schema_overrides={"timestamp": pl.Datetime("ms")}
    )
    src = tmp_path / "candles_1m.parquet"
    frame.write_parquet(src)
    out = tmp_path / "15m"
    out.mkdir()
    aggregate_candles(frame, 15).write_parquet(out / "candles.parquet")
    from quant.candles.verify import verify_month

    report = verify_month(src, out, minutes=15, dataset="x")
    assert report["overall"] == "pass"
    assert (out / "verification_report.json").exists()
