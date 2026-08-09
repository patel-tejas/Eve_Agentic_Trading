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
