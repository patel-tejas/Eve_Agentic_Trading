"""Honest evaluation of a user strategy (Phase 15, P4).

A backtest on the month the rules were tuned on says little. This module
turns an in-sample run, a run on a month the user has NOT backtested (the
holdout), the number of tries (trials) and a buy-and-hold benchmark into a
verdict that says plainly how much the result can be trusted.

Rules, in the order they are checked (the first that applies is the label;
every one that applies is listed in ``reasons``):

1. ``too_few_trades``  -- under ``MIN_TRADES`` trades in either window: the
   numbers are anecdotes, whatever they show.
2. ``failed_holdout``  -- the holdout lost money (net, after costs).
3. ``not_significant`` -- the in-sample Sharpe does not survive the deflated
   Sharpe correction for ``trials`` tries (probability < 0.95).
4. ``lags_buy_and_hold`` -- profitable, but holding the future for the same
   month made more.
5. ``survived_holdout`` -- none of the above. Never "proven": two months of
   one instrument cannot establish an edge, and the verdict says so.

Pure functions only; the tool in ``mcp/quant_server/store_tools.py`` does the
I/O. Every number here comes from the engine's own backtests.
"""

from __future__ import annotations

import math
from dataclasses import asdict, dataclass, field
from typing import Any, Sequence

import polars as pl

from quant.research._stats import sharpe_ratio, stdev
from quant.research.multiple_testing import deflated_sharpe_ratio

MIN_TRADES = 30
DSR_THRESHOLD = 0.95
ANNUALIZATION = math.sqrt(252.0)

VERDICT_TEXT = {
    "too_few_trades": "Too few trades to judge",
    "failed_holdout": "Lost money on the holdout month",
    "not_significant": "Not distinguishable from luck after {trials} tries",
    "lags_buy_and_hold": "Profitable, but behind buy-and-hold",
    "survived_holdout": "Survived the holdout month",
}

CAVEAT = (
    "Research only. A month or two of one instrument cannot establish an edge, "
    "and the holdout is only clean the first time it is used."
)


@dataclass
class Verdict:
    label: str
    headline: str
    reasons: list[str]
    trials: int
    in_sample_trades: int
    holdout_trades: int
    deflated_sharpe: dict[str, Any] | None
    benchmark: dict[str, Any] | None
    holdout_reused: bool
    caveat: str = CAVEAT
    skipped: dict[str, str] = field(default_factory=dict)

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)


def buy_and_hold(candles: pl.DataFrame, lot_size: int, lots: int) -> dict[str, Any]:
    """Gross P&L of holding the future long from the month's first open to its
    last close, at the strategy's size. No costs, held overnight: a yardstick,
    not a strategy."""
    if candles.height == 0:
        return {"net_pnl": None, "points": None}
    first = float(candles.sort("timestamp")["open"][0])
    last = float(candles.sort("timestamp")["close"][-1])
    points = last - first
    return {
        "points": points,
        "gross_pnl": points * lot_size * lots,
        "first_open": first,
        "last_close": last,
        "note": "long from the first open to the last close, no costs",
    }


def trials_adjusted_sharpe(
    returns: Sequence[float], *, trials: int, recorded_sharpes: Sequence[float] = ()
) -> dict[str, Any]:
    """Deflated Sharpe of the in-sample returns given ``trials`` tries.

    The dispersion of the tries' Sharpes is taken from the annualised Sharpes
    recorded on this strategy's earlier backtests, but never below the
    sampling error of a Sharpe estimate (1/sqrt(T-1) per period): with few
    recorded tries the observed spread understates how far luck alone moves
    the number, and an understated spread would flatter the result.
    """
    rets = list(returns)
    floor = 1.0 / math.sqrt(max(len(rets) - 1, 1))
    per_period = [s / ANNUALIZATION for s in recorded_sharpes if s is not None]
    spread = stdev(per_period) if len(per_period) >= 2 else 0.0
    result = deflated_sharpe_ratio(
        rets, n_trials=max(trials, 1), trial_sharpe_std=max(spread, floor)
    ).to_dict()
    result["observed_sharpe_annualised"] = sharpe_ratio(rets, annualised=False) * ANNUALIZATION
    return result


def make_verdict(
    *,
    trials: int,
    in_sample_metrics: dict[str, Any],
    holdout_metrics: dict[str, Any],
    in_sample_returns: Sequence[float],
    recorded_sharpes: Sequence[float],
    benchmark: dict[str, Any] | None,
    holdout_reused: bool,
) -> Verdict:
    reasons: list[str] = []
    labels: list[str] = []
    skipped: dict[str, str] = {}
    n_in = int(in_sample_metrics.get("total_trades") or 0)
    n_out = int(holdout_metrics.get("total_trades") or 0)
    net_out = holdout_metrics.get("net_pnl")

    if n_in < MIN_TRADES or n_out < MIN_TRADES:
        labels.append("too_few_trades")
        reasons.append(
            f"{n_in} in-sample and {n_out} holdout trades; under {MIN_TRADES} in a window "
            "the result is an anecdote, not evidence."
        )
    if net_out is not None and net_out <= 0:
        labels.append("failed_holdout")
        reasons.append("It lost money, after costs, on the month it was not tuned on.")

    dsr = None
    if len(in_sample_returns) >= 2:
        dsr = trials_adjusted_sharpe(
            in_sample_returns, trials=trials, recorded_sharpes=recorded_sharpes
        )
        if dsr["deflated_sharpe"] < DSR_THRESHOLD:
            labels.append("not_significant")
            reasons.append(
                f"Allowing for {trials} tr{'y' if trials == 1 else 'ies'}, the chance its "
                f"in-sample Sharpe beats luck is {dsr['deflated_sharpe']:.0%} "
                f"(needs {DSR_THRESHOLD:.0%})."
            )
    else:
        skipped["deflated_sharpe"] = f"{len(in_sample_returns)} daily returns, need >= 2"
        labels.append("not_significant")
        reasons.append("Too few trading days to test the Sharpe ratio at all.")

    if benchmark and benchmark.get("gross_pnl") is not None and net_out is not None:
        if net_out > 0 and net_out < benchmark["gross_pnl"]:
            labels.append("lags_buy_and_hold")
            reasons.append("Holding the future for the same month made more, before costs.")

    if holdout_reused:
        reasons.append(
            "This holdout month was already used to evaluate an earlier version, so it is no "
            "longer unseen; treat this as in-sample."
        )

    order = ["too_few_trades", "failed_holdout", "not_significant", "lags_buy_and_hold"]
    label = next((x for x in order if x in labels), "survived_holdout")
    if label == "survived_holdout":
        reasons.append("Profitable on an unseen month and not explained by the number of tries.")
    return Verdict(
        label=label,
        headline=VERDICT_TEXT[label].format(trials=trials),
        reasons=reasons,
        trials=trials,
        in_sample_trades=n_in,
        holdout_trades=n_out,
        deflated_sharpe=dsr,
        benchmark=benchmark,
        holdout_reused=holdout_reused,
        skipped=skipped,
    )
