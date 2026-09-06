"""Phase 11: canonicalisation for the ema_ha strategy params and the
scale-out exit ladder -- what keeps --resume dedup correct and
cumulative_trial_count (the n_trials the deflated Sharpe is penalized
against) from being inflated by behaviourally-identical trials."""

from __future__ import annotations

from quant.research.sampling import canonical_exits, canonical_params
from quant.research.sweep import Trial


def test_wick_ratio_pruned_when_pattern_set_is_doji_only():
    with_high_wick = canonical_params(
        "ema_ha", {"pattern_set": "doji_only", "wick_ratio": 0.55, "fast_ema": 9}
    )
    with_low_wick = canonical_params(
        "ema_ha", {"pattern_set": "doji_only", "wick_ratio": 0.40, "fast_ema": 9}
    )
    assert with_high_wick == with_low_wick
    assert "wick_ratio" not in with_high_wick


def test_wick_ratio_kept_when_pattern_set_is_directional():
    out = canonical_params(
        "ema_ha", {"pattern_set": "directional", "wick_ratio": 0.55, "fast_ema": 9}
    )
    assert out["wick_ratio"] == 0.55


def test_canonical_exits_quantises_equivalent_fractions_to_the_same_lots():
    exits_a = {"scale_out": [{"at_r": 1.0, "fraction": 0.30}], "trail_mode": "none"}
    exits_b = {"scale_out": [{"at_r": 1.0, "fraction": 0.33}], "trail_mode": "none"}
    canon_a = canonical_exits(exits_a, position_size=4)
    canon_b = canonical_exits(exits_b, position_size=4)
    # Both floor(fraction * 4) == 1 lot -- behaviourally identical.
    assert canon_a == canon_b


def test_canonical_exits_distinguishes_fractions_landing_on_different_lots():
    exits_a = {"scale_out": [{"at_r": 1.0, "fraction": 0.20}], "trail_mode": "none"}
    exits_b = {"scale_out": [{"at_r": 1.0, "fraction": 0.60}], "trail_mode": "none"}
    canon_a = canonical_exits(exits_a, position_size=4)
    canon_b = canonical_exits(exits_b, position_size=4)
    assert canon_a != canon_b  # 0 lots vs 2 lots


def test_canonical_exits_prunes_trail_buffer_when_trail_mode_none():
    out = canonical_exits({"trail_mode": "none", "trail_buffer_atr": 0.5})
    assert "trail_buffer_atr" not in out


def test_canonical_exits_keeps_trail_buffer_for_prev_candle_extreme():
    out = canonical_exits({"trail_mode": "prev_candle_extreme", "trail_buffer_atr": 0.5})
    assert out["trail_buffer_atr"] == 0.5


def test_param_hash_differs_by_position_size():
    kwargs = dict(
        campaign_id="T", round=1, strategy_id="ema_ha", strategy_version="v1",
        params={"fast_ema": 9}, exits={"stop_mode": "signal"}, symbol="NIFTY",
        price_source="index_spot_proxy", timeframe="15m", split="train",
        candles_path="x.parquet", window_start=None, window_end=None,
        lot_size=65, tick_size_rupees=0.10,
    )
    t1 = Trial(**kwargs, position_size=1)
    t4 = Trial(**kwargs, position_size=4)
    assert t1.param_hash != t4.param_hash
