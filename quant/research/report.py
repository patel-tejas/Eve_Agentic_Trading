"""Markdown rendering for the phase-06 baseline report."""

from __future__ import annotations

METRIC_LABELS = {
    "total_trades": "Total trades",
    "win_rate": "Win rate",
    "gross_pnl": "Gross P&L",
    "net_pnl": "Net P&L",
    "profit_factor": "Profit factor",
    "max_drawdown_pct": "Max drawdown (equity)",
    "sharpe": "Sharpe",
    "sortino": "Sortino",
    "avg_trade_pnl": "Avg trade",
    "avg_holding_periods": "Avg holding (bars)",
}

PERCENT_METRICS = {"win_rate", "max_drawdown_pct"}
MONEY_METRICS = {"gross_pnl", "net_pnl", "avg_trade_pnl"}


def fmt_value(metric: str, value: object) -> str:
    if not isinstance(value, (int, float)):
        return "-"
    if metric in PERCENT_METRICS:
        return f"{value:.1%}"
    if metric in MONEY_METRICS:
        return f"{value:,.0f}"
    return f"{value:.2f}"


def render_markdown_report(comparison: dict[str, object]) -> str:
    """Render the baseline comparison JSON into a markdown report."""
    lines: list[str] = [
        "# Baseline Report — EMA 9/15 + Angle (Phase 06)",
        "",
        f"**Period:** {comparison['period']}  ",
        f"**Dataset:** {comparison['dataset']}  ",
        f"**Experiments:** {comparison['experiment_count']}",
        "",
        "## Assumptions",
        "",
    ]
    for key, value in comparison["assumptions"].items():
        lines.append(f"- `{key}`: {value}")

    lines += ["", "## Comparison", ""]

    table = comparison["comparison_table"]
    variants = sorted(table.keys())
    timeframes = sorted(
        {tf for v in table.values() for tf in v}, key=lambda s: int(s[:-1])
    )
    keys = list(METRIC_LABELS)

    header = ["Metric"] + [f"{v} {tf}" for v in variants for tf in timeframes]
    lines.append("| " + " | ".join(header) + " |")
    lines.append("|" + "---|" * len(header))
    for key in keys:
        row = [f"**{METRIC_LABELS[key]}**"]
        for v in variants:
            for tf in timeframes:
                value = table[v].get(tf, {}).get(key)
                row.append(fmt_value(key, value))
        lines.append("| " + " | ".join(row) + " |")

    lines += ["", "## Reproducibility", ""]
    for exp in comparison["experiments"]:
        metrics = exp["metrics"]
        lines.append(
            f"- **{exp['experiment_id']}** ({exp['variant']}, {exp['timeframe']}) — "
            f"config `{exp['config_hash']}` — "
            f"{metrics['total_trades']} trades, net {metrics['net_pnl']:,.0f}"
        )

    lines += ["", "## Raw data", ""]
    results = "data/results/futures/NIFTY/<period>"
    lines += [
        f"- Per-experiment trade logs: `{results}/baseline/trades_<experiment_id>.parquet`",
        f"- Backtest artifacts (trades/metrics/equity per timeframe): `{results}/`",
    ]
    return "\n".join(lines) + "\n"


def render_robustness_report(summary: dict[str, object]) -> str:
    """Render the phase-08 research summary JSON into a markdown report."""
    lines: list[str] = [
        "# Robustness Report — Phase 08",
        "",
        f"**Period:** {summary['period']}  ",
        f"**Timeframes:** {', '.join(sorted(summary['timeframes'], key=lambda s: int(s[:-1])))}",
        "",
    ]

    for tf in sorted(summary["timeframes"], key=lambda s: int(s[:-1])):
        info = summary["timeframes"][tf]
        lines += [f"## {tf}", ""]

        lines.append("**Split schedule (half-open, train / validation / test):**")
        for name, (start, end) in info["splits"].items():
            lines.append(f"- {name}: {start} -> {end}")

        gs = info["grid_search"]
        lines += [
            "",
            "**Parameter grid (training window only):**",
            f"- Combinations: {gs['combinations']}",
            f"- Positive net P&L: {gs['positive_share']:.1%}",
            f"- Median net P&L: {gs['median_net_pnl']:,.0f}",
            f"- Best: `{gs['best']['params']}` -> net {gs['best']['net_pnl']:,.0f}"
            f" ({gs['best']['total_trades']} trades, PF {gs['best']['profit_factor']:.2f})",
            "",
        ]

        wf = info["walk_forward"]
        lines += ["**Walk-forward (out-of-sample):**", ""]
        if wf:
            header = (
                "| Step | Train window | Test window | Best params "
                "(fast/slow/angle/lookback) | Train net | Test net | Trades | PF |"
            )
            lines.append(header)
            lines.append("|" + "---|" * 8)
            for row in wf:
                params = " / ".join(
                    str(row.get(k))
                    for k in (
                        "fast_ema",
                        "slow_ema",
                        "angle_threshold",
                        "angle_lookback",
                    )
                )
                lines.append(
                    "| {} | {:.10}..{:.10} | {:.10}..{:.10} | {} | {:,.0f} |"
                    " {:,.0f} | {} | {:.2f} |".format(
                        row["step"],
                        str(row["train_start"]),
                        str(row["train_end"]),
                        str(row["test_start"]),
                        str(row["test_end"]),
                        params,
                        row["train_net_pnl"],
                        row["test_net_pnl"],
                        row["test_trades"],
                        row["test_profit_factor"],
                    )
                )
        else:
            lines.append("- no walk-forward windows for this dataset")
        lines.append("")

        lines += ["**Regime analysis (B-config full month):**", ""]
        header = "| Regime | Days | Trades | Net P&L | Profit factor | Win rate |"
        lines.append(header)
        lines.append("|" + "---|" * 6)
        for row in info["regimes"]:
            lines.append(
                f"| {row['regime']} | {row['days']} | {row['trades']} | {row['net_pnl']:,.0f}"
                f" | {row['profit_factor']:.2f} | {row['win_rate']:.1%} |"
            )
        lines += ["", ""]

    lines += ["## Reproducibility", ""]
    lines += [
        "- Signal engine: phase 04 `ema_9_15` (deterministic, no look-ahead)",
        "- Backtester: phase 05 (next-candle-open execution, 1 tick normal slippage)",
        "- Grid experiment IDs: `RE-<seq>` in `parameter_search_<tf>.parquet`",
        "- Raw results: `data/results/futures/NIFTY/<period>/research/`",
    ]
    return "\n".join(lines) + "\n"
