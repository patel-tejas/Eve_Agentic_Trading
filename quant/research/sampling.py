"""Parameter-space sampling for the Phase 09 staged search.

The new EMA + exits space is ~1.3M cartesian points (Stage 1 entry grid
x Stage 2 exit grid). Nobody runs that; the pattern here is:

    Stage 1 (entry logic)   -- full cartesian, cheap (~575 valid combos)
    Stage 2 (exits)         -- top-K stage-1 winners x LHS-sampled exit grid
    Stage 3 (refinement)    -- +/-1 grid step on the numeric axes around
                                the stage-2 winner

``canonical_params`` exists so trials that differ only in a parameter a
mode switch made INERT (e.g. ``angle_lookback`` when
``slope_threshold_atr == 0.0`` gates everything through regardless of
lookback) collapse to the same canonical config. Two things depend on
this: it stops the sweep spending trials on configs that are really all
identical to "no gate", and it keeps duplicate configs from inflating
the ``n_trials`` that the deflated Sharpe ratio is penalized against.
"""

from __future__ import annotations

import itertools
import math
from collections.abc import Callable, Iterable, Mapping, Sequence
from typing import Any

import numpy as np

Params = dict[str, Any]
Constraint = Callable[[Params], bool]


# ---------------------------------------------------------------------------
# Canonicalization -- collapse configs that differ only in an inert param.
# ---------------------------------------------------------------------------


def canonical_params(strategy_id: str, params: Mapping[str, Any]) -> Params:
    """Return a copy of ``params`` with mode-inert keys dropped.

    Only ``"ema"`` has rules today (the only family whose parameter space
    exists yet); an unknown ``strategy_id`` returns ``params`` unchanged
    rather than raising, so new strategies are safe by default until
    rules are added for them.
    """
    out = dict(params)
    if strategy_id == "ema_ha":
        # wick_ratio/opp_wick_ratio only affect the hammer/inverted-hammer
        # tests -- irrelevant when pattern_set="doji_only" only ever
        # checks ha_is_doji (see quant.strategies.ema_ha_pattern).
        if out.get("pattern_set") == "doji_only":
            out.pop("wick_ratio", None)
            out.pop("opp_wick_ratio", None)
            out.pop("hammer_body_pct", None)
        return out
    if strategy_id != "ema":
        return out

    signal_mode = out.get("signal_mode")
    if signal_mode == "crossover":
        # A pure crossover signal never looks at the angle/slope gate at all.
        for key in (
            "angle_mode",
            "angle_threshold",
            "angle_lookback",
            "angle_scale",
            "atr_period",
            "slope_threshold_atr",
        ):
            out.pop(key, None)
    else:
        angle_mode = out.get("angle_mode", "fixed_scale")
        threshold = (
            out.get("slope_threshold_atr", 0.0)
            if angle_mode == "atr_normalized"
            else out.get("angle_threshold", 0.0)
        )
        if threshold == 0.0:
            # A threshold of exactly zero gates purely on the SIGN of the
            # slope/angle, which for any smooth trend matches the
            # crossover direction almost always -- lookback choice makes
            # no practical difference to which bars pass.
            out.pop("angle_lookback", None)

    stop_mode = out.get("stop_mode", "none")
    if stop_mode == "none":
        for key in ("stop_atr_mult", "stop_points", "stop_pct"):
            out.pop(key, None)

    target_mode = out.get("target_mode", "none")
    if target_mode == "r_multiple" and stop_mode == "none":
        # r_multiple needs a risk distance from the stop; with no stop,
        # risk is None and the target never activates -- same effective
        # config as target_mode="none".
        target_mode = "none"
        out["target_mode"] = "none"
    if target_mode == "none":
        for key in ("target_r_multiple", "target_atr_mult", "target_points"):
            out.pop(key, None)
    elif target_mode != "r_multiple":
        out.pop("target_r_multiple", None)
    if target_mode != "atr":
        out.pop("target_atr_mult", None)
    if target_mode != "points":
        out.pop("target_points", None)

    trail_mode = out.get("trail_mode", "none")
    if trail_mode == "none":
        for key in ("trail_atr_mult", "breakeven_at_r"):
            out.pop(key, None)
    elif trail_mode == "atr":
        out.pop("breakeven_at_r", None)

    return out


def canonical_exits(exits: Mapping[str, Any], *, position_size: int = 1) -> Params:
    """Drop/quantise exit-config keys made inert by another exit setting,
    for the Phase 11 scale-out ladder search (mirrors ``canonical_params``
    above, but operates on the ``ExitConfig`` dict rather than a
    strategy's own params -- the two are always swept independently, see
    ``quant.research.sweep.Trial.exits`` vs ``Trial.params``).

    ``scale_out`` leg fractions are quantised to the ACTUAL lot count
    they resolve to at ``position_size`` (mirroring
    ``quant.backtest.engine``'s ``math.floor(fraction * position_size)``)
    and rewritten as that quantised fraction -- two fractions that floor
    to the same lot count (e.g. 0.30 and 0.33 at position_size=4, both 1
    lot) are behaviourally IDENTICAL trials and must hash the same, or
    ``--resume`` dedup breaks and ``cumulative_trial_count`` (the
    ``n_trials`` the deflated Sharpe is penalized against) is inflated by
    duplicates.
    """
    out = dict(exits)

    trail_mode = out.get("trail_mode", "none")
    if trail_mode == "none":
        for key in ("trail_atr_mult", "breakeven_at_r", "trail_buffer_atr", "trail_after_leg"):
            out.pop(key, None)
    else:
        if trail_mode not in ("atr", "breakeven_then_atr"):
            out.pop("trail_atr_mult", None)
        if trail_mode != "breakeven_then_atr":
            out.pop("breakeven_at_r", None)
        if trail_mode != "prev_candle_extreme":
            out.pop("trail_buffer_atr", None)

    scale_out = out.get("scale_out")
    if scale_out:
        quantised = []
        for leg in scale_out:
            leg_lots = math.floor(leg["fraction"] * position_size + 1e-9)
            quantised.append({"at_r": leg["at_r"], "fraction": leg_lots / position_size})
        out["scale_out"] = tuple(sorted((leg["at_r"], leg["fraction"]) for leg in quantised))
        if out.get("after_leg1_stop") == "breakeven":
            # Only the FIRST leg (by at_r) matters for whether breakeven
            # has anything to arm against; already captured by scale_out
            # itself, nothing further to prune.
            pass
    else:
        out.pop("after_leg1_stop", None)
        out.pop("trail_after_leg", None)

    return out


def dedupe_by_effect(strategy_id: str, combos: Iterable[Params]) -> list[Params]:
    """Drop combos whose CANONICAL form has already been seen.

    The first occurrence (in iteration order) of each canonical form is
    kept, so callers can put their preferred/most-readable variant first.
    """
    seen: set[tuple[tuple[str, Any], ...]] = set()
    out: list[Params] = []
    for combo in combos:
        key = tuple(sorted(canonical_params(strategy_id, combo).items()))
        if key in seen:
            continue
        seen.add(key)
        out.append(combo)
    return out


# ---------------------------------------------------------------------------
# Sampling
# ---------------------------------------------------------------------------


def _apply_constraints(combos: Iterable[Params], constraints: Sequence[Constraint]) -> list[Params]:
    if not constraints:
        return list(combos)
    return [c for c in combos if all(fn(c) for fn in constraints)]


def full_combinations(
    grid: Mapping[str, Sequence[Any]],
    *,
    constraints: Sequence[Constraint] = (),
) -> list[Params]:
    """Cartesian product of ``grid``, filtered by ``constraints``."""
    names = list(grid.keys())
    axis_values = (grid[n] for n in names)
    combos = [dict(zip(names, v, strict=True)) for v in itertools.product(*axis_values)]
    return _apply_constraints(combos, constraints)


def sample_combinations(
    grid: Mapping[str, Sequence[Any]],
    *,
    n: int,
    seed: int,
    method: str = "lhs",
    constraints: Sequence[Constraint] = (),
) -> list[Params]:
    """Deterministically sample ``n`` combinations from a discrete grid.

    ``method="full"`` returns the entire (constraint-filtered) cartesian
    product, ignoring ``n``. ``method="lhs"`` (default) and
    ``"random"`` both use a discrete Latin-hypercube-style construction:
    for each axis, build a value sequence that cycles through the axis's
    OWN possible values as evenly as possible (a fresh independent
    shuffle per axis), so every value appears roughly ``n / len(values)``
    times across the sample -- this is what makes it "Latin hypercube"
    rather than plain independent random sampling, which can (and with
    small ``n`` often does) skip a value on some axis entirely.

    Always deterministic under the same ``(grid, n, seed)`` -- required
    for a reproducible run card.
    """
    if method == "full":
        return full_combinations(grid, constraints=constraints)
    if method not in ("lhs", "random"):
        raise ValueError(f"unknown method {method!r}; expected 'full', 'lhs', or 'random'")

    rng = np.random.default_rng(seed)
    names = list(grid.keys())
    columns: dict[str, list[Any]] = {}
    for name in names:
        values = list(grid[name])
        if method == "lhs":
            reps = -(-n // len(values))  # ceil division
            # `reps` independent shuffles of `values`, concatenated, then
            # take the first n -- guarantees near-even coverage per axis.
            pool: list[Any] = []
            for _ in range(reps):
                shuffled = values.copy()
                rng.shuffle(shuffled)
                pool.extend(shuffled)
            columns[name] = pool[:n]
        else:  # random
            columns[name] = [values[i] for i in rng.integers(0, len(values), size=n)]

    combos = [{name: columns[name][i] for name in names} for i in range(n)]
    return _apply_constraints(combos, constraints)


def local_refinement(
    base_params: Mapping[str, Any],
    grid: Mapping[str, Sequence[Any]],
    *,
    radius: int = 1,
    constraints: Sequence[Constraint] = (),
) -> list[Params]:
    """Neighbours of ``base_params`` within ``radius`` grid steps per axis.

    Only axes present in both ``base_params`` and ``grid`` are varied;
    every other key of ``base_params`` is held fixed. For each such axis,
    the neighbour set is the ``+/-radius`` positions around the base
    value's index in ``grid[axis]`` (clipped to the grid's own range --
    never extrapolated beyond the declared search space). The cartesian
    product of all neighbour sets is returned, so ``radius=1`` over 5
    numeric axes yields at most ``3**5 = 243`` combos, matching the
    Stage-3 budget in the implementation plan.
    """
    axes = [name for name in grid if name in base_params]
    neighbour_sets: dict[str, list[Any]] = {}
    for name in axes:
        values = list(grid[name])
        try:
            idx = values.index(base_params[name])
        except ValueError:
            # base value isn't literally in this grid (e.g. came from a
            # different stage's grid) -- fall back to nearest by value.
            idx = min(range(len(values)), key=lambda i: abs(values[i] - base_params[name]))
        lo, hi = max(0, idx - radius), min(len(values) - 1, idx + radius)
        neighbour_sets[name] = values[lo : hi + 1]

    combos: list[Params] = []
    if not axes:
        return [dict(base_params)]
    for combo_values in itertools.product(*(neighbour_sets[name] for name in axes)):
        candidate = dict(base_params)
        candidate.update(dict(zip(axes, combo_values, strict=True)))
        combos.append(candidate)
    return _apply_constraints(combos, constraints)
