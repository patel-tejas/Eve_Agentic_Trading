"""Performance metrics over backtest trades and the equity curve.

Phase 05 minimum set: trade counts, win rate, gross/net P&L, profit
factor, drawdown (value + duration), holding time, streaks, Sharpe,
Sortino, Calmar, expectancy, daily P&L.
"""

from __future__ import annotations

import math

import polars as pl

TRADING_DAYS_PER_YEAR = 252.0
ANNUALIZATION = math.sqrt(TRADING_DAYS_PER_YEAR)


def compute_metrics(
    *,
    trades: pl.DataFrame,
    equity: pl.DataFrame,
    capital: float = 1_000_000.0,
) -> dict[str, float | int | str]:
    """Aggregate all metrics from a trades frame and equity curve."""
    m: dict[str, float | int | str] = {}

    if trades.height == 0:
        m.update(
            {
                "total_trades": 0,
                "winning_trades": 0,
                "losing_trades": 0,
                "win_rate": 0.0,
                "gross_pnl": 0.0,
                "net_pnl": 0.0,
                "avg_trade_pnl": 0.0,
                "profit_factor": 0.0,
                "max_drawdown_pct": 0.0,
            }
        )
        return _with_equity_metrics(m, equity, capital)

    net = trades["net_pnl"].to_list()
    gross = trades["gross_pnl"].to_list()
    wins = [x for x in net if x > 0]
    losses = [x for x in net if x <= 0]

    m["total_trades"] = trades.height
    m["winning_trades"] = len(wins)
    m["losing_trades"] = len(losses)
    m["win_rate"] = len(wins) / trades.height
    m["gross_pnl"] = sum(gross)
    m["net_pnl"] = sum(net)
    m["avg_trade_pnl"] = sum(net) / trades.height
    m["avg_winner"] = sum(wins) / len(wins) if wins else 0.0
    m["avg_loser"] = sum(losses) / len(losses) if losses else 0.0

    # Profit factor: gross P&L of winning trades / |gross P&L| of losing trades
    gross_of_win = [g for n, g in zip(net, gross) if n > 0]
    gross_of_loss = [g for n, g in zip(net, gross) if n <= 0]
    m["profit_factor"] = sum(gross_of_win) / abs(sum(gross_of_loss)) if sum(gross_of_loss) else 0.0

    hold = trades["holding_periods"].to_list()
    m["avg_holding_periods"] = sum(hold) / len(hold)

    strengths = _streaks(net)
    m["longest_win_streak"] = strengths[0]
    m["longest_loss_streak"] = strengths[1]

    expect = [x for x in net]
    m["expectancy"] = sum(expect) / len(expect) if expect else 0.0

    return _with_equity_metrics(m, equity, capital)


def _with_equity_metrics(
    m: dict[str, float | int | str],
    equity: pl.DataFrame,
    capital: float,
) -> dict[str, float | int | str]:
    eq = equity.sort("timestamp")["equity"].to_list()
    if not eq:
        return m

    peak = float("-inf")
    max_dd_val = 0.0
    max_dd_pct = 0.0
    cur_dd = 0
    max_dd_duration = 0
    for v in eq:
        if v > peak:
            peak = v
            cur_dd = 0
        dd_val = peak - v
        dd_pct = dd_val / peak if peak > 0 else 0.0
        if dd_pct > max_dd_pct:
            max_dd_pct = dd_pct
            max_dd_val = dd_val
        cur_dd = cur_dd + 1 if v < peak else 0
        max_dd_duration = max(max_dd_duration, cur_dd)

    m["max_drawdown_pct"] = max_dd_pct
    m["max_drawdown_value"] = max_dd_val
    m["max_drawdown_duration_bars"] = max_dd_duration

    total_return = (eq[-1] - capital) / capital if capital else 0.0
    m["total_return_pct"] = total_return

    days = equity["timestamp"].dt.date().n_unique()
    daily = (
        equity.sort("timestamp")
        .with_columns(pl.col("timestamp").dt.date().alias("day_of"))
        .group_by("day_of")
        .agg(pl.col("equity").last())
        .sort("day_of")["equity"]
        .to_list()
    )
    returns = [(b - a) / a if a > 0 else 0.0 for a, b in zip(daily, daily[1:])]
    mean_r = sum(returns) / len(returns) if returns else 0.0
    if len(returns) > 1:
        var = sum((x - mean_r) ** 2 for x in returns) / (len(returns) - 1)
    else:
        var = 0.0
    std_r = math.sqrt(var)

    m["sharpe"] = (mean_r / std_r * ANNUALIZATION) if std_r > 0 else 0.0
    downside = [x for x in returns if x < 0]
    if downside:
        dstd = math.sqrt(sum(x * x for x in downside) / max(len(downside) - 1, 1))
        sortino = mean_r / dstd * ANNUALIZATION if dstd > 0 else 0.0
    else:
        sortino = 0.0
    m["sortino"] = sortino

    m["calmar"] = (
        total_return * TRADING_DAYS_PER_YEAR / max(days, 1) / max_dd_pct if max_dd_pct > 0 else 0.0
    )
    m["trading_days"] = days
    return m


def _streaks(net: list[float]) -> tuple[int, int]:
    """Return (longest winning streak, longest losing streak) in trades."""
    best_win = best_loss = cur_win = cur_loss = 0
    for x in net:
        if x > 0:
            cur_win += 1
            cur_loss = 0
            best_win = max(best_win, cur_win)
        else:
            cur_loss += 1
            cur_win = 0
            best_loss = max(best_loss, cur_loss)
    return best_win, best_loss
