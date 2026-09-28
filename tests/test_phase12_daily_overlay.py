"""Phase 12: low-turnover daily overlays (campaign C2026-09-LOWTURN).

The properties worth testing here are the ones that would silently
invalidate the campaign's result rather than raise: a one-bar look-ahead,
a stale STT rate, carry that skips weekends, and a rebalance band that
does not actually suppress turnover.
"""

from __future__ import annotations

from datetime import date, timedelta

import numpy as np
import polars as pl
import pytest

from quant.research.daily_overlay import (
    STT_CHANGE,
    CostModel,
    RunConfig,
    _banded,
    add_features,
    backtest,
    block_bootstrap_ci,
    expo_buy_hold,
    expo_sma200,
    metrics,
)


def _frame(closes: list[float], start: date = date(2024, 1, 1)) -> pl.DataFrame:
    """Consecutive-calendar-day frame (so carry is 1 day per step)."""
    days = [start + timedelta(days=i) for i in range(len(closes))]
    return add_features(
        pl.DataFrame(
            {
                "d": days,
                "open": closes,
                "high": closes,
                "low": closes,
                "close": closes,
            }
        )
    )


FREE = RunConfig(
    r_minus_q=0.0,
    monthly_roll=False,
    costs=CostModel(
        exchange_rate=0.0,
        sebi_rate=0.0,
        stamp_rate=0.0,
        gst_rate=0.0,
        brokerage_flat=0.0,
        slippage_ticks=0.0,
        stt_override=0.0,
    ),
)


class TestNoLookAhead:
    def test_exposure_earns_the_following_days_return(self) -> None:
        # Flat, then a +10% jump on day 2 (index 2), then flat.
        f = _frame([100.0, 100.0, 110.0, 110.0, 110.0])
        # Exposure set ONLY on the jump day's close. It must earn day 3's
        # return (0%), never the jump it was set on.
        e = np.array([0.0, 0.0, 1.0, 0.0, 0.0])
        bt = backtest(f, e, FREE)
        assert bt["net_ret"].sum() == pytest.approx(0.0, abs=1e-12)

    def test_exposure_set_the_day_before_captures_the_jump(self) -> None:
        f = _frame([100.0, 100.0, 110.0, 110.0, 110.0])
        e = np.array([0.0, 1.0, 0.0, 0.0, 0.0])  # set at close of day 1
        bt = backtest(f, e, FREE)
        assert bt["net_ret"].sum() == pytest.approx(0.10, rel=1e-9)

    def test_buy_hold_with_no_friction_equals_index_return(self) -> None:
        closes = [100.0, 101.0, 99.0, 104.0, 103.0]
        f = _frame(closes)
        bt = backtest(f, expo_buy_hold(f), FREE)
        compounded = float(np.prod(1.0 + bt["net_ret"].to_numpy()))
        assert compounded == pytest.approx(closes[-1] / closes[0], rel=1e-9)

    def test_sma200_signal_uses_no_future_close(self) -> None:
        """Truncating the series must not change earlier exposures."""
        rng = np.random.default_rng(0)
        closes = list(100.0 * np.cumprod(1.0 + rng.normal(0, 0.01, 400)))
        full = expo_sma200(_frame(closes))
        cut = expo_sma200(_frame(closes[:300]))
        assert np.allclose(full[:300], cut, equal_nan=True)


class TestCostModel:
    def test_stt_rate_changes_on_2024_10_01(self) -> None:
        c = CostModel()
        # 0.0125% -> 0.02% is +0.75 bps of STT on the sell leg
        stt_jump = c.stt_rate(STT_CHANGE) - c.stt_rate(STT_CHANGE - timedelta(days=1))
        assert stt_jump * 1e4 == pytest.approx(0.75, abs=1e-9)
        # the exchange charge was cut the same day (0.0019% -> 0.00173%), so the
        # whole sell leg rises by a little less than the STT alone
        leg_jump = c.leg_bps(side="sell", on=STT_CHANGE) - c.leg_bps(
            side="sell", on=STT_CHANGE - timedelta(days=1)
        )
        assert 0.70 < leg_jump < 0.75

    def test_stt_applies_to_sell_leg_only(self) -> None:
        c = CostModel()
        buy = c.leg_bps(side="buy", on=date(2025, 1, 1))
        sell = c.leg_bps(side="sell", on=date(2025, 1, 1))
        assert sell > buy
        # stamp duty is the buy-only offset; STT dominates
        # STT 0.02% on the sell leg vs futures stamp duty 0.002% on the buy leg
        assert sell - buy == pytest.approx(0.0002 * 1e4 - 0.00002 * 1e4, abs=1e-6)

    def test_stt_rises_to_five_bps_on_2026_04_01(self) -> None:
        c = CostModel()
        before = c.leg_bps(side="sell", on=date(2026, 3, 31))
        after = c.leg_bps(side="sell", on=date(2026, 4, 1))
        assert after - before == pytest.approx(3.0, abs=1e-6)  # 0.02% -> 0.05%

    def test_stt_was_one_bp_before_april_2023(self) -> None:
        c = CostModel()
        assert c.stt_rate(date(2022, 6, 1)) == pytest.approx(0.0001)

    def test_round_trip_is_about_three_bps(self) -> None:
        rt = CostModel().round_trip_bps(date(2025, 1, 1))
        assert 3.0 < rt < 4.0, rt

    def test_no_cost_when_exposure_unchanged(self) -> None:
        f = _frame([100.0] * 10)
        bt = backtest(f, np.ones(10), RunConfig(r_minus_q=0.0, monthly_roll=False))
        # one entry cost on day 0, nothing after
        assert bt["tc"][0] > 0
        assert bt["tc"][1:].sum() == pytest.approx(0.0, abs=1e-15)


class TestCarry:
    def test_carry_counts_calendar_days_not_sessions(self) -> None:
        """A Fri -> Mon hold must be charged 3 days, not 1."""
        f = add_features(
            pl.DataFrame(
                {
                    "d": [date(2025, 5, 9), date(2025, 5, 12)],  # Fri, Mon
                    "open": [100.0, 100.0],
                    "high": [100.0, 100.0],
                    "low": [100.0, 100.0],
                    "close": [100.0, 100.0],
                }
            )
        )
        cfg = RunConfig(monthly_roll=False)
        bt = backtest(f, np.ones(2), cfg)
        expected = cfg.r_minus_q / 365.0 * 3
        assert bt["carry"][1] == pytest.approx(expected, rel=1e-12)

    def test_carry_only_charged_while_invested(self) -> None:
        f = _frame([100.0] * 6)
        cfg = RunConfig(monthly_roll=False)
        flat = backtest(f, np.zeros(6), cfg)
        assert flat["carry"].sum() == pytest.approx(0.0, abs=1e-15)


class TestBandedRebalancing:
    def test_band_suppresses_small_moves(self) -> None:
        raw = np.array([1.0, 1.1, 1.15, 1.2, 1.0])
        out = _banded(raw, band=0.25)
        assert np.allclose(out, 1.0)  # nothing moved more than the band

    def test_band_admits_a_large_move(self) -> None:
        out = _banded(np.array([0.0, 1.0]), band=0.25)
        assert out[1] == pytest.approx(1.0)

    def test_band_lowers_turnover_versus_unbanded(self) -> None:
        rng = np.random.default_rng(3)
        raw = np.clip(rng.normal(0.6, 0.15, 500), 0, 1)
        t_raw = np.abs(np.diff(raw, prepend=0.0)).sum()
        t_band = np.abs(np.diff(_banded(raw), prepend=0.0)).sum()
        assert t_band < t_raw / 2


class TestInference:
    def test_bootstrap_ci_brackets_the_point_estimate(self) -> None:
        rng = np.random.default_rng(11)
        diff = rng.normal(0.0004, 0.01, 1000)
        ci = block_bootstrap_ci(diff, n_boot=2000)
        assert ci["mean_lo_bps"] < ci["mean_bps"] < ci["mean_hi_bps"]

    def test_bootstrap_detects_a_clear_positive_mean(self) -> None:
        rng = np.random.default_rng(12)
        ci = block_bootstrap_ci(rng.normal(0.004, 0.005, 1000), n_boot=2000)
        assert ci["excludes_zero"] is True

    def test_bootstrap_does_not_claim_an_edge_from_noise(self) -> None:
        rng = np.random.default_rng(13)
        ci = block_bootstrap_ci(rng.normal(0.0, 0.01, 1000), n_boot=2000)
        assert ci["excludes_zero"] is False


class TestMetrics:
    def test_max_drawdown_is_negative_and_bounded(self) -> None:
        f = _frame([100.0, 120.0, 60.0, 80.0])
        m = metrics(backtest(f, expo_buy_hold(f), FREE))
        assert -1.0 < m["max_dd"] < 0.0

    def test_friction_multiple_increases_costs(self) -> None:
        f = _frame([100.0 + i for i in range(30)])
        e = np.tile([0.0, 1.0], 15)
        base = backtest(f, e, RunConfig()).select(pl.col("tc").sum()).item()
        stressed = (
            backtest(f, e, RunConfig(friction_multiple=1.5)).select(pl.col("tc").sum()).item()
        )
        assert stressed == pytest.approx(1.5 * base, rel=1e-9)
