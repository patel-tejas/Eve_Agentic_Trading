"""Phase 02 unit tests: dataset validation checks + reports.

These tests do not touch the network.
"""

from datetime import date, datetime

import polars as pl
import pytest

from quant.candles.aggregation import aggregate_candles
from quant.data.validation import validate_dataset, validate_month
from quant.indicators.angle import AngleParams, add_ema_angle
from quant.indicators.ema import add_ema


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


def _good_frame_375() -> pl.DataFrame:
    rows = []
    for day in (date(2026, 7, 1), date(2026, 7, 2)):
        for i in range(375):
            ts = datetime(2026, 7, 1, 9, 15) + __import__("datetime").timedelta(
                days=(day - date(2026, 7, 1)).days, minutes=i
            )
            rows.append(_candle_row(ts, 100.0 + i))
    return pl.DataFrame(rows, schema_overrides={"timestamp": pl.Datetime("ms")})


def test_validation_passes_clean_frame():
    df = _good_frame_375()
    report = validate_dataset(df, "clean")
    assert report.overall_status == "pass"


def test_validation_out_of_bounds():
    # OHLC values that are <= 0 must be rejected
    df = _good_frame_375()
    df = df.with_columns((pl.col("low") - 100).alias("low"))
    report = validate_dataset(df, "oob")
    names = {c.name: c.status for c in report.checks}
    assert names["ohlc_integrity"] == "fail"


def test_validation_flags_ohlc_violation():
    df = _good_frame_375()
    df = df.with_columns(
        pl.when(pl.int_range(pl.len()) == 5)
        .then(pl.col("close") + 1000)
        .otherwise(pl.col("close"))
        .alias("close")
    )
    report = validate_dataset(df, "bad_ohlc")
    assert report.overall_status == "fail"
    names = {c.name for c in report.checks}
    assert "ohlc_integrity" in names


def test_validation_flags_duplicates():
    df = _good_frame_375()
    df = pl.concat([df, df.head(3)])
    report = validate_dataset(df, "dupes")
    assert report.overall_status in ("fail", "pass_with_warnings")
    check = next(c for c in report.checks if c.name == "no_duplicates")
    assert check.status == "fail"


def test_validation_clean_intraday_oi_jump_warns():
    df = _good_frame_375()
    df = df.with_columns(
        pl.when(pl.int_range(pl.len()) == 30)
        .then(pl.col("open_interest") * 10)
        .otherwise(pl.col("open_interest"))
        .alias("open_interest")
    )
    report = validate_dataset(df, "oi_jump")
    names = {c.name: c.status for c in report.checks}
    assert names["open_interest_sanity"] == "warn"


def test_validation_overnight_oi_change_ignored():
    # day 2 opens at a completely different OI level (tripled). The only
    # jump is across the day boundary: must NOT warn.
    n = _good_frame_375().height
    half = n // 2
    df = _good_frame_375()
    df = df.with_columns(
        pl.when(pl.int_range(pl.len()) < half)
        .then(pl.col("open_interest"))
        .otherwise(pl.col("open_interest") * 3)
        .alias("open_interest")
    )
    report = validate_dataset(df, "overnight")
    names = {c.name: c.status for c in report.checks}
    assert names["open_interest_sanity"] == "pass"


def test_validation_out_of_hours():
    # a bar before 09:15 or after 15:30 must fail market_hours
    bad = pl.DataFrame(
        [_candle_row(datetime(2026, 7, 1, 15, 31), 1000.0)],
        schema_overrides={"timestamp": pl.Datetime("ms")},
    )
    df = pl.concat([_good_frame_375(), bad])
    report = validate_dataset(df, "ooh")
    names = {c.name: c.status for c in report.checks}
    assert names["market_hours"] == "fail"


def test_aggregation_counts_and_values():
    base = datetime(2026, 7, 1, 9, 15)
    rows = [
        _candle_row(base + __import__("datetime").timedelta(minutes=i), 100.0 + i)
        for i in range(15)
    ]
    df = pl.DataFrame(rows)
    for minutes, expected in ((5, 3), (15, 1)):
        agg = aggregate_candles(df, minutes)
        assert agg.height == expected
        assert agg["timestamp"][0] == base
        assert agg["volume"].sum() == df["volume"].sum()
        assert agg["high"][0] >= agg["open"][0]


def test_aggregate_open_is_first_close_is_last():
    df = pl.DataFrame(
        [
            _candle_row(
                datetime(2026, 7, 1, 9, 15) + __import__("datetime").timedelta(minutes=i), 100.0 + i
            )
            for i in range(5)
        ]
    )
    agg = aggregate_candles(df, 5)
    assert agg["open"][0] == 100.0
    assert agg["close"][0] == 104.5
    assert agg["high"][0] == 105.0
    assert agg["low"][0] == 99.0


def test_ema_warmup_and_values():
    df = pl.DataFrame({"close": [1.0, 2.0, 3.0, 4.0, 5.0]})
    out = add_ema(df, 3)
    vals = out["ema_3"].to_list()
    assert vals[0] is None and vals[1] is None
    assert vals[2] == pytest.approx(2.25)
    assert vals[3] == pytest.approx(3.125)
    assert vals[4] == pytest.approx(4.0625)


def test_angle_deg_matches_definition():
    df = pl.DataFrame({"close": [1.0, 2.0, 3.0, 4.0, 5.0]})
    out = add_ema(df, 3)
    out = add_ema_angle(out, "ema_3", lookback=1, scale=1.0)
    # last two EMA values: 3.125, 4.0625 -> slope 0.3 -> atan(0.3) deg
    expected = __import__("math").degrees(__import__("math").atan(0.3))
    assert out["ema_3_angle_deg"][4] == pytest.approx(expected)
    assert out["ema_3_angle_deg"][0] is None


def test_angle_params_defaults():
    params = AngleParams()
    assert params.threshold == 30.0
    assert params.lookback == 1
    assert params.scale == 1000.0


def test_validate_month_writes_report(tmp_path):
    df = _good_frame_375()
    p = tmp_path / "candles_1m.parquet"
    df.write_parquet(p)
    report = validate_month(p, dataset="test")
    assert report.overall_status == "pass"
    assert (tmp_path / "validation_report.json").exists()
