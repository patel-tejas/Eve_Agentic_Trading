"""Phase 09: staged-search sampling (canonicalization, LHS, refinement)."""

from __future__ import annotations

from quant.research.sampling import (
    canonical_params,
    dedupe_by_effect,
    full_combinations,
    local_refinement,
    sample_combinations,
)


def test_canonical_params_drops_angle_fields_under_pure_crossover():
    params = {
        "signal_mode": "crossover",
        "angle_mode": "atr_normalized",
        "slope_threshold_atr": 0.3,
        "angle_lookback": 5,
    }
    out = canonical_params("ema", params)
    assert "angle_mode" not in out
    assert "slope_threshold_atr" not in out
    assert "angle_lookback" not in out


def test_canonical_params_drops_lookback_when_threshold_zero():
    a = canonical_params(
        "ema",
        {
            "signal_mode": "crossover_and_angle",
            "angle_mode": "atr_normalized",
            "slope_threshold_atr": 0.0,
            "angle_lookback": 1,
        },
    )
    b = canonical_params(
        "ema",
        {
            "signal_mode": "crossover_and_angle",
            "angle_mode": "atr_normalized",
            "slope_threshold_atr": 0.0,
            "angle_lookback": 5,
        },
    )
    assert a == b  # lookback dropped -> both collapse to the same config


def test_canonical_params_keeps_lookback_when_threshold_nonzero():
    a = canonical_params(
        "ema",
        {
            "signal_mode": "crossover_and_angle",
            "angle_mode": "atr_normalized",
            "slope_threshold_atr": 0.2,
            "angle_lookback": 1,
        },
    )
    b = canonical_params(
        "ema",
        {
            "signal_mode": "crossover_and_angle",
            "angle_mode": "atr_normalized",
            "slope_threshold_atr": 0.2,
            "angle_lookback": 5,
        },
    )
    assert a != b


def test_canonical_params_drops_exit_fields_when_off():
    out = canonical_params(
        "ema",
        {
            "stop_mode": "none",
            "stop_atr_mult": 2.0,
            "target_mode": "r_multiple",
            "target_r_multiple": 3.0,
            "trail_mode": "none",
            "trail_atr_mult": 1.5,
        },
    )
    assert "stop_atr_mult" not in out
    # target_mode="r_multiple" with stop_mode="none" is inert -> rewritten
    assert out["target_mode"] == "none"
    assert "target_r_multiple" not in out
    assert "trail_atr_mult" not in out


def test_dedupe_by_effect_collapses_duplicates():
    combos = [
        {"signal_mode": "crossover", "angle_lookback": 1},
        {"signal_mode": "crossover", "angle_lookback": 5},  # same canonical form
        {
            "signal_mode": "crossover_and_angle",
            "angle_mode": "fixed_scale",
            "angle_threshold": 30.0,
        },
    ]
    deduped = dedupe_by_effect("ema", combos)
    assert len(deduped) == 2
    assert deduped[0] == combos[0]  # first occurrence kept


def test_full_combinations_respects_constraints():
    grid = {"fast_ema": (5, 9, 18), "slow_ema": (15, 21)}
    combos = full_combinations(grid, constraints=[lambda c: c["fast_ema"] < c["slow_ema"]])
    assert all(c["fast_ema"] < c["slow_ema"] for c in combos)
    # (fast=18, slow=15) is the only invalid pair out of 3*2=6
    assert len(combos) == 3 * 2 - 1


def test_sample_combinations_lhs_covers_every_value_reasonably_evenly():
    grid = {"stop_atr_mult": (0.75, 1.0, 1.5, 2.0, 3.0)}
    combos = sample_combinations(grid, n=25, seed=42, method="lhs")
    assert len(combos) == 25
    counts = {}
    for c in combos:
        counts[c["stop_atr_mult"]] = counts.get(c["stop_atr_mult"], 0) + 1
    # 25 samples / 5 values = 5 each; LHS should keep every value's count
    # reasonably close to that, unlike plain random which can skip values.
    assert set(counts) == set(grid["stop_atr_mult"])
    assert all(3 <= v <= 7 for v in counts.values())


def test_sample_combinations_is_deterministic():
    grid = {"a": (1, 2, 3), "b": (10, 20)}
    r1 = sample_combinations(grid, n=10, seed=7, method="lhs")
    r2 = sample_combinations(grid, n=10, seed=7, method="lhs")
    assert r1 == r2


def test_sample_combinations_full_ignores_n():
    grid = {"a": (1, 2), "b": (10, 20)}
    combos = sample_combinations(grid, n=1, seed=0, method="full")
    assert len(combos) == 4


def test_local_refinement_radius_one_bounds():
    grid = {"stop_atr_mult": (0.75, 1.0, 1.5, 2.0, 3.0), "trail_atr_mult": (1.5, 2.5)}
    base = {"stop_atr_mult": 1.5, "trail_atr_mult": 1.5, "other_field": "kept"}
    neighbours = local_refinement(base, grid, radius=1)
    stop_values = {c["stop_atr_mult"] for c in neighbours}
    assert stop_values == {1.0, 1.5, 2.0}  # neighbours of 1.5 in the grid
    assert all(c["other_field"] == "kept" for c in neighbours)


def test_local_refinement_clips_at_grid_edge():
    grid = {"stop_atr_mult": (0.75, 1.0, 1.5, 2.0, 3.0)}
    base = {"stop_atr_mult": 0.75}  # first value -- no room to go lower
    neighbours = local_refinement(base, grid, radius=1)
    stop_values = {c["stop_atr_mult"] for c in neighbours}
    assert stop_values == {0.75, 1.0}  # never extrapolates below the grid
