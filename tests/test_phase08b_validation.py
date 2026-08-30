"""Phase 08b unit tests: statistical validation, multiple testing, run cards.

No network, no data files: every input is constructed in-process, and every
resampling call is seeded so the assertions are exact rather than flaky.
"""

from __future__ import annotations

import json
import math
from dataclasses import replace
from datetime import datetime

import numpy as np
import polars as pl
import pytest

from quant.backtest.engine import BacktestConfig, run_backtest
from quant.backtest.metrics import daily_closing_equity, daily_returns
from quant.research._stats import (
    kurtosis,
    norm_cdf,
    norm_ppf,
    sharpe_ratio,
    skewness,
    stdev,
)
from quant.research.multiple_testing import (
    benjamini_hochberg,
    deflated_sharpe_ratio,
    expected_maximum_sharpe,
    probabilistic_sharpe_ratio,
    probability_of_backtest_overfitting,
)
from quant.research.parameter_search import GridResult
from quant.research.run_card import (
    build_run_card,
    canonical_json,
    hash_mapping,
    render_run_card_markdown,
    verify_run_card,
    write_run_card,
)
from quant.research.significance import (
    bootstrap_sharpe_ci,
    monte_carlo_permutation_test,
)
from quant.research.validate import (
    SearchValidation,
    _aligned_matrix,
    validate_parameter_search,
)
from quant.research.walk_forward import DEFAULT_EMBARGO_DAYS, define_walk_windows

# --------------------------------------------------------------------------
# _stats primitives
# --------------------------------------------------------------------------


@pytest.mark.parametrize("p", [0.0001, 0.01, 0.25, 0.5, 0.75, 0.99, 0.9999])
def test_norm_ppf_inverts_norm_cdf(p: float) -> None:
    """The Halley-refined approximation must round-trip to machine precision."""
    assert norm_cdf(norm_ppf(p)) == pytest.approx(p, abs=1e-12)


def test_norm_cdf_known_values() -> None:
    assert norm_cdf(0.0) == pytest.approx(0.5)
    assert norm_cdf(1.959963984540054) == pytest.approx(0.975, abs=1e-12)


@pytest.mark.parametrize("p", [0.0, 1.0, -0.1, 1.5])
def test_norm_ppf_rejects_out_of_range(p: float) -> None:
    with pytest.raises(ValueError):
        norm_ppf(p)


def test_moments_of_a_normal_sample() -> None:
    sample = np.random.default_rng(7).normal(0.0, 1.0, 20_000).tolist()
    assert skewness(sample) == pytest.approx(0.0, abs=0.05)
    # Non-excess kurtosis: a normal distribution sits at 3.0, not 0.0.
    assert kurtosis(sample) == pytest.approx(3.0, abs=0.1)
    assert stdev(sample) == pytest.approx(1.0, abs=0.02)


def test_kurtosis_is_non_excess_for_short_samples() -> None:
    assert kurtosis([1.0, 2.0]) == 3.0


def test_sharpe_annualisation_is_opt_out() -> None:
    rets = [0.01, -0.005, 0.02, 0.0, 0.008]
    per_period = sharpe_ratio(rets, annualised=False)
    annual = sharpe_ratio(rets)
    assert annual == pytest.approx(per_period * math.sqrt(252.0))


def test_sharpe_of_a_flat_series_is_zero() -> None:
    assert sharpe_ratio([0.01] * 10) == 0.0


# --------------------------------------------------------------------------
# daily returns plumbing
# --------------------------------------------------------------------------


def _equity_frame(values: list[float], start_day: int = 1) -> pl.DataFrame:
    """One bar at 10:00 and 15:00 for each of ``len(values)//2`` days."""
    rows = []
    for i, v in enumerate(values):
        day = start_day + i // 2
        hour = 10 if i % 2 == 0 else 15
        rows.append({"timestamp": datetime(2026, 7, day, hour), "equity": v})
    return pl.DataFrame(rows, schema_overrides={"timestamp": pl.Datetime("ms")})


def test_daily_closing_equity_takes_last_bar_of_each_day() -> None:
    frame = _equity_frame([100.0, 110.0, 110.0, 121.0])
    assert daily_closing_equity(frame) == [110.0, 121.0]


def test_daily_returns_are_day_over_day() -> None:
    frame = _equity_frame([100.0, 110.0, 110.0, 121.0])
    assert daily_returns(frame) == pytest.approx([0.1])


def test_daily_returns_empty_for_a_single_day() -> None:
    assert daily_returns(_equity_frame([100.0, 110.0])) == []
    assert daily_returns(_equity_frame([])) == []


def test_backtest_result_exposes_daily_returns() -> None:
    """The engine must hand back the series the statistical tests consume."""
    rows = []
    for day in range(1, 6):
        for hour in (10, 11, 12, 13, 14, 15):
            price = 100.0 + day * 2.0 + hour * 0.1
            rows.append(
                {
                    "timestamp": datetime(2026, 7, day, hour),
                    "open": price,
                    "high": price + 1,
                    "low": price - 1,
                    "close": price,
                }
            )
    candles = pl.DataFrame(rows, schema_overrides={"timestamp": pl.Datetime("ms")})
    signals = pl.DataFrame(
        {
            "timestamp": [r["timestamp"] for r in rows],
            "signal_type": ["LONG"] * len(rows),
        },
        schema_overrides={"timestamp": pl.Datetime("ms")},
    )
    result = run_backtest(candles, signals, BacktestConfig())

    assert isinstance(result.daily_returns, list)
    assert result.daily_returns == daily_returns(result.equity)
    # 5 distinct days -> 4 day-over-day returns.
    assert len(result.daily_returns) == 4


# --------------------------------------------------------------------------
# permutation test
# --------------------------------------------------------------------------


def test_permutation_test_is_reproducible() -> None:
    pnls = np.random.default_rng(3).normal(200, 3000, 80).tolist()
    a = monte_carlo_permutation_test(pnls, iterations=200, seed=42)
    b = monte_carlo_permutation_test(pnls, iterations=200, seed=42)
    assert a.p_value == b.p_value
    assert a.null_mean == b.null_mean


def test_permutation_p_value_is_never_zero() -> None:
    """Davison-Hinkley +1 correction: an unbeaten run reports 1/(N+1)."""
    # A monotonically rising equity curve has zero drawdown, which no
    # re-ordering can improve on.
    result = monte_carlo_permutation_test([100.0] * 30, iterations=99, seed=1)
    assert result.p_value > 0.0
    assert result.p_value == pytest.approx(1.0)


def test_permutation_total_pnl_is_exactly_one() -> None:
    """Sum is order-invariant, so the test must be able to say so exactly.

    This is why ``_path_statistic`` uses ``math.fsum`` rather than ``np.sum``:
    ordinary float addition is not associative, and a shuffled ``np.sum``
    differs in the last bits, which scatters this p-value around 0.5.
    """
    pnls = np.random.default_rng(11).normal(500, 5000, 120).tolist()
    result = monte_carlo_permutation_test(pnls, statistic="total_pnl", iterations=200)
    assert result.p_value == 1.0


def test_permutation_detects_a_favourably_ordered_path() -> None:
    """A perfectly alternating path has a drawdown almost no shuffle matches.

    Every loss is followed by a win, so no drawdown is ever more than one loss
    deep (~0.4%). A random shuffle clusters losses and typically reaches ~2%,
    which is exactly the ordering luck this test is meant to detect.
    """
    alternating = [x for _ in range(20) for x in (5000.0, -4000.0)]
    result = monte_carlo_permutation_test(alternating, iterations=500, seed=5)
    assert result.p_value < 0.05
    assert result.significant_at_5pct
    # Observed drawdown is well under the median of the shuffled null.
    assert -result.observed < -result.null_percentiles["p50"]


def test_permutation_does_not_flag_an_unfavourably_ordered_path() -> None:
    """The mirror case: all wins then all losses is the WORST ordering.

    Guards the sign convention in ``_path_statistic`` -- drawdown is negated
    so larger is better, and getting that backwards would make this the most
    significant result rather than the least.
    """
    grouped = [5000.0] * 20 + [-4000.0] * 20
    result = monte_carlo_permutation_test(grouped, iterations=500, seed=5)
    assert result.p_value == pytest.approx(1.0)
    assert not result.significant_at_5pct


def test_permutation_rejects_bad_input() -> None:
    with pytest.raises(ValueError, match="at least 2 trades"):
        monte_carlo_permutation_test([1.0])
    with pytest.raises(ValueError, match="statistic must be one of"):
        monte_carlo_permutation_test([1.0, 2.0], statistic="alpha")


def test_permutation_result_to_dict_is_json_serialisable() -> None:
    result = monte_carlo_permutation_test([1.0, -2.0, 3.0], iterations=20)
    json.dumps(result.to_dict())


# --------------------------------------------------------------------------
# bootstrap Sharpe CI
# --------------------------------------------------------------------------


def test_bootstrap_interval_brackets_the_point_estimate() -> None:
    rets = np.random.default_rng(2).normal(0.002, 0.01, 120).tolist()
    result = bootstrap_sharpe_ci(rets, iterations=500, seed=9)
    assert result.lower <= result.observed_sharpe <= result.upper
    assert result.confidence == 0.95


def test_bootstrap_flags_a_real_edge_and_a_null_one() -> None:
    rng = np.random.default_rng(4)
    strong = bootstrap_sharpe_ci(rng.normal(0.004, 0.004, 250).tolist(), iterations=500, seed=9)
    noise = bootstrap_sharpe_ci(rng.normal(0.0, 0.01, 250).tolist(), iterations=500, seed=9)
    assert strong.excludes_zero
    assert strong.prob_positive > 0.99
    assert not noise.excludes_zero


def test_wider_confidence_gives_a_wider_interval() -> None:
    rets = np.random.default_rng(6).normal(0.001, 0.01, 100).tolist()
    narrow = bootstrap_sharpe_ci(rets, confidence=0.80, iterations=400, seed=3)
    wide = bootstrap_sharpe_ci(rets, confidence=0.99, iterations=400, seed=3)
    assert (wide.upper - wide.lower) > (narrow.upper - narrow.lower)


def test_bootstrap_rejects_bad_input() -> None:
    with pytest.raises(ValueError, match="at least 2 return"):
        bootstrap_sharpe_ci([0.01])
    with pytest.raises(ValueError, match="confidence must be"):
        bootstrap_sharpe_ci([0.01, 0.02], confidence=1.0)


# --------------------------------------------------------------------------
# probabilistic / deflated Sharpe
# --------------------------------------------------------------------------


def test_psr_at_the_benchmark_is_one_half() -> None:
    assert probabilistic_sharpe_ratio(
        0.1, n_observations=100, benchmark_sharpe=0.1
    ) == pytest.approx(0.5)


def test_psr_rises_with_sample_length() -> None:
    short = probabilistic_sharpe_ratio(0.15, n_observations=30)
    long = probabilistic_sharpe_ratio(0.15, n_observations=500)
    assert long > short


def test_psr_penalises_negative_skew_and_fat_tails() -> None:
    clean = probabilistic_sharpe_ratio(0.2, n_observations=250)
    ugly = probabilistic_sharpe_ratio(0.2, n_observations=250, skew=-1.5, kurt=8.0)
    assert ugly < clean


def test_psr_rejects_too_few_observations() -> None:
    with pytest.raises(ValueError, match="at least 2 observations"):
        probabilistic_sharpe_ratio(0.1, n_observations=1)


def test_expected_max_sharpe_grows_with_trials() -> None:
    assert expected_maximum_sharpe(1, 0.5) == 0.0
    values = [expected_maximum_sharpe(n, 0.5) for n in (10, 100, 320, 1000)]
    assert values == sorted(values)
    assert all(v > 0 for v in values)


def test_expected_max_sharpe_scales_with_dispersion() -> None:
    assert expected_maximum_sharpe(100, 1.0) == pytest.approx(
        2.0 * expected_maximum_sharpe(100, 0.5)
    )
    assert expected_maximum_sharpe(100, 0.0) == 0.0


def test_deflation_demotes_the_luckiest_of_many_worthless_trials() -> None:
    """The headline case: 320 noise trials, and the winner must not survive.

    Undeflated, the best column's Sharpe looks overwhelming. Deflated against
    the Sharpe the best of 320 draws reaches by luck, it must not clear 95%.
    """
    rng = np.random.default_rng(20260831)
    matrix = rng.normal(0.0, 0.01, size=(21, 320))
    col_sharpes = (matrix.mean(axis=0) / matrix.std(axis=0, ddof=1)).tolist()
    best = int(np.argmax(col_sharpes))
    winner = matrix[:, best].tolist()

    deflated = deflated_sharpe_ratio(winner, n_trials=320, trial_sharpes=col_sharpes)
    naive = deflated_sharpe_ratio(winner, n_trials=1, trial_sharpes=col_sharpes)

    assert naive.deflated_sharpe > 0.95  # the number a grid search would report
    assert not deflated.survives_at_95pct  # the number it should report
    assert deflated.deflated_sharpe < naive.deflated_sharpe
    assert deflated.expected_max_sharpe > 0.0
    assert deflated.n_observations == 21


def test_deflation_accepts_an_explicit_dispersion() -> None:
    rets = np.random.default_rng(8).normal(0.001, 0.01, 60).tolist()
    a = deflated_sharpe_ratio(rets, n_trials=50, trial_sharpe_std=0.4)
    b = deflated_sharpe_ratio(rets, n_trials=50, trial_sharpes=[0.1, 0.2, 0.9])
    assert a.trial_sharpe_std == pytest.approx(0.4)
    assert b.trial_sharpe_std == pytest.approx(0.435889894)
    assert a.expected_max_sharpe != b.expected_max_sharpe


def test_explicit_dispersion_overrides_the_sampled_one() -> None:
    rets = np.random.default_rng(8).normal(0.001, 0.01, 60).tolist()
    result = deflated_sharpe_ratio(
        rets, n_trials=50, trial_sharpes=[0.1, 0.2, 0.9], trial_sharpe_std=0.4
    )
    assert result.trial_sharpe_std == pytest.approx(0.4)


def test_deflation_requires_a_dispersion_source() -> None:
    with pytest.raises(ValueError, match="trial_sharpes or trial_sharpe_std"):
        deflated_sharpe_ratio([0.01, 0.02, 0.03], n_trials=10)


def test_deflated_result_to_dict_is_json_serialisable() -> None:
    rets = np.random.default_rng(9).normal(0.001, 0.01, 40).tolist()
    payload = deflated_sharpe_ratio(rets, n_trials=20, trial_sharpe_std=0.3).to_dict()
    json.dumps(payload)
    assert payload["n_trials"] == 20


# --------------------------------------------------------------------------
# Benjamini-Hochberg
# --------------------------------------------------------------------------


def test_bh_matches_the_textbook_example() -> None:
    """Benjamini & Hochberg (1995) worked example: 2 of 10 survive at 0.05."""
    p = [0.001, 0.008, 0.039, 0.041, 0.042, 0.060, 0.074, 0.205, 0.212, 0.216]
    result = benjamini_hochberg(p, alpha=0.05)
    assert result.n_rejected == 2
    assert result.rejected == [0, 1]
    assert result.threshold == pytest.approx(0.01)


def test_bh_is_less_conservative_than_bonferroni() -> None:
    p = [0.001, 0.008, 0.02, 0.03, 0.04] + [0.5] * 15
    bh = benjamini_hochberg(p, alpha=0.05)
    bonferroni = sum(1 for x in p if x <= 0.05 / len(p))
    assert bh.n_rejected >= bonferroni


def test_bh_adjusted_p_values_are_monotone_and_bounded() -> None:
    p = [0.001, 0.04, 0.03, 0.9, 0.2, 0.02]
    result = benjamini_hochberg(p)
    order = sorted(range(len(p)), key=lambda i: p[i])
    adjusted_in_rank_order = [result.adjusted_p_values[i] for i in order]
    assert adjusted_in_rank_order == sorted(adjusted_in_rank_order)
    assert all(0.0 <= x <= 1.0 for x in result.adjusted_p_values)
    assert all(a >= b for a, b in zip(result.adjusted_p_values, p))


def test_bh_rejects_nothing_when_everything_is_noise() -> None:
    assert benjamini_hochberg([0.4, 0.6, 0.8, 0.95]).n_rejected == 0


def test_bh_rejects_bad_input() -> None:
    with pytest.raises(ValueError, match="at least 1 p-value"):
        benjamini_hochberg([])
    with pytest.raises(ValueError, match=r"\[0, 1\]"):
        benjamini_hochberg([0.5, 1.7])
    with pytest.raises(ValueError, match="alpha must be"):
        benjamini_hochberg([0.5], alpha=0.0)


# --------------------------------------------------------------------------
# PBO / CSCV
# --------------------------------------------------------------------------


def test_pbo_is_high_on_pure_noise() -> None:
    matrix = np.random.default_rng(20260831).normal(0.0, 0.01, size=(21, 320))
    result = probability_of_backtest_overfitting(matrix, n_partitions=8)
    assert result.pbo > 0.5
    assert result.overfit
    assert result.n_splits == 70  # C(8, 4)


def test_pbo_is_low_when_one_trial_has_a_real_edge() -> None:
    rng = np.random.default_rng(5)
    matrix = rng.normal(0.0, 0.01, size=(40, 20))
    matrix[:, 7] += 0.02  # a genuinely superior column
    result = probability_of_backtest_overfitting(matrix, n_partitions=8)
    assert result.pbo < 0.5
    assert not result.overfit
    assert result.median_oos_rank > 0.9


def test_pbo_split_count_follows_the_partition_count() -> None:
    matrix = np.random.default_rng(1).normal(0.0, 0.01, size=(60, 6))
    assert probability_of_backtest_overfitting(matrix, n_partitions=6).n_splits == 20
    assert probability_of_backtest_overfitting(matrix, n_partitions=10).n_splits == 252


def test_pbo_rejects_bad_input() -> None:
    matrix = np.random.default_rng(1).normal(0.0, 0.01, size=(40, 5))
    with pytest.raises(ValueError, match="even number"):
        probability_of_backtest_overfitting(matrix, n_partitions=7)
    with pytest.raises(ValueError, match="at least 2 trials"):
        probability_of_backtest_overfitting(matrix[:, :1])
    with pytest.raises(ValueError, match="at least 8 observations"):
        probability_of_backtest_overfitting(matrix[:4, :], n_partitions=8)


# --------------------------------------------------------------------------
# walk-forward embargo
# --------------------------------------------------------------------------


def test_default_embargo_preserves_the_phase08_schedule() -> None:
    """The documented default must not change any existing result."""
    windows = define_walk_windows(datetime(2026, 7, 1), datetime(2026, 7, 31))
    days = [(w[1].day, w[2].day, w[3].day) for w in windows]
    assert days == [(15, 16, 21), (20, 21, 26), (25, 26, 31)]
    assert DEFAULT_EMBARGO_DAYS == 1


def test_embargo_widens_the_gap_between_train_and_test() -> None:
    for embargo in (0, 1, 3, 5):
        windows = define_walk_windows(
            datetime(2026, 7, 1), datetime(2026, 7, 31), embargo_days=embargo
        )
        for _, train_end, test_start, _ in windows:
            assert (test_start - train_end).days == embargo


def test_zero_embargo_makes_test_start_at_train_end() -> None:
    windows = define_walk_windows(datetime(2026, 7, 1), datetime(2026, 7, 31), embargo_days=0)
    assert all(w[1] == w[2] for w in windows)


def test_embargo_never_yields_an_empty_test_window() -> None:
    windows = define_walk_windows(datetime(2026, 7, 1), datetime(2026, 7, 31), embargo_days=30)
    assert all(w[2] < w[3] for w in windows)


def test_negative_embargo_is_rejected() -> None:
    with pytest.raises(ValueError, match="embargo_days must be >= 0"):
        define_walk_windows(datetime(2026, 7, 1), datetime(2026, 7, 31), embargo_days=-1)


# --------------------------------------------------------------------------
# run card
# --------------------------------------------------------------------------


def test_config_hash_ignores_key_order() -> None:
    a = {"fast_ema": 9, "slow_ema": 15, "angle_threshold": 30.0}
    b = {"angle_threshold": 30.0, "slow_ema": 15, "fast_ema": 9}
    assert hash_mapping(a) == hash_mapping(b)
    assert canonical_json(a) == canonical_json(b)


def test_config_hash_changes_with_the_config() -> None:
    base = {"fast_ema": 9, "slow_ema": 15}
    assert hash_mapping(base) != hash_mapping({"fast_ema": 9, "slow_ema": 21})


def test_canonical_json_replaces_non_finite_floats() -> None:
    """NaN and Infinity are not valid JSON; a card must stay re-readable."""
    text = canonical_json({"sharpe": float("nan"), "calmar": float("inf")})
    assert json.loads(text) == {"sharpe": None, "calmar": None}


def test_run_card_records_artifact_digests(tmp_path) -> None:
    (tmp_path / "trades.csv").write_text("a,b\n1,2\n", encoding="utf-8")
    (tmp_path / "nested").mkdir()
    (tmp_path / "nested" / "equity.csv").write_text("x\n1\n", encoding="utf-8")

    card = write_run_card(
        tmp_path,
        run_id="RC-0001",
        config={"fast_ema": 9, "slow_ema": 15},
        metrics={"net_pnl": 12345.6, "sharpe": 1.4},
        notes=["seeded run"],
    )

    paths = [row["path"] for row in card["artifacts"]]
    assert paths == ["nested/equity.csv", "trades.csv"]
    assert all(len(row["sha256"]) == 64 for row in card["artifacts"])
    assert (tmp_path / "run_card.json").exists()
    assert (tmp_path / "run_card.md").exists()

    # The card must never hash itself.
    assert "run_card.json" not in paths
    assert "run_card.md" not in paths


def test_run_card_json_round_trips(tmp_path) -> None:
    (tmp_path / "out.csv").write_text("x\n1\n", encoding="utf-8")
    card = write_run_card(
        tmp_path, run_id="RC-0002", config={"a": 1}, metrics={"sharpe": float("nan")}
    )
    reloaded = json.loads((tmp_path / "run_card.json").read_text(encoding="utf-8"))
    assert reloaded["config_hash"] == card["config_hash"]
    assert reloaded["metrics"]["sharpe"] is None


def test_verify_detects_a_tampered_artifact(tmp_path) -> None:
    target = tmp_path / "trades.csv"
    target.write_text("a,b\n1,2\n", encoding="utf-8")
    write_run_card(tmp_path, run_id="RC-0003", config={"a": 1})

    assert verify_run_card(tmp_path)["ok"] is True

    target.write_text("a,b\n9,9\n", encoding="utf-8")
    report = verify_run_card(tmp_path)
    assert report["ok"] is False
    assert report["mismatched"] == ["trades.csv"]


def test_verify_detects_missing_and_unexpected_files(tmp_path) -> None:
    (tmp_path / "trades.csv").write_text("a\n1\n", encoding="utf-8")
    write_run_card(tmp_path, run_id="RC-0004", config={"a": 1})

    (tmp_path / "trades.csv").unlink()
    (tmp_path / "surprise.csv").write_text("z\n", encoding="utf-8")

    report = verify_run_card(tmp_path)
    assert report["ok"] is False
    assert report["missing"] == ["trades.csv"]
    assert report["unexpected"] == ["surprise.csv"]


def test_verify_requires_a_card(tmp_path) -> None:
    with pytest.raises(FileNotFoundError):
        verify_run_card(tmp_path)


def test_run_card_markdown_carries_the_validation_verdicts() -> None:
    rets = np.random.default_rng(12).normal(0.001, 0.01, 60).tolist()
    card = build_run_card(
        run_id="RC-0005",
        config={"fast_ema": 9, "slow_ema": 15},
        metrics={"net_pnl": 100.0, "sharpe": 1.2},
        validation={
            "bootstrap": bootstrap_sharpe_ci(rets, iterations=100, seed=1).to_dict(),
            "deflated_sharpe": deflated_sharpe_ratio(
                rets, n_trials=320, trial_sharpe_std=0.4
            ).to_dict(),
        },
    )
    text = render_run_card_markdown(card)
    assert "# Run card — RC-0005" in text
    assert card["config_hash"] in text
    assert "Statistical validation" in text
    assert "deflated_sharpe" in text
    assert "n_trials: 320" in text


# --------------------------------------------------------------------------
# validate_parameter_search (integration)
# --------------------------------------------------------------------------


TINY_GRID = {
    "fast_ema": (5, 9),
    "slow_ema": (15, 21),
    "angle_threshold": (20.0, 30.0),
    "angle_lookback": (1, 2),
}


def _month_candles(days: int = 31, bars_per_day: int = 12) -> pl.DataFrame:
    """Synthetic NIFTY-like bars: a slow sine plus drift, 12 bars per day."""
    rows = []
    for day in range(1, days + 1):
        for b in range(bars_per_day):
            i = (day - 1) * bars_per_day + b
            price = 22000.0 + 300.0 * math.sin(i / 25.0) + i * 0.4
            rows.append(
                {
                    "timestamp": datetime(2026, 7, day, 9 + b // 2, 15 if b % 2 else 0),
                    "open": price,
                    "high": price + 8,
                    "low": price - 8,
                    "close": price + 2,
                }
            )
    return pl.DataFrame(rows, schema_overrides={"timestamp": pl.Datetime("ms")})


def test_validation_runs_every_test_end_to_end() -> None:
    report = validate_parameter_search(_month_candles(), grid=TINY_GRID, iterations=200, seed=7)
    assert report.n_trials == 16  # 2x2x2x2, all fast < slow
    assert report.deflated is not None
    assert report.bootstrap is not None
    assert report.permutation is not None
    assert report.pbo is not None
    assert report.skipped == {}
    assert set(report.best_params) == {
        "fast_ema",
        "slow_ema",
        "angle_threshold",
        "angle_lookback",
    }


def test_trial_sharpes_are_per_period_not_annualised() -> None:
    """The wiring hazard this module exists to prevent.

    ``parameter_grid_search`` reports an ANNUALISED Sharpe; the deflated
    Sharpe is defined on per-period ones. If the annualised column leaked in,
    the trial dispersion -- and so the luck benchmark -- would be inflated by
    roughly sqrt(252).
    """
    report = validate_parameter_search(_month_candles(), grid=TINY_GRID, iterations=100, seed=7)
    annualised_best = abs(float(report.best_metrics["sharpe"]))
    per_period = abs(report.deflated["observed_sharpe"])
    assert per_period < annualised_best
    assert per_period == pytest.approx(annualised_best / math.sqrt(252.0), rel=1e-6)


def test_selection_metric_drives_the_winner() -> None:
    candles = _month_candles()
    by_pnl = validate_parameter_search(
        candles, grid=TINY_GRID, iterations=50, seed=7, select_by="net_pnl"
    )
    by_trades = validate_parameter_search(
        candles, grid=TINY_GRID, iterations=50, seed=7, select_by="total_trades"
    )
    assert by_pnl.best_metrics["net_pnl"] >= by_trades.best_metrics["net_pnl"]
    assert by_trades.best_metrics["total_trades"] >= by_pnl.best_metrics["total_trades"]


def test_short_window_skips_pbo_and_is_not_credible() -> None:
    """A skipped test must never be read as a passed one."""
    report = validate_parameter_search(
        _month_candles(days=6), grid=TINY_GRID, iterations=50, seed=7
    )
    assert "pbo" in report.skipped
    assert report.pbo is None
    assert not report.credible


def test_validation_is_reproducible() -> None:
    candles = _month_candles()
    a = validate_parameter_search(candles, grid=TINY_GRID, iterations=100, seed=3)
    b = validate_parameter_search(candles, grid=TINY_GRID, iterations=100, seed=3)
    assert a.to_dict() == b.to_dict()


def test_validation_to_dict_is_json_serialisable() -> None:
    report = validate_parameter_search(_month_candles(), grid=TINY_GRID, iterations=50, seed=7)
    payload = json.dumps(report.to_dict())
    assert "deflated_sharpe" in payload
    assert isinstance(report.summary_lines(), list)
    assert any("VERDICT" in line for line in report.summary_lines())


def test_empty_grid_is_rejected() -> None:
    with pytest.raises(ValueError, match="no valid combinations"):
        validate_parameter_search(
            _month_candles(days=6),
            grid={
                "fast_ema": (21,),
                "slow_ema": (15,),
                "angle_threshold": (20.0,),
                "angle_lookback": (1,),
            },
        )


def test_aligned_matrix_uses_only_shared_dates() -> None:
    """Trials warm up over different bar counts, so alignment is by date."""
    a = GridResult(params={}, metrics={}, returns_by_date={"d1": 0.1, "d2": 0.2})
    b = GridResult(params={}, metrics={}, returns_by_date={"d2": 0.3, "d3": 0.4})
    matrix, dates = _aligned_matrix([a, b])
    assert dates == ["d2"]
    assert matrix.tolist() == [[0.2, 0.3]]


# Realistically shaped verdict payloads: ``summary_lines`` renders every key
# a real ``to_dict()`` carries, so stubs must carry them too.
_DEFLATED_OK = {
    "survives_at_95pct": True,
    "deflated_sharpe": 0.98,
    "observed_sharpe": 0.6,
    "expected_max_sharpe": 0.35,
}
_BOOTSTRAP_OK = {"excludes_zero": True, "ci_lower": 0.8, "ci_upper": 2.4}
_PBO_OK = {"overfit": False, "pbo": 0.1, "n_splits": 70}


def test_unfavourable_permutation_does_not_change_the_verdict() -> None:
    """The permutation test is informational, not a gate.

    It describes the shape of the equity path, not whether an edge exists, so
    a strategy whose losses happened to cluster must not be marked uncredible
    on that basis alone. Pinned because ``credible`` reads three fields and
    deliberately not this one.
    """
    favourable = SearchValidation(
        n_trials=16,
        best_params={"fast_ema": 9},
        best_metrics={},
        deflated=_DEFLATED_OK,
        bootstrap=_BOOTSTRAP_OK,
        pbo=_PBO_OK,
        permutation={"statistic": "max_drawdown_pct", "p_value": 0.01},
    )
    unfavourable = replace(
        favourable,
        permutation={"statistic": "max_drawdown_pct", "p_value": 1.0},
    )
    assert favourable.credible
    assert unfavourable.credible

    text = "\n".join(unfavourable.summary_lines())
    assert "informational" in text
    assert "does not gate the verdict" in text


@pytest.mark.parametrize(
    "field_name, unfavourable",
    [
        ("deflated", {**_DEFLATED_OK, "survives_at_95pct": False}),
        ("bootstrap", {**_BOOTSTRAP_OK, "excludes_zero": False}),
        ("pbo", {**_PBO_OK, "overfit": True}),
    ],
)
def test_each_gating_test_can_veto_the_verdict(field_name, unfavourable) -> None:
    base = SearchValidation(
        n_trials=16,
        best_params={},
        best_metrics={},
        deflated=_DEFLATED_OK,
        bootstrap=_BOOTSTRAP_OK,
        pbo=_PBO_OK,
    )
    assert base.credible
    assert not replace(base, **{field_name: unfavourable}).credible


def test_unknown_selection_metric_is_rejected() -> None:
    """A typo must fail loudly, not deflate an arbitrary winner."""
    with pytest.raises(ValueError, match="not a computed metric"):
        validate_parameter_search(
            _month_candles(days=6),
            grid=TINY_GRID,
            iterations=20,
            select_by="net_pnl_typo",
        )
