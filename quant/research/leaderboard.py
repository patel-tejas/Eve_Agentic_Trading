"""Append-only, resumable leaderboard for the Phase 09 sweep campaign.

One row per trial. Written as ``part_<pid>_<chunk>.jsonl`` shards under
``data/results/leaderboard/<campaign_id>/round_<NN>/`` (one file per
worker chunk, so concurrent workers never append to the same file) and
merged into a single ``leaderboard.parquet`` on read. ``param_hash``
makes a trial idempotent: a trial already present with
``status != "error"`` is skipped by the sweep dispatcher, so an
interrupted campaign resumes without recomputation or duplication.
"""

from __future__ import annotations

import json
from pathlib import Path

import polars as pl

from quant.research.run_card import canonical_json, hash_mapping

LEADERBOARD_COLUMNS = (
    "campaign_id",
    "round",
    "trial_id",
    "strategy_id",
    "param_hash",
    "params_json",
    "exits_json",
    "symbol",
    "price_source",
    "timeframe",
    "split",
    "window_start",
    "window_end",
    "n_bars",
    "trading_days",
    "total_trades",
    "winning_trades",
    "losing_trades",
    "win_rate",
    "gross_pnl",
    "net_pnl",
    "avg_trade_pnl",
    "profit_factor",
    "expectancy",
    "max_drawdown_pct",
    "max_drawdown_value",
    "sharpe",
    "sortino",
    "calmar",
    "total_return_pct",
    "avg_holding_periods",
    "pct_closed_at_end",
    "exit_reason_counts_json",
    "daily_returns_json",
    "lot_size",
    "tick_size_rupees",
    "slippage_mode",
    "engine_version",
    "strategy_version",
    "cost_model_version",
    "git_sha",
    "config_hash",
    "run_card_hash",
    "seed",
    "created_at",
    "host",
    "duration_ms",
    "status",
    "error",
)


def trial_param_hash(strategy_id: str, params: dict, exits: dict, market: dict) -> str:
    """SHA-256[:16] of the canonical (strategy_id, params, exits, market)
    tuple -- what makes two trials "the same trial" for resume/dedup and
    for the cumulative trial count DSR is penalized against."""
    return hash_mapping(
        {"strategy_id": strategy_id, "params": params, "exits": exits, "market": market}
    )[:16]


def make_trial_id(round_no: int, param_hash: str, symbol: str, timeframe: str, split: str) -> str:
    return f"{round_no:02d}-{param_hash}-{symbol}-{timeframe}-{split}"


def _campaign_root(campaign_id: str, *, root: str | Path) -> Path:
    return Path(root) / campaign_id


def _round_dir(campaign_id: str, round_no: int, *, root: str | Path) -> Path:
    return _campaign_root(campaign_id, root=root) / f"round_{round_no:02d}"


def append_results(
    rows: list[dict[str, object]],
    *,
    campaign_id: str,
    round_no: int,
    root: str | Path = "data/results/leaderboard",
    shard_name: str,
) -> Path:
    """Append ``rows`` (already matching ``LEADERBOARD_COLUMNS``) as one
    JSONL shard. ``shard_name`` should be unique per writer (e.g.
    ``f"part_{os.getpid()}_{chunk_idx}"``) -- never write two shards with
    the same name concurrently."""
    out_dir = _round_dir(campaign_id, round_no, root=root)
    out_dir.mkdir(parents=True, exist_ok=True)
    path = out_dir / f"{shard_name}.jsonl"
    with path.open("a", encoding="utf-8") as handle:
        for row in rows:
            handle.write(canonical_json(row))
            handle.write("\n")
    return path


def load_leaderboard(
    campaign_id: str,
    *,
    round_no: int | None = None,
    root: str | Path = "data/results/leaderboard",
) -> pl.DataFrame:
    """Merge every JSONL shard for a campaign (optionally one round) into
    a single frame. Returns an empty frame with the declared schema if
    nothing has been written yet, never raises."""
    campaign_dir = _campaign_root(campaign_id, root=root)
    if round_no is not None:
        shard_dirs = [_round_dir(campaign_id, round_no, root=root)]
    else:
        shard_dirs = sorted(campaign_dir.glob("round_*")) if campaign_dir.exists() else []

    rows: list[dict[str, object]] = []
    for shard_dir in shard_dirs:
        if not shard_dir.exists():
            continue
        for shard_path in sorted(shard_dir.glob("part_*.jsonl")):
            with shard_path.open(encoding="utf-8") as handle:
                for line in handle:
                    line = line.strip()
                    if line:
                        rows.append(json.loads(line))

    if not rows:
        return pl.DataFrame(schema={col: pl.Utf8 for col in LEADERBOARD_COLUMNS})
    return pl.DataFrame(rows, infer_schema_length=None)


def completed_trial_ids(
    campaign_id: str, *, root: str | Path = "data/results/leaderboard"
) -> set[str]:
    """``trial_id``s already present with ``status != "error"`` -- what
    the sweep dispatcher skips on resume."""
    frame = load_leaderboard(campaign_id, root=root)
    if frame.height == 0 or "trial_id" not in frame.columns:
        return set()
    ok = frame.filter(pl.col("status") != "error")
    return set(ok["trial_id"].to_list())


def cumulative_trial_count(
    campaign_id: str, *, root: str | Path = "data/results/leaderboard"
) -> int:
    """Distinct ``param_hash`` values ever evaluated in this campaign,
    across ALL rounds -- this is the ``n_trials`` that
    ``quant.research.multiple_testing.deflated_sharpe_ratio`` must be
    penalized against, not any single round's trial count."""
    frame = load_leaderboard(campaign_id, root=root)
    if frame.height == 0 or "param_hash" not in frame.columns:
        return 0
    return frame["param_hash"].n_unique()
