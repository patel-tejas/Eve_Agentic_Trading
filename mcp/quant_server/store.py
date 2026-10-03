"""Per-user strategy storage behind the gate (Phase 15, P2).

Production storage is Hisaab's Supabase project (tables ``algo_*``, see
Hisaab ``supabase_schema.sql`` section 4s). The engine talks to it through
PostgREST **with the user's own access token**, one client per request, so
row-level security applies to every read and write: if the gate ever had a
bug, or a model injected another user's ``strategy_id``, Postgres would still
refuse. Every query also filters ``user_id`` explicitly, as a second fence.

The service-role key is used for one thing only: inserting audit rows
(``algo_tool_audit`` has no insert policy for users).

``EVE_LOCAL_DEV=1`` (the stdio MCP server, Eve's local research console)
uses a SQLite stand-in with the same semantics and never touches production.
"""

from __future__ import annotations

import json
import os
import sqlite3
import threading
import uuid
from collections.abc import Callable
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Protocol

import httpx

from mcp.quant_server.audit import AuditRecord
from mcp.quant_server.auth import Principal

PROJECT_ROOT = Path(__file__).resolve().parents[2]
DEFAULT_LOCAL_STORE = PROJECT_ROOT / "data" / "local" / "strategies.sqlite"
REST_TIMEOUT_SECONDS = 10.0


class StoreError(ValueError):
    """A storage refusal the caller can act on (name taken, stale version...)."""


class StoreUnavailable(ValueError):
    pass


def _now() -> str:
    return datetime.now(timezone.utc).isoformat()


def new_id() -> str:
    return str(uuid.uuid4())


class StrategyStore(Protocol):
    user_id: str

    def list_strategies(self, status: str | None = None) -> list[dict[str, Any]]: ...
    def get_strategy(self, strategy_id: str) -> dict[str, Any] | None: ...
    def list_versions(self, strategy_id: str) -> list[dict[str, Any]]: ...
    def get_version(self, strategy_id: str, version: int) -> dict[str, Any] | None: ...
    def get_version_by_id(self, version_id: str) -> dict[str, Any] | None: ...
    def find_version_by_hash(self, spec_hash: str) -> dict[str, Any] | None: ...
    def insert_strategy(self, row: dict[str, Any]) -> dict[str, Any]: ...
    def insert_version(self, row: dict[str, Any]) -> dict[str, Any]: ...
    def update_strategy(self, strategy_id: str, patch: dict[str, Any]) -> dict[str, Any]: ...
    def insert_backtest(self, row: dict[str, Any]) -> dict[str, Any]: ...
    def list_backtests(self, version_ids: list[str]) -> list[dict[str, Any]]: ...
    def get_controls(self) -> list[dict[str, Any]]: ...
    def set_own_kill_switch(self, engaged: bool, reason: str | None) -> dict[str, Any]: ...


# ------------------------------------------------------------------ Supabase


class SupabaseStore:
    """PostgREST client acting as one user (their JWT, RLS applies)."""

    def __init__(
        self,
        url: str,
        apikey: str,
        access_token: str,
        user_id: str,
        client: httpx.Client | None = None,
    ) -> None:
        self.base = f"{url.rstrip('/')}/rest/v1"
        self.user_id = user_id
        self._client = client or httpx.Client(timeout=REST_TIMEOUT_SECONDS)
        self._headers = {
            "apikey": apikey,
            "authorization": f"Bearer {access_token}",
            "content-type": "application/json",
            "accept": "application/json",
        }

    def _req(
        self,
        method: str,
        table: str,
        *,
        params: dict[str, str] | None = None,
        body: Any = None,
        prefer: str | None = None,
    ) -> list[dict[str, Any]]:
        headers = dict(self._headers)
        if prefer:
            headers["prefer"] = prefer
        res = self._client.request(
            method,
            f"{self.base}/{table}",
            params=params,
            content=None if body is None else json.dumps(body),
            headers=headers,
        )
        if res.status_code >= 400:
            try:
                err = res.json()
                message = err.get("message") or err.get("hint") or res.text
                code = err.get("code")
            except ValueError:
                message, code = res.text, None
            if res.status_code in (401, 403) or code == "42501":
                raise PermissionError(f"storage refused the request: {message}")
            if res.status_code == 409 or code == "23505":
                raise StoreError(f"conflict: {message}")
            raise StoreError(message)
        if not res.content:
            return []
        data = res.json()
        return data if isinstance(data, list) else [data]

    def _mine(self, **filters: str) -> dict[str, str]:
        return {"user_id": f"eq.{self.user_id}", **filters}

    def list_strategies(self, status: str | None = None) -> list[dict[str, Any]]:
        params = self._mine(select="*", order="updated_at.desc")
        if status:
            params["status"] = f"eq.{status}"
        return self._req("GET", "algo_strategies", params=params)

    def get_strategy(self, strategy_id: str) -> dict[str, Any] | None:
        rows = self._req(
            "GET", "algo_strategies", params=self._mine(select="*", id=f"eq.{strategy_id}")
        )
        return rows[0] if rows else None

    def list_versions(self, strategy_id: str) -> list[dict[str, Any]]:
        return self._req(
            "GET",
            "algo_strategy_versions",
            params=self._mine(
                select="*", strategy_id=f"eq.{strategy_id}", order="version.desc"
            ),
        )

    def get_version(self, strategy_id: str, version: int) -> dict[str, Any] | None:
        rows = self._req(
            "GET",
            "algo_strategy_versions",
            params=self._mine(
                select="*", strategy_id=f"eq.{strategy_id}", version=f"eq.{version}"
            ),
        )
        return rows[0] if rows else None

    def get_version_by_id(self, version_id: str) -> dict[str, Any] | None:
        rows = self._req(
            "GET", "algo_strategy_versions", params=self._mine(select="*", id=f"eq.{version_id}")
        )
        return rows[0] if rows else None

    def find_version_by_hash(self, spec_hash: str) -> dict[str, Any] | None:
        rows = self._req(
            "GET",
            "algo_strategy_versions",
            params=self._mine(select="*", spec_hash=f"eq.{spec_hash}", limit="1",
                              order="created_at.asc"),
        )
        return rows[0] if rows else None

    def insert_strategy(self, row: dict[str, Any]) -> dict[str, Any]:
        return self._req(
            "POST", "algo_strategies", body=row, prefer="return=representation"
        )[0]

    def insert_version(self, row: dict[str, Any]) -> dict[str, Any]:
        return self._req(
            "POST", "algo_strategy_versions", body=row, prefer="return=representation"
        )[0]

    def update_strategy(self, strategy_id: str, patch: dict[str, Any]) -> dict[str, Any]:
        rows = self._req(
            "PATCH",
            "algo_strategies",
            params=self._mine(id=f"eq.{strategy_id}"),
            body=patch,
            prefer="return=representation",
        )
        if not rows:
            raise StoreError(f"strategy {strategy_id} not found")
        return rows[0]

    def insert_backtest(self, row: dict[str, Any]) -> dict[str, Any]:
        return self._req("POST", "algo_backtests", body=row, prefer="return=representation")[0]

    def list_backtests(self, version_ids: list[str]) -> list[dict[str, Any]]:
        if not version_ids:
            return []
        return self._req(
            "GET",
            "algo_backtests",
            params=self._mine(
                select="*",
                strategy_version_id=f"in.({','.join(version_ids)})",
                order="created_at.desc",
            ),
        )

    def get_controls(self) -> list[dict[str, Any]]:
        return self._req(
            "GET",
            "algo_trading_controls",
            params={"select": "*", "or": f"(user_id.is.null,user_id.eq.{self.user_id})"},
        )

    def set_own_kill_switch(self, engaged: bool, reason: str | None) -> dict[str, Any]:
        return self._req(
            "POST",
            "algo_trading_controls",
            params={"on_conflict": "user_id"},
            body={"user_id": self.user_id, "kill_switch": engaged, "reason": reason},
            prefer="resolution=merge-duplicates,return=representation",
        )[0]


# ------------------------------------------------------------------ SQLite


_SQLITE_SCHEMA = """
create table if not exists algo_strategies (
  id text primary key, user_id text not null, name text not null, description text,
  status text not null default 'draft', current_version_id text, source text not null,
  trial_count integer not null default 0, paper_started_at text,
  created_at text not null, updated_at text not null, unique (user_id, name));
create table if not exists algo_strategy_versions (
  id text primary key, strategy_id text not null, user_id text not null,
  version integer not null, spec text not null, spec_schema_version text not null,
  spec_hash text not null, nl_summary text not null, validation text,
  parent_version_id text, created_at text not null, unique (strategy_id, version));
create table if not exists algo_backtests (
  id text primary key, strategy_version_id text not null, user_id text not null,
  kind text not null default 'in_sample', params text not null, metrics text not null,
  verdict text, engine_version text, data_version text, run_card_hash text,
  status text not null, created_at text not null);
create table if not exists algo_trading_controls (
  id text primary key, user_id text unique, kill_switch integer not null default 0,
  reason text, updated_at text not null);
"""

_JSON_COLS = {"spec", "validation", "params", "metrics", "verdict"}


class SqliteStore:
    """Local-dev stand-in with the same per-user scoping and status guards."""

    _locks: dict[str, threading.Lock] = {}

    def __init__(self, path: str | Path, user_id: str) -> None:
        self.path = Path(path)
        self.user_id = user_id
        self.path.parent.mkdir(parents=True, exist_ok=True)
        self._lock = SqliteStore._locks.setdefault(str(self.path), threading.Lock())
        with self._conn() as db:
            db.executescript(_SQLITE_SCHEMA)

    def _conn(self) -> sqlite3.Connection:
        db = sqlite3.connect(self.path)
        db.row_factory = sqlite3.Row
        return db

    @staticmethod
    def _out(row: sqlite3.Row | None) -> dict[str, Any] | None:
        if row is None:
            return None
        out = dict(row)
        for col in _JSON_COLS & set(out):
            if out[col] is not None:
                out[col] = json.loads(out[col])
        if "kill_switch" in out:
            out["kill_switch"] = bool(out["kill_switch"])
        return out

    def _all(self, sql: str, args: tuple = ()) -> list[dict[str, Any]]:
        with self._lock, self._conn() as db:
            return [self._out(r) for r in db.execute(sql, args).fetchall()]  # type: ignore[misc]

    def _insert(self, table: str, row: dict[str, Any]) -> dict[str, Any]:
        row = {k: json.dumps(v) if k in _JSON_COLS and v is not None else v for k, v in row.items()}
        cols = ", ".join(row)
        marks = ", ".join("?" for _ in row)
        try:
            with self._lock, self._conn() as db:
                db.execute(f"insert into {table} ({cols}) values ({marks})", tuple(row.values()))
        except sqlite3.IntegrityError as exc:
            raise StoreError(f"conflict: {exc}") from exc
        return self._all(f"select * from {table} where id = ?", (row["id"],))[0]

    def list_strategies(self, status: str | None = None) -> list[dict[str, Any]]:
        sql = "select * from algo_strategies where user_id = ?"
        args: tuple = (self.user_id,)
        if status:
            sql += " and status = ?"
            args += (status,)
        return self._all(sql + " order by updated_at desc", args)

    def get_strategy(self, strategy_id: str) -> dict[str, Any] | None:
        rows = self._all(
            "select * from algo_strategies where user_id = ? and id = ?",
            (self.user_id, strategy_id),
        )
        return rows[0] if rows else None

    def list_versions(self, strategy_id: str) -> list[dict[str, Any]]:
        return self._all(
            "select * from algo_strategy_versions where user_id = ? and strategy_id = ? "
            "order by version desc",
            (self.user_id, strategy_id),
        )

    def get_version(self, strategy_id: str, version: int) -> dict[str, Any] | None:
        rows = self._all(
            "select * from algo_strategy_versions where user_id = ? and strategy_id = ? "
            "and version = ?",
            (self.user_id, strategy_id, version),
        )
        return rows[0] if rows else None

    def get_version_by_id(self, version_id: str) -> dict[str, Any] | None:
        rows = self._all(
            "select * from algo_strategy_versions where user_id = ? and id = ?",
            (self.user_id, version_id),
        )
        return rows[0] if rows else None

    def find_version_by_hash(self, spec_hash: str) -> dict[str, Any] | None:
        rows = self._all(
            "select * from algo_strategy_versions where user_id = ? and spec_hash = ? "
            "order by created_at limit 1",
            (self.user_id, spec_hash),
        )
        return rows[0] if rows else None

    def insert_strategy(self, row: dict[str, Any]) -> dict[str, Any]:
        if row.get("user_id") != self.user_id:
            raise PermissionError("cannot write another user's strategy")
        now = _now()
        return self._insert("algo_strategies", {"created_at": now, "updated_at": now, **row})

    def insert_version(self, row: dict[str, Any]) -> dict[str, Any]:
        if row.get("user_id") != self.user_id or self.get_strategy(row["strategy_id"]) is None:
            raise PermissionError("cannot add a version to another user's strategy")
        return self._insert("algo_strategy_versions", {"created_at": _now(), **row})

    def update_strategy(self, strategy_id: str, patch: dict[str, Any]) -> dict[str, Any]:
        old = self.get_strategy(strategy_id)
        if old is None:
            raise StoreError(f"strategy {strategy_id} not found")
        new = {**old, **patch}
        # Mirror private.guard_algo_strategy().
        if new["current_version_id"] != old["current_version_id"] and new["current_version_id"]:
            version = self.get_version_by_id(new["current_version_id"])
            if version is None or version["strategy_id"] != strategy_id:
                raise StoreError("current_version_id must be a version of this strategy")
        if new["trial_count"] < old["trial_count"]:
            raise StoreError("trial_count cannot decrease")
        if old["status"] == "paper" and new["current_version_id"] != old["current_version_id"]:
            new["status"] = "validated"
        if new["status"] == "paper" and old["status"] != "paper":
            ok = self._all(
                "select id from algo_backtests where strategy_version_id = ? and status = 'ok'",
                (new["current_version_id"],),
            )
            if not ok:
                raise StoreError("paper trading needs an ok backtest on the current version")
            if any(c["kill_switch"] for c in self.get_controls()):
                raise StoreError("a kill switch is engaged")
            new["paper_started_at"] = _now()
        if new["status"] != "paper":
            new["paper_started_at"] = None
        new["updated_at"] = _now()
        cols = [c for c in new if c != "id"]
        with self._lock, self._conn() as db:
            db.execute(
                f"update algo_strategies set {', '.join(f'{c} = ?' for c in cols)} "
                "where id = ? and user_id = ?",
                (*[new[c] for c in cols], strategy_id, self.user_id),
            )
        return self.get_strategy(strategy_id)  # type: ignore[return-value]

    def insert_backtest(self, row: dict[str, Any]) -> dict[str, Any]:
        if self.get_version_by_id(row["strategy_version_id"]) is None:
            raise PermissionError("cannot record a backtest on another user's version")
        return self._insert("algo_backtests", {"created_at": _now(), **row})

    def list_backtests(self, version_ids: list[str]) -> list[dict[str, Any]]:
        if not version_ids:
            return []
        marks = ", ".join("?" for _ in version_ids)
        return self._all(
            f"select * from algo_backtests where user_id = ? and strategy_version_id in ({marks}) "
            "order by created_at desc",
            (self.user_id, *version_ids),
        )

    def get_controls(self) -> list[dict[str, Any]]:
        return self._all(
            "select * from algo_trading_controls where user_id is null or user_id = ?",
            (self.user_id,),
        )

    def set_own_kill_switch(self, engaged: bool, reason: str | None) -> dict[str, Any]:
        with self._lock, self._conn() as db:
            db.execute(
                "insert into algo_trading_controls (id, user_id, kill_switch, reason, updated_at) "
                "values (?, ?, ?, ?, ?) on conflict(user_id) do update set "
                "kill_switch = excluded.kill_switch, reason = excluded.reason, "
                "updated_at = excluded.updated_at",
                (new_id(), self.user_id, int(engaged), reason, _now()),
            )
            if engaged:
                db.execute(
                    "update algo_strategies set status = 'validated', paper_started_at = null "
                    "where user_id = ? and status = 'paper'",
                    (self.user_id,),
                )
        return [c for c in self.get_controls() if c["user_id"] == self.user_id][0]


# ------------------------------------------------------------------ factory


def _supabase_settings() -> tuple[str, str] | None:
    url = os.environ.get("SUPABASE_URL", "").strip()
    key = (
        os.environ.get("SUPABASE_ANON_KEY", "").strip()
        or os.environ.get("SUPABASE_PUBLISHABLE_KEY", "").strip()
    )
    return (url, key) if url and key else None


def default_store_factory(principal: Principal) -> StrategyStore:
    if not principal.is_user:
        raise PermissionError("strategy storage needs a signed-in user")
    if principal.kind == "local_dev":
        path = os.environ.get("EVE_LOCAL_STORE_PATH", "").strip() or DEFAULT_LOCAL_STORE
        return SqliteStore(path, principal.user_id)  # type: ignore[arg-type]
    settings = _supabase_settings()
    if settings is None or not principal.access_token:
        raise StoreUnavailable(
            "strategy storage is not configured on the engine: set SUPABASE_URL and "
            "SUPABASE_ANON_KEY (Hisaab's NEXT_PUBLIC_SUPABASE_URL / _ANON_KEY values)"
        )
    url, key = settings
    return SupabaseStore(url, key, principal.access_token, principal.user_id)  # type: ignore[arg-type]


_factory: Callable[[Principal], StrategyStore] = default_store_factory


def store_for(principal: Principal) -> StrategyStore:
    return _factory(principal)


def set_store_factory(factory: Callable[[Principal], StrategyStore] | None) -> None:
    """Tests swap the backend here; ``None`` restores the default."""
    global _factory
    _factory = factory or default_store_factory


# ------------------------------------------------------------------ audit sink


class SupabaseAuditSink:
    """Mirror audit records into ``algo_tool_audit`` with the service role."""

    def __init__(self, url: str, service_key: str, client: httpx.Client | None = None) -> None:
        self.endpoint = f"{url.rstrip('/')}/rest/v1/algo_tool_audit"
        self._client = client or httpx.Client(timeout=3.0)
        self._headers = {
            "apikey": service_key,
            "authorization": f"Bearer {service_key}",
            "content-type": "application/json",
            "prefer": "return=minimal",
        }

    def write(self, record: AuditRecord) -> None:
        # Only real Supabase users have a profiles row to reference.
        if record.principal_kind != "user":
            return
        row = record.to_dict()
        row.pop("principal_kind", None)
        self._client.post(self.endpoint, content=json.dumps(row, default=str),
                          headers=self._headers)


def supabase_audit_sink() -> SupabaseAuditSink | None:
    url = os.environ.get("SUPABASE_URL", "").strip()
    key = os.environ.get("SUPABASE_SERVICE_ROLE_KEY", "").strip()
    if not url or not key:
        return None
    return SupabaseAuditSink(url, key)
