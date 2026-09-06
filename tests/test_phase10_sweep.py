"""Phase 09: parallel sweep harness + leaderboard.

Uses a tiny on-disk candle fixture (tmp_path) rather than the real
processed data, so these tests are fast and self-contained.
"""

from __future__ import annotations

import os
from datetime import datetime, timedelta

import polars as pl
import pytest

import quant.strategies.pdh_pdl_turtle_soup  # noqa: F401 -- registers the strategy
from quant.research.leaderboard import (
    cumulative_trial_count,
    load_leaderboard,
    trial_param_hash,
)
from quant.research.sweep import Trial, run_sweep

BASE = datetime(2026, 7, 1, 9, 15)


def _write_candles(path) -> None:
    rows = []
    price = 100.0
    for day in range(10):
        for bar in range(25):
            ts = BASE + timedelta(days=day) + timedelta(minutes=15 * bar)
            price += 0.1 * ((bar % 5) - 2)
            rows.append(
                {
                    "timestamp": ts,
                    "open": price,
                    "high": price + 1.0,
                    "low": price - 1.0,
                    "close": price + 0.2,
                    "volume": 0,
                }
            )
    pl.DataFrame(rows, schema_overrides={"timestamp": pl.Datetime("ms")}).write_parquet(path)


@pytest.fixture()
def candles_path(tmp_path) -> str:
    path = tmp_path / "candles.parquet"
    _write_candles(path)
    return str(path)


def _trial(candles_path: str, *, revert_bars: int, round_no: int = 1) -> Trial:
    return Trial(
        campaign_id="TEST-SWEEP",
        round=round_no,
        strategy_id="pdh_pdl_turtle_soup",
        strategy_version="v1",
        params={"revert_bars": revert_bars, "min_overshoot_atr": 0.1},
        exits={"stop_mode": "signal", "target_mode": "signal", "eod_squareoff": "15:15"},
        symbol="NIFTY",
        price_source="futures",
        timeframe="15m",
        split="train",
        candles_path=candles_path,
        window_start=None,
        window_end=None,
        lot_size=65,
        tick_size_rupees=0.10,
    )


def test_param_hash_stable_under_key_reordering():
    a = trial_param_hash("ema", {"a": 1, "b": 2}, {"stop_mode": "atr"}, {"lot_size": 65})
    b = trial_param_hash("ema", {"b": 2, "a": 1}, {"stop_mode": "atr"}, {"lot_size": 65})
    assert a == b


def test_param_hash_differs_for_different_params():
    a = trial_param_hash("ema", {"a": 1}, {}, {"lot_size": 65})
    b = trial_param_hash("ema", {"a": 2}, {}, {"lot_size": 65})
    assert a != b


def test_run_sweep_writes_leaderboard_rows(tmp_path, candles_path):
    trials = [_trial(candles_path, revert_bars=r) for r in (1, 2, 3)]
    root = str(tmp_path / "leaderboard")
    summary = run_sweep(trials, campaign_id="TEST-SWEEP", round_no=1, workers=2, root=root)
    assert summary["submitted"] == 3
    assert summary["skipped"] == 0
    assert summary["errors"] == 0

    lb = load_leaderboard("TEST-SWEEP", root=root)
    assert lb.height == 3
    assert lb["trial_id"].n_unique() == 3
    assert set(lb["status"].to_list()) == {"ok"}


def test_run_sweep_resume_adds_zero_rows(tmp_path, candles_path):
    trials = [_trial(candles_path, revert_bars=r) for r in (1, 2, 3)]
    root = str(tmp_path / "leaderboard")
    run_sweep(trials, campaign_id="TEST-SWEEP", round_no=1, workers=2, root=root)

    summary2 = run_sweep(trials, campaign_id="TEST-SWEEP", round_no=1, workers=2, root=root)
    assert summary2["submitted"] == 0
    assert summary2["skipped"] == 3

    lb = load_leaderboard("TEST-SWEEP", root=root)
    assert lb.height == 3  # still 3, not 6


def test_run_sweep_dedupes_identical_trials_in_one_call(tmp_path, candles_path):
    """Two Trial objects with the same effective config (same trial_id)
    submitted in the SAME call must not both run and both get written."""
    trials = [
        _trial(candles_path, revert_bars=2),
        _trial(candles_path, revert_bars=2),  # exact duplicate
        _trial(candles_path, revert_bars=3),
    ]
    root = str(tmp_path / "leaderboard")
    summary = run_sweep(trials, campaign_id="TEST-SWEEP", round_no=1, workers=2, root=root)
    assert summary["submitted"] == 2  # only 2 distinct trial_ids
    assert summary["skipped"] == 1

    lb = load_leaderboard("TEST-SWEEP", root=root)
    assert lb.height == 2
    assert lb["trial_id"].n_unique() == 2


def test_cumulative_trial_count_is_distinct_param_hash_across_rounds(tmp_path, candles_path):
    root = str(tmp_path / "leaderboard")
    run_sweep(
        [_trial(candles_path, revert_bars=1, round_no=1)],
        campaign_id="TEST-SWEEP",
        round_no=1,
        workers=1,
        root=root,
    )
    run_sweep(
        [_trial(candles_path, revert_bars=1, round_no=2)],  # same params, different round
        campaign_id="TEST-SWEEP",
        round_no=2,
        workers=1,
        root=root,
    )
    # Same params -> same param_hash, even though trial_id differs by round.
    assert cumulative_trial_count("TEST-SWEEP", root=root) == 1


def test_single_threaded_env_vars_set_by_run_sweep(tmp_path, candles_path):
    """POLARS_MAX_THREADS alone is not enough -- a real round-2 run with
    14 workers hit "OpenBLAS error: Memory allocation still failed"
    and crashed the whole pool (BrokenProcessPool) before this fix, since
    numpy's BLAS backend has its own, independent thread pool."""
    env_vars = (
        "POLARS_MAX_THREADS",
        "OPENBLAS_NUM_THREADS",
        "OMP_NUM_THREADS",
        "MKL_NUM_THREADS",
        "NUMEXPR_NUM_THREADS",
    )
    for var in env_vars:
        os.environ.pop(var, None)
    trials = [_trial(candles_path, revert_bars=1)]
    run_sweep(trials, campaign_id="TEST-SWEEP", round_no=1, workers=1, root=str(tmp_path / "lb"))
    for var in env_vars:
        assert os.environ.get(var) == "1", f"{var} was not set before the pool was created"


def test_error_in_one_trial_does_not_kill_the_sweep(tmp_path, candles_path):
    bad_trial = _trial(candles_path, revert_bars=1)
    bad_trial = Trial(**{**bad_trial.__dict__, "strategy_id": "not_a_real_strategy"})
    good_trial = _trial(candles_path, revert_bars=2)
    root = str(tmp_path / "leaderboard")
    summary = run_sweep(
        [bad_trial, good_trial], campaign_id="TEST-SWEEP", round_no=1, workers=2, root=root
    )
    assert summary["submitted"] == 2
    assert summary["errors"] == 1

    lb = load_leaderboard("TEST-SWEEP", root=root)
    statuses = dict(zip(lb["trial_id"].to_list(), lb["status"].to_list(), strict=True))
    assert statuses[bad_trial.trial_id] == "error"
    assert statuses[good_trial.trial_id] == "ok"
