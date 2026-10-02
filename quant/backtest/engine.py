"""Backtest event engine.

Phase 05: position state machine (LONG/SHORT/FLAT), signal-at-close ->
execute-at-next-open (no look-ahead), per-trade log and bar-level
mark-to-market equity curve.

Execution rules
- Signals are decided at their bar's close; orders fill at the *next*
  bar's open plus configured slippage.
- FLAT -> BUY is a LONG entry, FLAT -> SELL is a SHORT entry.
- LONG exits on SELL (-> FLAT), SHORT exits on BUY (-> FLAT). Same
  direction signals while open are ignored.
- A position still open at series end is closed at the last close and
  flagged with ``closed_at_end=1``.
- Phase 15: ``EXIT_LONG`` / ``EXIT_SHORT`` / ``EXIT`` only ever flatten the
  matching position and never open one. They let a long-only rule-spec
  strategy say "go flat" without a SELL that would open a short from FLAT.
  No pre-Phase-15 strategy emits them, so legacy runs are unchanged.

Phase 09: optional bracket exits (``BacktestConfig.exits``) and a
contract-aware ``MarketContext`` (``BacktestConfig.market``). Both are
additive and off by default -- ``ExitConfig()`` with every field at its
default reproduces the Phase 05 behaviour bit-for-bit (see
``tests/test_phase09_exits.py``). When ``exits.enabled`` is True, a
bracket exit can fire intrabar (using the bar's high/low); the intrabar
precedence rules are documented in ``quant.backtest.exits``.
Signal-driven entries and reversals still only ever fill at the *next*
bar's open -- bracket exits are the only thing allowed to fill within
the bar it triggers on.

Phase 11: optional partial scale-out ladder (``ExitConfig.scale_out``).
Every exit -- signal reversal, stop, target, trail, time, EOD, and
end-of-data -- is implemented as ONE OR MORE "legs" against a running
``remaining_qty``, consolidated into a SINGLE trades-frame row per
logical trade (never one row per leg -- see the module-level note on
why that distinction matters for every downstream metric). With
``scale_out=()`` (the default), a trade always closes in exactly one
leg, and every field emitted is numerically identical to the pre-Phase-11
single-exit engine -- this equivalence is a regression test, not an
assumption.
"""

from __future__ import annotations

import json
import math
from dataclasses import dataclass, field
from datetime import datetime
from typing import Literal

import polars as pl

from quant.backtest.costs import CostConfig, cost_of_order
from quant.backtest.execution import ExecutionConfig, adjusted_price
from quant.backtest.exits import ExitConfig
from quant.backtest.market import MarketContext
from quant.backtest.metrics import compute_metrics, daily_returns
from quant.candles.session import parse_time
from quant.indicators.atr import add_atr

Position = Literal["FLAT", "LONG", "SHORT"]
ExitReason = Literal["signal", "stop", "target", "trail", "time", "eod", "end_of_data"]


@dataclass(frozen=True)
class BacktestConfig:
    """Full backtest configuration for one run."""

    initial_capital: float = 1_000_000.0
    position_size: int = 1  # lots
    lot_size: int = 50  # NIFTY futures (default kept for existing tests/tools)
    costs: CostConfig = field(default_factory=CostConfig)
    execution: ExecutionConfig = field(default_factory=ExecutionConfig)
    exits: ExitConfig = field(default_factory=ExitConfig)
    market: MarketContext | None = None  # when set, overrides lot_size/tick_size

    @property
    def quantity(self) -> int:
        lot = self.market.lot_size if self.market is not None else self.lot_size
        return self.position_size * lot

    @property
    def lot_count(self) -> int:
        """The contract count of ONE lot -- needed to quantise scale-out
        legs (sized in lots, never fractional contracts)."""
        return self.market.lot_size if self.market is not None else self.lot_size

    @property
    def tick_size(self) -> float:
        if self.market is not None:
            return self.market.tick_size_rupees
        return self.execution.slippage.tick_size


@dataclass(frozen=True)
class BacktestResult:
    """Output of one backtest run: trades, equity curve, metrics."""

    trades: pl.DataFrame
    equity: pl.DataFrame
    metrics: dict[str, float | int | str]
    daily_returns: list[float] = field(default_factory=list)


TRADE_COLUMNS = [
    "trade_id",
    "entry_time",
    "exit_time",
    "direction",
    "entry_price",
    "exit_price",
    "quantity",
    "gross_pnl",
    "costs",
    "net_pnl",
    "holding_periods",
    "closed_at_end",
    # Phase 09 additions -- appended, never inserted, so existing positional
    # indexing (tests/test_phase05_backtest.py) keeps working unchanged.
    "exit_reason",
    "mae",
    "mfe",
    "bars_held",
    "r_multiple",
    # Phase 11 additions -- appended, never inserted. n_legs=1 and a
    # single-entry exit_legs_json for every trade that never used
    # ExitConfig.scale_out (i.e. every pre-Phase-11 trade).
    "n_legs",
    "exit_legs_json",
]

EQUITY_COLUMNS = ["timestamp", "equity", "unrealized", "realized"]


def _bracket_levels(
    *,
    direction: str,
    entry_price: float,
    exits: ExitConfig,
    atr_at_entry: float | None,
    signal_stop: float | None,
    signal_target: float | None,
) -> tuple[float | None, float | None, float | None]:
    """Compute (stop_level, target_level, risk) frozen at entry.

    ``risk`` is the distance from entry to the stop, used for R-multiple
    targets and R-multiple reporting. Never recomputed from later bars.
    """
    sign = 1.0 if direction == "LONG" else -1.0

    stop_level: float | None = None
    if exits.stop_mode == "signal":
        stop_level = signal_stop
    elif exits.stop_mode == "atr" and atr_at_entry is not None:
        stop_level = entry_price - sign * exits.stop_atr_mult * atr_at_entry
    elif exits.stop_mode == "points" and exits.stop_points > 0:
        stop_level = entry_price - sign * exits.stop_points
    elif exits.stop_mode == "pct" and exits.stop_pct > 0:
        stop_level = entry_price * (1 - sign * exits.stop_pct)

    risk = abs(entry_price - stop_level) if stop_level is not None else None

    target_level: float | None = None
    if exits.target_mode == "signal":
        target_level = signal_target
    elif exits.target_mode == "r_multiple" and risk is not None:
        target_level = entry_price + sign * exits.target_r_multiple * risk
    elif exits.target_mode == "atr" and atr_at_entry is not None:
        target_level = entry_price + sign * exits.target_atr_mult * atr_at_entry
    elif exits.target_mode == "points" and exits.target_points > 0:
        target_level = entry_price + sign * exits.target_points
    elif exits.target_mode == "pct" and exits.target_pct > 0:
        target_level = entry_price * (1 + sign * exits.target_pct)

    return stop_level, target_level, risk


def _bracket_hit(
    *,
    direction: str,
    sl_level: float | None,
    tp_level: float | None,
    o: float,
    h: float,
    low: float,
) -> tuple[str | None, float | None]:
    """One bar's conservative intrabar resolution.

    Order: gap-through (fills at the open) -> stop (checked first, wins
    ties with the target) -> target. Returns (None, None) if neither
    level is touched this bar.
    """
    if direction == "LONG":
        if sl_level is not None and o <= sl_level:
            return "stop", o
        if tp_level is not None and o >= tp_level:
            return "target", o
        if sl_level is not None and low <= sl_level:
            return "stop", sl_level
        if tp_level is not None and h >= tp_level:
            return "target", tp_level
    else:  # SHORT
        if sl_level is not None and o >= sl_level:
            return "stop", o
        if tp_level is not None and o <= tp_level:
            return "target", o
        if sl_level is not None and h >= sl_level:
            return "stop", sl_level
        if tp_level is not None and low <= tp_level:
            return "target", tp_level
    return None, None


def _level_hit(
    *, direction: str, level: float, o: float, h: float, low: float
) -> float | None:
    """Whether ONE level (a stop, or a single scale-out leg's target) is
    reached this bar, conservative (gap-through fills at the open).
    Returns the fill price, or ``None`` if not reached."""
    if direction == "LONG":
        if o >= level:
            return o
        if h >= level:
            return level
    else:
        if o <= level:
            return o
        if low <= level:
            return level
    return None


def _stop_hit(*, direction: str, sl_level: float, o: float, h: float, low: float) -> float | None:
    if direction == "LONG":
        if o <= sl_level:
            return o
        if low <= sl_level:
            return sl_level
    else:
        if o >= sl_level:
            return o
        if h >= sl_level:
            return sl_level
    return None


def run_backtest(
    candles: pl.DataFrame,
    signals: pl.DataFrame,
    config: BacktestConfig | None = None,
) -> BacktestResult:
    """Simulate ``signals`` against ``candles``; return trades + equity + metrics."""
    cfg = config or BacktestConfig()
    exits = cfg.exits
    candles = candles.sort("timestamp")

    needs_ohlc = exits.enabled
    if needs_ohlc:
        missing = [c for c in ("high", "low") if c not in candles.columns]
        if missing:
            raise ValueError(
                f"bracket exits (ExitConfig.enabled) require columns {missing} in candles"
            )

    work = candles
    if needs_ohlc and exits.needs_atr:
        work = add_atr(work, exits.atr_period, name="_atr")

    select_cols = ["timestamp", "open", "close"]
    if needs_ohlc:
        select_cols += ["high", "low"]
    if needs_ohlc and exits.needs_atr:
        select_cols += ["_atr"]

    signal_exprs = [pl.col("timestamp"), pl.col("signal_type").alias("next_signal")]
    if exits.needs_stop_price_column:
        if "stop_price" not in signals.columns:
            raise ValueError("ExitConfig.stop_mode='signal' requires a 'stop_price' column")
        signal_exprs.append(pl.col("stop_price"))
    if exits.needs_target_price_column:
        if "target_price" not in signals.columns:
            raise ValueError("ExitConfig.target_mode='signal' requires a 'target_price' column")
        signal_exprs.append(pl.col("target_price"))

    signals_sel = signals.sort("timestamp").select(*signal_exprs)
    merged = work.select(select_cols).join(signals_sel, on="timestamp", how="inner")
    if merged.height == 0:
        raise ValueError("no overlapping bars between candles and signals")

    times = merged["timestamp"].to_list()
    opens = merged["open"].to_list()
    closes = merged["close"].to_list()
    next_signal = merged["next_signal"].to_list()
    n = merged.height

    highs = merged["high"].to_list() if needs_ohlc else [None] * n
    lows = merged["low"].to_list() if needs_ohlc else [None] * n
    atrs = merged["_atr"].to_list() if (needs_ohlc and exits.needs_atr) else [None] * n
    signal_stops = merged["stop_price"].to_list() if exits.needs_stop_price_column else [None] * n
    signal_targets = (
        merged["target_price"].to_list() if exits.needs_target_price_column else [None] * n
    )

    session_start_t = parse_time(exits.session_start) if exits.session_start else None
    session_end_t = parse_time(exits.session_end) if exits.session_end else None
    eod_t = parse_time(exits.eod_squareoff) if exits.eod_squareoff else None

    quantity = cfg.quantity
    slippage = cfg.execution.slippage
    tick = cfg.tick_size
    capital = cfg.initial_capital

    # Phase 11: pre-compute the scale-out schedule ONCE -- it does not
    # depend on entry price/direction, only on position sizing. Sized in
    # LOTS first (never fractional contracts -- NIFTY's lot of 65 is
    # indivisible), then converted to contracts. Legs are kept sorted by
    # ascending at_r so they are always checked nearest-target-first.
    scale_schedule: list[tuple[float, int]] = []  # (at_r, leg_qty_contracts)
    if exits.scale_out:
        lot_count = cfg.lot_count
        position_lots = cfg.position_size
        assigned_lots = 0
        for leg in sorted(exits.scale_out, key=lambda leg: leg.at_r):
            leg_lots = math.floor(leg.fraction * position_lots + 1e-9)
            if leg_lots <= 0:
                raise ValueError(
                    f"ScaleLeg(at_r={leg.at_r}, fraction={leg.fraction}) quantises to 0 "
                    f"lots at position_size={position_lots} lots; increase position_size "
                    "or the leg's fraction."
                )
            assigned_lots += leg_lots
            scale_schedule.append((leg.at_r, leg_lots * lot_count))
        if assigned_lots > position_lots:
            raise ValueError(
                f"ExitConfig.scale_out legs sum to {assigned_lots} lots, exceeding "
                f"position_size={position_lots} lots."
            )

    trades: list[dict[str, object]] = []
    equity_rows: list[dict[str, object]] = []

    position: Position = "FLAT"
    trade_id = 0
    entry_time: datetime | None = None
    entry_price = 0.0
    entry_idx = 0
    realized = 0.0  # cumulative realized net P&L, updated once per FULLY CLOSED trade

    # Bracket state for the current open trade (irrelevant while FLAT).
    sl_level: float | None = None
    tp_level: float | None = None
    risk: float | None = None
    best_price = 0.0  # best (favourable) price seen since entry, for trailing
    trail_active = False
    mae = 0.0  # max adverse excursion (positive number, in price units)
    mfe = 0.0  # max favourable excursion (positive number, in price units)

    # Phase 11 scale-out state. ``remaining_qty`` == ``quantity`` and
    # ``banked_gross`` == 0.0 for the ENTIRE life of any trade that never
    # uses ExitConfig.scale_out -- so the mark-to-market formula below is
    # unified across both paths without changing legacy numbers.
    remaining_qty = 0
    filled_legs: list[dict[str, object]] = []
    filled_leg_indices: set[int] = set()
    legs_filled_count = 0
    banked_gross = 0.0
    breakeven_from_bar: int | None = None  # bar index breakeven becomes effective, if armed

    def _in_entry_window(t: datetime) -> bool:
        tod = t.time()
        if session_start_t is not None and tod < session_start_t:
            return False
        if session_end_t is not None and tod >= session_end_t:
            return False
        return True

    def open_trade(direction_label: str, price: float, i: int) -> None:
        nonlocal position, entry_time, entry_price, entry_idx
        nonlocal sl_level, tp_level, risk, best_price, trail_active, mae, mfe
        nonlocal remaining_qty, filled_legs, filled_leg_indices, legs_filled_count
        nonlocal banked_gross, breakeven_from_bar
        position = "LONG" if direction_label == "LONG" else "SHORT"
        entry_time = times[i]
        entry_price = price
        entry_idx = i
        best_price = price
        trail_active = False
        mae = 0.0
        mfe = 0.0
        remaining_qty = quantity
        filled_legs = []
        filled_leg_indices = set()
        legs_filled_count = 0
        banked_gross = 0.0
        breakeven_from_bar = None
        # ATR sizing uses the last FULLY CLOSED bar before the fill (i-1),
        # never the fill bar itself -- the stop/target level must be known
        # before it is used.
        atr_at_entry = atrs[i - 1] if (i > 0 and atrs[i - 1] is not None) else None
        sl_level, tp_level, risk = _bracket_levels(
            direction=position,
            entry_price=price,
            exits=exits,
            atr_at_entry=atr_at_entry,
            signal_stop=signal_stops[i],
            signal_target=signal_targets[i],
        )

    def _add_leg(exit_reason: str, price: float, qty: int, i: int) -> None:
        """Record one exit leg (partial or full) against the CURRENTLY
        open trade; reduces ``remaining_qty`` and banks its gross P&L.
        Never touches ``costs``/``realized`` directly -- those are
        settled once, in ``_finalize_trade``, exactly where the legacy
        single-exit engine settled them."""
        nonlocal remaining_qty, banked_gross, legs_filled_count, breakeven_from_bar
        sign = 1.0 if position == "LONG" else -1.0
        banked_gross += (price - entry_price) * qty * sign
        remaining_qty -= qty
        filled_legs.append({"qty": qty, "price": price, "reason": exit_reason, "time": times[i]})
        legs_filled_count += 1
        if (
            legs_filled_count == 1
            and exits.after_leg1_stop == "breakeven"
            and breakeven_from_bar is None
        ):
            # Effective from the NEXT bar only -- never the bar that
            # filled leg 1 itself (see _update_trailing_stop).
            breakeven_from_bar = i + 1

    def _finalize_trade(i: int, closed_at_end: bool) -> None:
        """Consolidate every leg of the CURRENT trade (1 leg for every
        trade that never touches ExitConfig.scale_out) into ONE
        trades-frame row. This is what keeps `total_trades`, `win_rate`,
        `profit_factor`, the pre-registered MIN_TRADES gate, and the
        permutation/bootstrap significance tests all correct under
        partial exits -- see quant.backtest.engine module docstring."""
        nonlocal realized, trade_id, position, entry_time
        direction = position
        sign = 1.0 if direction == "LONG" else -1.0
        entry_side = "buy" if direction == "LONG" else "sell"
        exit_side = "sell" if direction == "LONG" else "buy"

        total_qty = sum(int(leg["qty"]) for leg in filled_legs)
        exit_price = sum(leg["price"] * leg["qty"] for leg in filled_legs) / total_qty
        gross = banked_gross
        costs = cost_of_order(entry_price, total_qty, entry_side, cfg.costs) + sum(
            cost_of_order(leg["price"], leg["qty"], exit_side, cfg.costs) for leg in filled_legs
        )
        net = gross - costs
        realized += net
        trade_id += 1
        final_leg = filled_legs[-1]
        r_multiple = ((exit_price - entry_price) * sign / risk) if risk else None

        trades.append(
            {
                "trade_id": trade_id,
                "entry_time": entry_time,
                "exit_time": final_leg["time"],
                "direction": direction,
                "entry_price": entry_price,
                "exit_price": exit_price,
                "quantity": total_qty,
                "gross_pnl": gross,
                "costs": costs,
                "net_pnl": net,
                "holding_periods": i - entry_idx,
                "closed_at_end": int(closed_at_end),
                "exit_reason": final_leg["reason"],
                "mae": mae,
                "mfe": mfe,
                "bars_held": i - entry_idx,
                "r_multiple": r_multiple,
                "n_legs": len(filled_legs),
                "exit_legs_json": json.dumps(
                    [
                        {
                            "qty": leg["qty"],
                            "price": leg["price"],
                            "reason": leg["reason"],
                            "time": leg["time"].isoformat(),
                        }
                        for leg in filled_legs
                    ]
                ),
            }
        )
        position = "FLAT"
        entry_time = None

    def close_trade(
        direction: str, exit_price: float, i: int, closed_at_end: bool, exit_reason: str
    ) -> None:
        """Close 100% of whatever remains of the current trade in ONE
        leg. Signature unchanged from the pre-Phase-11 engine -- every
        existing call site (signal reversal, legacy bracket exit,
        end-of-data force-close) needs no edit. For a trade that never
        partially filled (remaining_qty == quantity, the overwhelming
        majority), this reproduces the pre-Phase-11 gross/costs/net/
        r_multiple formulas exactly: cost_of_order(entry, full_qty) +
        cost_of_order(exit, full_qty) == the old round_trip_costs(...)."""
        _add_leg(exit_reason, exit_price, remaining_qty, i)
        _finalize_trade(i, closed_at_end)

    def _update_excursion(direction: str, h: float | None, low: float | None) -> None:
        """MAE/MFE tracked from the bar's high/low when available."""
        nonlocal mae, mfe
        if h is None or low is None:
            return
        if direction == "LONG":
            mfe = max(mfe, h - entry_price)
            mae = max(mae, entry_price - low)
        else:
            mfe = max(mfe, entry_price - low)
            mae = max(mae, h - entry_price)

    def _update_trailing_stop(i: int) -> None:
        """Advance the trailing stop / breakeven-after-leg-1 using bars
        <= i-1 only (never bar i).

        No-op on the entry bar itself (``i == entry_idx``): there is no
        bar within this trade yet to trail from, and ``best_price`` is
        already correctly initialised to ``entry_price`` in ``open_trade``.
        This is the guard that stops a bar's own high/low from setting a
        trail level that the SAME bar's low/high could then trip --
        intrabar look-ahead, and the most common way a bracket engine
        manufactures fake profit. The breakeven-after-leg-1 move is
        guarded the same way via ``breakeven_from_bar = i + 1`` at the
        bar leg 1 actually filled (see ``_add_leg``), so it can only take
        effect starting the NEXT bar, never the fill bar itself.
        """
        nonlocal sl_level, best_price, trail_active
        if i <= entry_idx:
            return
        prev_h, prev_low = highs[i - 1], lows[i - 1]
        if prev_h is None or prev_low is None:
            return
        if position == "LONG":
            best_price = max(best_price, prev_h)
        else:
            best_price = min(best_price, prev_low)

        if (
            exits.after_leg1_stop == "breakeven"
            and breakeven_from_bar is not None
            and i >= breakeven_from_bar
        ):
            if position == "LONG":
                sl_level = max(sl_level, entry_price) if sl_level is not None else entry_price
            else:
                sl_level = min(sl_level, entry_price) if sl_level is not None else entry_price

        # trail_after_leg gates ONLY the ATR / prev-candle-extreme
        # trailing below, never the breakeven move above (which has its
        # own dedicated gate, breakeven_from_bar). Default 0 means
        # "trail immediately" -- a strict no-op for any trade that never
        # fills a scale-out leg (legs_filled_count stays 0 forever, and
        # 0 < 0 is False).
        if legs_filled_count < exits.trail_after_leg:
            return

        prev_atr = atrs[i - 1] if atrs[i - 1] is not None else None

        if exits.trail_mode == "breakeven_then_atr" and risk:
            favourable = (
                (best_price - entry_price) if position == "LONG" else (entry_price - best_price)
            )
            if favourable / risk >= exits.breakeven_at_r:
                trail_active = True
                if position == "LONG":
                    sl_level = max(sl_level, entry_price) if sl_level is not None else entry_price
                else:
                    sl_level = min(sl_level, entry_price) if sl_level is not None else entry_price

        if exits.trail_mode == "atr" or (exits.trail_mode == "breakeven_then_atr" and trail_active):
            if prev_atr is not None:
                if position == "LONG":
                    candidate = best_price - exits.trail_atr_mult * prev_atr
                    sl_level = max(sl_level, candidate) if sl_level is not None else candidate
                else:
                    candidate = best_price + exits.trail_atr_mult * prev_atr
                    sl_level = min(sl_level, candidate) if sl_level is not None else candidate

        if exits.trail_mode == "prev_candle_extreme":
            buffer = (
                exits.trail_buffer_atr * prev_atr
                if (prev_atr is not None and exits.trail_buffer_atr > 0)
                else 0.0
            )
            if position == "LONG":
                candidate = prev_low - buffer
                sl_level = max(sl_level, candidate) if sl_level is not None else candidate
            else:
                candidate = prev_h + buffer
                sl_level = min(sl_level, candidate) if sl_level is not None else candidate

    def _process_scale_out_bar(i: int) -> None:
        """The Phase-11 bracket path, used only when
        ``exits.scale_out`` is non-empty. Precedence within one bar:
        1. full stop (closes 100% of what remains, stop wins ties --
           checked before any leg, matching the legacy convention);
        2. scale-out legs, ascending ``at_r``, several may fill in one
           bar; a leg that empties ``remaining_qty`` finalizes the trade
           immediately;
        3. if still open, a runner target (``target_mode``), if any;
        4. if still open, time-stop / EOD, exactly as the legacy path.
        """
        direction = position
        o, h, low_ = opens[i], highs[i], lows[i]

        if sl_level is not None and h is not None and low_ is not None:
            stop_price = _stop_hit(direction=direction, sl_level=sl_level, o=o, h=h, low=low_)
            if stop_price is not None:
                side = "sell" if direction == "LONG" else "buy"
                exit_px = adjusted_price(stop_price, side, slippage, tick)
                close_trade(direction, exit_px, i, closed_at_end=False, exit_reason="stop")
                return

        if h is not None and low_ is not None:
            for idx, (at_r, leg_qty) in enumerate(scale_schedule):
                if idx in filled_leg_indices or risk is None:
                    continue
                sign = 1.0 if direction == "LONG" else -1.0
                level = entry_price + sign * at_r * risk
                hit_price = _level_hit(direction=direction, level=level, o=o, h=h, low=low_)
                if hit_price is None:
                    continue
                side = "sell" if direction == "LONG" else "buy"
                exit_px = adjusted_price(hit_price, side, slippage, tick)
                qty = min(leg_qty, remaining_qty)
                _add_leg("target", exit_px, qty, i)
                filled_leg_indices.add(idx)
                if remaining_qty == 0:
                    _finalize_trade(i, closed_at_end=False)
                    return

        if position == "FLAT":
            return  # defensive; _finalize_trade above already returned

        if tp_level is not None and h is not None and low_ is not None:
            target_price = _level_hit(direction=direction, level=tp_level, o=o, h=h, low=low_)
            if target_price is not None:
                side = "sell" if direction == "LONG" else "buy"
                exit_px = adjusted_price(target_price, side, slippage, tick)
                close_trade(direction, exit_px, i, closed_at_end=False, exit_reason="target")
                return

        bars_in_trade = i - entry_idx
        reason = None
        price = None
        if exits.time_stop_bars > 0 and bars_in_trade >= exits.time_stop_bars:
            reason, price = "time", closes[i]
        if reason is None and eod_t is not None and times[i].time() >= eod_t:
            reason, price = "eod", closes[i]
        if reason is not None:
            side = "sell" if direction == "LONG" else "buy"
            exit_px = adjusted_price(price, side, slippage, tick)
            close_trade(direction, exit_px, i, closed_at_end=False, exit_reason=reason)

    for i in range(n):
        pending = next_signal[i - 1] if i > 0 else None

        # 1. Signal-based reversal exit (fills at this bar's open) and
        #    2. new entry when flat (gated by the entry window) are kept as
        #    a single if/elif/elif chain -- a close and a fresh entry must
        #    never both fire in the same bar for the same pending signal.
        #    Splitting this into two independent statements would let a
        #    SELL that closes a LONG immediately open a SHORT in the same
        #    bar, which is not the legacy semantics.
        if position == "LONG" and pending in ("SELL", "EXIT_LONG", "EXIT"):
            exit_px = adjusted_price(opens[i], "sell", slippage, tick)
            close_trade("LONG", exit_px, i, closed_at_end=False, exit_reason="signal")
        elif position == "SHORT" and pending in ("BUY", "EXIT_SHORT", "EXIT"):
            exit_px = adjusted_price(opens[i], "buy", slippage, tick)
            close_trade("SHORT", exit_px, i, closed_at_end=False, exit_reason="signal")
        elif position == "FLAT":
            if pending == "BUY" and _in_entry_window(times[i]):
                open_trade("LONG", adjusted_price(opens[i], "buy", slippage, tick), i)
            elif pending == "SELL" and _in_entry_window(times[i]):
                open_trade("SHORT", adjusted_price(opens[i], "sell", slippage, tick), i)

        # 3. Bracket exits -- may fire intrabar, on the entry bar itself
        #    or on any later bar the position remains open.
        if position != "FLAT" and exits.enabled:
            _update_excursion(position, highs[i], lows[i])
            if exits.trail_mode != "none" or exits.after_leg1_stop == "breakeven":
                _update_trailing_stop(i)

            if exits.scale_out:
                _process_scale_out_bar(i)
            else:
                reason, price = (None, None)
                if needs_ohlc and highs[i] is not None and lows[i] is not None:
                    reason, price = _bracket_hit(
                        direction=position,
                        sl_level=sl_level,
                        tp_level=tp_level,
                        o=opens[i],
                        h=highs[i],
                        low=lows[i],
                    )
                bars_in_trade = i - entry_idx
                time_stop_hit = exits.time_stop_bars > 0 and bars_in_trade >= exits.time_stop_bars
                if reason is None and time_stop_hit:
                    reason, price = "time", closes[i]
                if reason is None and eod_t is not None and times[i].time() >= eod_t:
                    reason, price = "eod", closes[i]

                if reason is not None:
                    side = "sell" if position == "LONG" else "buy"
                    exit_px = adjusted_price(price, side, slippage, tick)
                    close_trade(position, exit_px, i, closed_at_end=False, exit_reason=reason)

        # Mark to market at this bar's close. ``banked_gross`` and
        # ``remaining_qty`` are exactly ``0.0``/``quantity`` for the
        # entire life of any trade that never uses ExitConfig.scale_out,
        # so this is numerically identical to the pre-Phase-11 formula
        # for every existing test.
        unrealized = 0.0
        if position == "LONG":
            unrealized = banked_gross + (closes[i] - entry_price) * remaining_qty
        elif position == "SHORT":
            unrealized = banked_gross + (entry_price - closes[i]) * remaining_qty
        equity_rows.append(
            {
                "timestamp": times[i],
                "equity": capital + realized + unrealized,
                "unrealized": unrealized,
                "realized": realized,
            }
        )

    # Force-close any position open at the end of the series
    if position != "FLAT":
        side = "sell" if position == "LONG" else "buy"
        exit_px = adjusted_price(closes[-1], side, slippage, tick)
        close_trade(position, exit_px, n - 1, closed_at_end=True, exit_reason="end_of_data")

    trades_df = pl.DataFrame(
        trades,
        schema={
            "trade_id": pl.Int64,
            "entry_time": pl.Datetime("ms"),
            "exit_time": pl.Datetime("ms"),
            "direction": pl.Utf8,
            "entry_price": pl.Float64,
            "exit_price": pl.Float64,
            "quantity": pl.Int64,
            "gross_pnl": pl.Float64,
            "costs": pl.Float64,
            "net_pnl": pl.Float64,
            "holding_periods": pl.Int64,
            "closed_at_end": pl.Int64,
            "exit_reason": pl.Utf8,
            "mae": pl.Float64,
            "mfe": pl.Float64,
            "bars_held": pl.Int64,
            "r_multiple": pl.Float64,
            "n_legs": pl.Int64,
            "exit_legs_json": pl.Utf8,
        },
        orient="row",
    )
    equity_df = pl.DataFrame(equity_rows, schema=EQUITY_COLUMNS, orient="row")
    metrics = compute_metrics(trades=trades_df, equity=equity_df, capital=capital)
    return BacktestResult(
        trades=trades_df,
        equity=equity_df,
        metrics=metrics,
        daily_returns=daily_returns(equity_df),
    )
