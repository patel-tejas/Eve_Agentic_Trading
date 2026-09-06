"""Deterministic round analysis (the "Analyst" role, run as code).

Per-project convention, Agent/Task subagents are not spawned unless the
user asks -- so the Phase 7 round-loop's Analyst role is implemented
here as ordinary, reproducible code reading the aggregated leaderboard,
not as an LLM call. Reports:

- which (strategy, symbol, timeframe) cells beat break-even on the
  TRAIN split, with a plateau-vs-spike check (is the top result part of
  a cluster of similar-performing neighbours, or an isolated outlier);
- any row with pct_closed_at_end > 0 (force-close artifact) or
  total_trades below the protocol's MIN_TRADES["train"];
- the top-N candidates overall, ranked by net_pnl among cells that pass
  the sanity checks above.

Reads only the aggregated leaderboard -- never raw trade frames.
"""

from __future__ import annotations

import argparse
from pathlib import Path

import polars as pl

from quant.research.leaderboard import load_leaderboard
from quant.research.protocol import MIN_TRADES


def _numify(frame: pl.DataFrame, cols: list[str]) -> pl.DataFrame:
    exprs = [pl.col(c).cast(pl.Float64, strict=False) for c in cols if c in frame.columns]
    return frame.with_columns(exprs)


def analyze(campaign_id: str, round_no: int, *, root: str, top_n: int = 15) -> str:
    lb = load_leaderboard(campaign_id, round_no=round_no, root=root)
    if lb.height == 0:
        return f"# Round {round_no} analysis -- {campaign_id}\n\nNo rows found.\n"

    numeric_cols = [
        "net_pnl", "gross_pnl", "profit_factor", "win_rate", "total_trades",
        "max_drawdown_pct", "sharpe", "pct_closed_at_end",
    ]
    lb = _numify(lb, numeric_cols)
    ok = lb.filter(pl.col("status") == "ok")
    errors = lb.filter(pl.col("status") == "error")

    lines = [f"# Round {round_no} analysis -- {campaign_id}", ""]
    lines.append(f"Total rows: {lb.height} (ok: {ok.height}, error: {errors.height})")
    if errors.height:
        top_errors = (
            errors.group_by("error").agg(pl.len().alias("n")).sort("n", descending=True).head(5)
        )
        lines.append("\nTop errors:")
        for row in top_errors.to_dicts():
            lines.append(f"- ({row['n']}x) {row['error']}")

    min_trades = MIN_TRADES["train"]
    flagged_artifact = ok.filter(pl.col("pct_closed_at_end") > 0)
    flagged_thin = ok.filter(pl.col("total_trades") < min_trades)
    lines.append(
        f"\nFlagged (force-close artifact present): {flagged_artifact.height} rows"
    )
    lines.append(
        f"Flagged (< {min_trades} trades, below protocol MIN_TRADES): {flagged_thin.height} rows"
    )

    clean = ok.filter((pl.col("pct_closed_at_end") == 0) & (pl.col("total_trades") >= min_trades))
    lines.append(
        f"\nClean candidate pool (no artifact, >= {min_trades} trades): {clean.height} rows"
    )

    lines.append("\n## Break-even summary by (strategy, symbol, timeframe)")
    lines.append("")
    lines.append(
        "| strategy | symbol | timeframe | n | positive | best net_pnl | best PF | best trades |"
    )
    lines.append("|---|---|---|---|---|---|---|---|")
    grouped = clean.group_by(["strategy_id", "symbol", "timeframe"]).agg(
        pl.len().alias("n"),
        (pl.col("net_pnl") > 0).sum().alias("positive"),
        pl.col("net_pnl").max().alias("best_net"),
    )
    for row in grouped.sort(["strategy_id", "symbol", "timeframe"]).to_dicts():
        cell = clean.filter(
            (pl.col("strategy_id") == row["strategy_id"])
            & (pl.col("symbol") == row["symbol"])
            & (pl.col("timeframe") == row["timeframe"])
            & (pl.col("net_pnl") == row["best_net"])
        ).head(1)
        best_pf = cell["profit_factor"][0] if cell.height else None
        best_trades = cell["total_trades"][0] if cell.height else None
        lines.append(
            f"| {row['strategy_id']} | {row['symbol']} | {row['timeframe']} | {row['n']} | "
            f"{row['positive']} ({100*row['positive']/row['n']:.0f}%) | "
            f"{row['best_net']:,.0f} | {best_pf:.2f} | {best_trades:.0f} |"
        )

    lines.append("\n## Top candidates overall (clean pool, ranked by net_pnl)")
    lines.append("")
    top = clean.sort("net_pnl", descending=True).head(top_n)
    lines.append(
        "| rank | strategy | symbol | tf | net_pnl | PF | trades | win_rate | sharpe "
        "| maxDD% | params |"
    )
    lines.append("|---|---|---|---|---|---|---|---|---|---|---|")
    for i, row in enumerate(top.to_dicts(), start=1):
        lines.append(
            f"| {i} | {row['strategy_id']} | {row['symbol']} | {row['timeframe']} | "
            f"{row['net_pnl']:,.0f} | {row['profit_factor']:.2f} | {row['total_trades']:.0f} | "
            f"{row['win_rate']:.2%} | {row['sharpe']:.2f} | {row['max_drawdown_pct']:.2%} | "
            f"`{row['params_json']}` |"
        )

    # Plateau-vs-spike check: for the single best row, count how many
    # OTHER trials of the same (strategy, symbol, timeframe) land within
    # 20% of its net_pnl -- a lone spike with no nearby support is a
    # classic overfitting signature.
    if top.height:
        winner = top.row(0, named=True)
        cell = clean.filter(
            (pl.col("strategy_id") == winner["strategy_id"])
            & (pl.col("symbol") == winner["symbol"])
            & (pl.col("timeframe") == winner["timeframe"])
        )
        threshold = 0.8 * winner["net_pnl"] if winner["net_pnl"] > 0 else winner["net_pnl"] * 1.2
        nearby = cell.filter(pl.col("net_pnl") >= threshold).height
        verdict = "plateau (supported)" if nearby >= 5 else "POSSIBLE ISOLATED SPIKE"
        lines.append(
            f"\nTop overall winner: {nearby} of {cell.height} trials in its cell land "
            f"within 20% of its net_pnl -- {verdict}."
        )

    return "\n".join(lines) + "\n"


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--campaign", required=True)
    parser.add_argument("--round", type=int, required=True)
    parser.add_argument("--root", default="data/results/leaderboard")
    parser.add_argument("--top-n", type=int, default=15)
    parser.add_argument("--out", default=None, help="write markdown here instead of stdout")
    args = parser.parse_args()

    report = analyze(args.campaign, args.round, root=args.root, top_n=args.top_n)
    if args.out:
        Path(args.out).parent.mkdir(parents=True, exist_ok=True)
        Path(args.out).write_text(report, encoding="utf-8")
        print(f"wrote {args.out}")
    else:
        print(report)


if __name__ == "__main__":
    main()
