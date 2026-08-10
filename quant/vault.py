"""Experiment vault: a small SQLite ledger of every research run.

Every backtest call and baseline experiment produced through the MCP
server is recorded here so cross-run questions ("which configs beat the
baseline?", "best net P&L so far") can be answered deterministically from
the vault instead of recomputing.

Layout:
    data/vault/experiments.db   (SQLite, WAL mode)
"""

from __future__ import annotations

import sqlite3
from contextlib import closing
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

DEFAULT_VAULT_PATH = Path("data/vault/experiments.db")

_SCHEMA = """
CREATE TABLE IF NOT EXISTS runs (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    created_at TEXT NOT NULL,
    source TEXT NOT NULL,
    experiment_id TEXT,
    variant TEXT,
    month TEXT NOT NULL,
    timeframe TEXT NOT NULL,
    config_hash TEXT,
    signal_mode TEXT NOT NULL,
    fast_ema INTEGER NOT NULL,
    slow_ema INTEGER NOT NULL,
    angle_threshold REAL NOT NULL,
    angle_lookback INTEGER NOT NULL,
    slippage TEXT,
    total_trades INTEGER,
    win_rate REAL,
    gross_pnl REAL,
    net_pnl REAL,
    profit_factor REAL,
    avg_trade_pnl REAL,
    avg_holding_periods REAL,
    max_drawdown_pct REAL,
    max_drawdown_duration_bars INTEGER,
    sharpe REAL,
    sortino REAL,
    calmar REAL,
    trading_days INTEGER,
    equity_start REAL,
    equity_end REAL,
    equity_bars INTEGER
);
CREATE INDEX IF NOT EXISTS idx_runs_month ON runs(month);
CREATE INDEX IF NOT EXISTS idx_runs_timeframe ON runs(timeframe);
CREATE INDEX IF NOT EXISTS idx_runs_config_hash ON runs(config_hash);
"""

_COLUMNS = (
    "source",
    "experiment_id",
    "variant",
    "month",
    "timeframe",
    "config_hash",
    "signal_mode",
    "fast_ema",
    "slow_ema",
    "angle_threshold",
    "angle_lookback",
    "slippage",
    "total_trades",
    "win_rate",
    "gross_pnl",
    "net_pnl",
    "profit_factor",
    "avg_trade_pnl",
    "avg_holding_periods",
    "max_drawdown_pct",
    "max_drawdown_duration_bars",
    "sharpe",
    "sortino",
    "calmar",
    "trading_days",
    "equity_start",
    "equity_end",
    "equity_bars",
)

QUERYABLE = {
    "month",
    "timeframe",
    "signal_mode",
    "source",
    "variant",
    "config_hash",
}

ORDERABLE = {
    "net_pnl",
    "gross_pnl",
    "profit_factor",
    "total_trades",
    "win_rate",
    "sharpe",
    "max_drawdown_pct",
    "avg_trade_pnl",
    "fast_ema",
    "slow_ema",
    "angle_threshold",
    "angle_lookback",
    "created_at",
    "id",
}


def _connect(vault_path: str | Path) -> sqlite3.Connection:
    path = Path(vault_path)
    path.parent.mkdir(parents=True, exist_ok=True)
    conn = sqlite3.connect(path)
    conn.executescript(_SCHEMA)
    conn.execute("PRAGMA journal_mode = WAL")
    return conn


def record_run(
    *,
    vault_path: str | Path = DEFAULT_VAULT_PATH,
    source: str,
    month: str,
    timeframe: str,
    signal_mode: str,
    fast_ema: int,
    slow_ema: int,
    angle_threshold: float,
    angle_lookback: int,
    config_hash: str | None = None,
    slippage: str | None = None,
    experiment_id: str | None = None,
    variant: str | None = None,
    metrics: dict[str, Any] | None = None,
    equity_start: float | None = None,
    equity_end: float | None = None,
    equity_bars: int | None = None,
) -> int:
    """Insert one run and return its vault id."""
    m = metrics or {}
    values = (
        source,
        experiment_id,
        variant,
        month,
        timeframe,
        config_hash,
        signal_mode,
        int(fast_ema),
        int(slow_ema),
        float(angle_threshold),
        int(angle_lookback),
        slippage,
        m.get("total_trades"),
        m.get("win_rate"),
        m.get("gross_pnl"),
        m.get("net_pnl"),
        m.get("profit_factor"),
        m.get("avg_trade_pnl"),
        m.get("avg_holding_periods"),
        m.get("max_drawdown_pct"),
        m.get("max_drawdown_duration_bars"),
        m.get("sharpe"),
        m.get("sortino"),
        m.get("calmar"),
        m.get("trading_days"),
        equity_start,
        equity_end,
        equity_bars,
    )
    cols = "created_at, " + ", ".join(_COLUMNS)
    marks = "?, " + ", ".join("?" for _ in _COLUMNS)
    row = (datetime.now(timezone.utc).isoformat(),) + tuple(values)
    with closing(_connect(vault_path)) as conn, conn:
        cur = conn.execute(f"INSERT INTO runs ({cols}) VALUES ({marks})", row)
        return int(cur.lastrowid)


def query_runs(
    *,
    vault_path: str | Path = DEFAULT_VAULT_PATH,
    filters: dict[str, Any] | None = None,
    order_by: str = "net_pnl",
    ascending: bool = False,
    limit: int = 100,
) -> list[dict[str, Any]]:
    """Query recorded runs; every non-empty filter must be an exact match."""
    filters = filters or {}
    unknown = set(filters) - QUERYABLE
    if unknown:
        raise ValueError(f"unsupported vault filters: {sorted(unknown)}")
    if order_by not in ORDERABLE:
        raise ValueError(f"order_by must be one of {sorted(ORDERABLE)}")
    if not 1 <= limit <= 1000:
        raise ValueError("limit must be 1..1000")

    sql = "SELECT * FROM runs"
    if not Path(vault_path).exists():
        return []
    clauses, params = [], []
    for key, value in filters.items():
        if value not in (None, "", "0"):
            clauses.append(f"{key} = ?")
            params.append(value)
    if clauses:
        sql += " WHERE " + " AND ".join(clauses)
    sql += f" ORDER BY {order_by} {'ASC' if ascending else 'DESC'} LIMIT {limit}"
    with closing(_connect(vault_path)) as conn, conn:
        rows = conn.execute(sql, params).fetchall()
        cols = [d[0] for d in conn.execute("SELECT * FROM runs LIMIT 0").description]
    return [dict(zip(cols, row)) for row in rows]


def run_count(vault_path: str | Path = DEFAULT_VAULT_PATH) -> int:
    """Total recorded runs (0 when the vault does not exist yet)."""
    if not Path(vault_path).exists():
        return 0
    with closing(_connect(vault_path)) as conn:
        return int(conn.execute("SELECT COUNT(*) FROM runs").fetchone()[0])
