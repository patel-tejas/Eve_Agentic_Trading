"""Bracket exit configuration and intrabar resolution.

Phase 09: the engine previously exited on signal-reversal only (see
``quant.backtest.engine``), which cannot express a stop-loss, a target, a
trailing stop, a time-stop, or an end-of-day square-off -- required by the
re-tuned EMA strategy and by every SMC/ICT strategy, which are all
stop-and-target based.

``ExitConfig()`` with every field at its default is a no-op: no stops, no
targets, no trailing, no time-stop, no EOD square-off. That is what makes
this change backward compatible -- the default reproduces today's
engine behaviour bit-for-bit (see ``tests/test_phase09_exits.py``).

Intrabar precedence (the ``intrabar="conservative"`` convention, the only
mode implemented): within one bar,
    1. gap-through -- if the bar's open already clears a level, fill at
       the open, not at the level itself;
    2. stop-loss, checked against the bar's low (long) / high (short);
    3. take-profit -- checked only if the stop did not already fire.
       If both the stop and the target are inside the same bar, the
       STOP WINS. This is the pessimistic, standard convention and is
       the opposite of what an inflated backtest would assume.
    4. trailing stop -- the trail level used on bar ``i`` is derived
       from bars ``<= i-1`` only, never from bar ``i``'s own high/low.
       Updating the trail from bar ``i``'s own extreme and then testing
       bar ``i``'s low against it is intrabar look-ahead.
    5. time-stop -- exits at the bar's close once ``time_stop_bars``
       bars have elapsed since entry.
    6. end-of-day square-off -- resolved by wall-clock time, never bar
       index (July closes at 15:29/375 bars-a-day, August at
       15:39/385 bars-a-day; an index-based rule would be wrong on
       half the data).

``eod_squareoff`` and bar labelling: ``quant.candles.aggregation`` labels
aggregated bars by their INTERVAL START (``label="left"``), so a 15m
candle stamped 15:15 covers 15:15-15:30 -- it is the LAST bar of the
NSE session, even though its own timestamp is well before 15:30. The
engine's EOD check is ``timestamp.time() >= eod_squareoff``, so on a
15m/5m frame the cutoff must be set at or before that last bar's own
label (e.g. ``"15:15"`` for 15m, not ``"15:20"``) or it will never fire
on aggregated timeframes -- confirmed empirically: cutoff="15:20" never
triggers on 15m July data (last bar is 15:15) and the pre-Phase-09
force-close artifact survives unchanged; cutoff="15:15" does trigger,
and the previously "profitable" 15m B-config (net +Rs 5,737 on the old
lot/tick constants) becomes a NET LOSS of roughly -Rs 11,300 over 8
trades once every multi-day hold is actually flattened daily instead of
riding to the backtest's month boundary.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Literal

StopMode = Literal["none", "atr", "points", "pct", "signal"]
TargetMode = Literal["none", "r_multiple", "atr", "points", "signal"]
TrailMode = Literal["none", "atr", "breakeven_then_atr", "prev_candle_extreme"]
AfterLeg1Stop = Literal["keep", "breakeven"]


@dataclass(frozen=True)
class ScaleLeg:
    """One scale-out leg: sell/cover ``fraction`` of the ORIGINAL position
    once price reaches ``at_r`` (an R-multiple of the entry risk, i.e.
    ``risk = |entry_price - stop_level|`` frozen at entry -- see
    ``quant.backtest.engine._bracket_levels``).

    Plain floats only -- ``ExitConfig`` (and therefore ``Trial``) must
    stay picklable across the Windows ``ProcessPoolExecutor`` spawn
    boundary (see ``quant.research.sweep``).
    """

    at_r: float
    fraction: float

    def __post_init__(self) -> None:
        if self.at_r <= 0:
            raise ValueError(f"ScaleLeg.at_r must be > 0, got {self.at_r!r}")
        if not 0 < self.fraction <= 1:
            raise ValueError(f"ScaleLeg.fraction must be in (0, 1], got {self.fraction!r}")


@dataclass(frozen=True)
class ExitConfig:
    """Bracket exit parameters. All defaults are a no-op (legacy behaviour)."""

    stop_mode: StopMode = "none"
    stop_atr_mult: float = 2.0
    stop_points: float = 0.0
    stop_pct: float = 0.0

    target_mode: TargetMode = "none"
    target_r_multiple: float = 2.0
    target_atr_mult: float = 0.0
    target_points: float = 0.0

    trail_mode: TrailMode = "none"
    trail_atr_mult: float = 2.0
    breakeven_at_r: float = 1.0

    time_stop_bars: int = 0  # 0 = disabled

    session_start: str | None = None  # e.g. "09:15" -- gates NEW entries only
    session_end: str | None = None  # e.g. "15:00" -- gates NEW entries only
    eod_squareoff: str | None = None  # e.g. "15:20" -- force flat, per session

    atr_period: int = 14
    intrabar: Literal["conservative"] = "conservative"

    # Phase 11: partial scale-out ladder. Empty tuple (default) is a
    # no-op -- the position exits 100% on whichever bracket/signal fires
    # first, exactly as before. Legs are checked in ascending ``at_r``
    # order and sized in LOTS (never fractional contracts), so several
    # legs can fill in the same bar if the bar's range reaches more than
    # one level at once.
    scale_out: tuple[ScaleLeg, ...] = ()
    # Once the FIRST leg has filled, optionally move the stop to
    # breakeven (entry price) -- effective from the NEXT bar only, never
    # the bar that filled leg 1 itself (see engine.py's
    # ``_update_trailing_stop``/breakeven handling for why).
    after_leg1_stop: AfterLeg1Stop = "keep"
    # Only start trailing the remainder once this many legs have filled
    # (0 = trail from entry, matching the plain ``trail_mode="atr"``
    # behaviour above). Meaningful only alongside ``scale_out``.
    trail_after_leg: int = 0
    # Used by ``trail_mode="prev_candle_extreme"``: how far below (long)
    # / above (short) the previous bar's low/high the trail sits, in ATR.
    trail_buffer_atr: float = 0.0

    @property
    def enabled(self) -> bool:
        """Whether any bracket mechanism is active (else the engine's legacy
        signal-reversal-only path is used unchanged)."""
        return (
            self.stop_mode != "none"
            or self.target_mode != "none"
            or self.trail_mode != "none"
            or self.time_stop_bars > 0
            or self.eod_squareoff is not None
            or bool(self.scale_out)
        )

    @property
    def needs_atr(self) -> bool:
        return (
            self.stop_mode == "atr"
            or self.target_mode == "atr"
            or self.trail_mode in ("atr", "breakeven_then_atr")
            or (self.trail_mode == "prev_candle_extreme" and self.trail_buffer_atr > 0)
        )

    @property
    def needs_stop_price_column(self) -> bool:
        return self.stop_mode == "signal"

    @property
    def needs_target_price_column(self) -> bool:
        return self.target_mode == "signal"
