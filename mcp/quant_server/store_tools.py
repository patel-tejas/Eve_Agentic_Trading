"""Tools over the caller's saved strategies (Phase 15, P2+).

Every tool here acts as the verified principal the gate bound to this call
(``auth.require_principal``) -- there is no ``user_id`` argument for a model
to fill in. Storage goes through ``store.store_for``, which uses the user's
own token so row-level security applies as well.

Versions are immutable: saving creates version 1, revising creates N+1 with
its parent recorded, and every backtest points at the exact version (and
``spec_hash``) it ran.
"""

from __future__ import annotations

from typing import Any

from mcp.quant_server.auth import require_principal
from mcp.quant_server.server import DEFAULT_PROCESSED_ROOT, _json_safe
from mcp.quant_server.store import StoreError, new_id, store_for
from mcp.quant_server.strategy_tools import backtest_payload, run_spec_backtest
from quant.strategies.spec import (
    SCHEMA_VERSION,
    StrategySpecV1,
    analyse,
    describe,
    parse_spec,
    spec_hash,
)
from quant.strategies.spec.diff import spec_diff

ENGINE_VERSION = "phase15"
_STATUSES = ("draft", "validated", "backtested", "paper", "archived")


def _store():
    return store_for(require_principal())


def _metrics_row(metrics: dict[str, Any]) -> dict[str, Any]:
    keys = ("total_trades", "net_pnl", "profit_factor", "win_rate", "max_drawdown_pct", "sharpe")
    return {k: metrics.get(k) for k in keys}


def _strategy_or_404(store, strategy_id: str) -> dict[str, Any]:
    row = store.get_strategy(strategy_id)
    if row is None:
        # Same message whether it does not exist or belongs to someone else.
        raise StoreError(f"no strategy {strategy_id} in your account")
    return row


def _version_row(store, strategy: dict[str, Any], version: int) -> dict[str, Any]:
    if version:
        row = store.get_version(strategy["id"], version)
    elif strategy.get("current_version_id"):
        row = store.get_version_by_id(strategy["current_version_id"])
    else:
        row = None
    if row is None:
        raise StoreError(f"strategy {strategy['id']} has no version {version or '(current)'}")
    return row


def _validation_blob(analysis) -> dict[str, Any]:
    return {
        "errors": [i.to_dict() for i in analysis.errors],
        "warnings": [i.to_dict() for i in analysis.warnings],
    }


# ------------------------------------------------------------------ read


def list_my_strategies(status: str = "") -> dict[str, object]:
    """List the signed-in user's saved strategies (newest first) with their
    status, current version and the latest backtest's headline numbers.
    ``status`` filters to draft|validated|backtested|paper|archived."""
    if status and status not in _STATUSES:
        raise ValueError(f"status must be one of {', '.join(_STATUSES)}")
    store = _store()
    rows = store.list_strategies(status or None)
    version_ids = [r["current_version_id"] for r in rows if r.get("current_version_id")]
    latest: dict[str, dict[str, Any]] = {}
    for bt in store.list_backtests(version_ids):
        latest.setdefault(bt["strategy_version_id"], bt)
    versions = {vid: store.get_version_by_id(vid) for vid in version_ids}
    out = []
    for r in rows:
        vid = r.get("current_version_id")
        v = versions.get(vid) if vid else None
        bt = latest.get(vid) if vid else None
        out.append(
            {
                "id": r["id"],
                "name": r["name"],
                "status": r["status"],
                "source": r.get("source"),
                "trial_count": r.get("trial_count", 0),
                "version": v["version"] if v else None,
                "summary": v["nl_summary"] if v else None,
                "spec_hash": v["spec_hash"] if v else None,
                "updated_at": r.get("updated_at"),
                "latest_backtest": (
                    {
                        "month": (bt.get("params") or {}).get("month"),
                        "kind": bt.get("kind"),
                        **_metrics_row(bt.get("metrics") or {}),
                        "created_at": bt.get("created_at"),
                    }
                    if bt
                    else None
                ),
            }
        )
    return _json_safe({"strategies": out, "count": len(out)})


def get_my_strategy(strategy_id: str, version: int = 0) -> dict[str, object]:
    """One saved strategy: the spec and template summary of ``version`` (0 =
    current), every version with its hash and a diff against its parent, and
    the backtests recorded on the shown version."""
    store = _store()
    strategy = _strategy_or_404(store, strategy_id)
    shown = _version_row(store, strategy, version)
    versions = store.list_versions(strategy_id)
    by_id = {v["id"]: v for v in versions}
    timeline = []
    for v in versions:
        parent = by_id.get(v.get("parent_version_id") or "")
        diff = None
        if parent is not None:
            diff = spec_diff(parse_spec(parent["spec"]), parse_spec(v["spec"]))["changes"]
        timeline.append(
            {
                "id": v["id"],
                "version": v["version"],
                "spec_hash": v["spec_hash"],
                "summary": v["nl_summary"],
                "created_at": v["created_at"],
                "changes": diff,
            }
        )
    backtests = [
        {
            "id": b["id"],
            "kind": b.get("kind"),
            "params": b.get("params"),
            "metrics": b.get("metrics"),
            "verdict": b.get("verdict"),
            "status": b.get("status"),
            "created_at": b.get("created_at"),
        }
        for b in store.list_backtests([shown["id"]])
    ]
    return _json_safe(
        {
            "strategy": {
                k: strategy.get(k)
                for k in ("id", "name", "description", "status", "source", "trial_count",
                          "paper_started_at", "created_at", "updated_at", "current_version_id")
            },
            "version": {
                "id": shown["id"],
                "version": shown["version"],
                "spec": shown["spec"],
                "spec_hash": shown["spec_hash"],
                "summary": shown["nl_summary"],
                "validation": shown.get("validation"),
                "is_current": shown["id"] == strategy.get("current_version_id"),
            },
            "versions": timeline,
            "backtests": backtests,
        }
    )


# ------------------------------------------------------------------ write


def save_strategy(name: str, spec: StrategySpecV1, source: str = "chat") -> dict[str, object]:
    """Save a strategy spec to the signed-in user's account as version 1.

    Idempotent: if the user already saved these exact rules (same spec_hash)
    the existing strategy is returned instead of a duplicate. A spec with
    errors is saved as a draft; a clean one as validated. ``source`` is
    chat|form|import. Only call this after the user asked to save.
    """
    if source not in ("chat", "form", "import"):
        raise ValueError("source must be chat|form|import")
    name = name.strip()
    if not 1 <= len(name) <= 80:
        raise ValueError("name must be 1-80 characters")
    store = _store()
    analysis = analyse(spec)
    digest = spec_hash(analysis.spec)
    existing = store.find_version_by_hash(digest)
    if existing is not None:
        strategy = store.get_strategy(existing["strategy_id"])
        return _json_safe(
            {
                "status": "exists",
                "message": "these exact rules are already saved",
                "strategy_id": existing["strategy_id"],
                "name": strategy["name"] if strategy else None,
                "version": existing["version"],
                "spec_hash": digest,
            }
        )
    if any(r["name"] == name for r in store.list_strategies()):
        raise StoreError(
            f"you already have a strategy named {name!r}; pick another name or "
            "revise that one with revise_strategy"
        )

    strategy_id, version_id = new_id(), new_id()
    status = "validated" if analysis.valid else "draft"
    store.insert_strategy(
        {
            "id": strategy_id,
            "user_id": store.user_id,
            "name": name,
            "description": analysis.spec.description,
            "status": status,
            "source": source,
        }
    )
    store.insert_version(
        {
            "id": version_id,
            "strategy_id": strategy_id,
            "user_id": store.user_id,
            "version": 1,
            "spec": analysis.spec.model_dump(mode="json"),
            "spec_schema_version": SCHEMA_VERSION,
            "spec_hash": digest,
            "nl_summary": describe(analysis.spec) if analysis.valid else "(has errors)",
            "validation": _validation_blob(analysis),
        }
    )
    store.update_strategy(strategy_id, {"current_version_id": version_id})
    return _json_safe(
        {
            "status": "saved",
            "strategy_id": strategy_id,
            "version_id": version_id,
            "version": 1,
            "strategy_status": status,
            "spec_hash": digest,
            "errors": [i.to_dict() for i in analysis.errors],
            "warnings": [i.to_dict() for i in analysis.warnings],
        }
    )


def revise_strategy(
    strategy_id: str, base_version: int, spec: StrategySpecV1
) -> dict[str, object]:
    """Save a new version of one of the user's strategies.

    ``base_version`` must be the version the change was made from (the
    current one); if someone saved a newer version meanwhile this fails
    instead of overwriting it. Returns the new version number and a diff of
    exactly what changed. Each revision counts as a trial.
    """
    store = _store()
    strategy = _strategy_or_404(store, strategy_id)
    current = _version_row(store, strategy, 0)
    if current["version"] != base_version:
        raise StoreError(
            f"stale base_version {base_version}: the current version is {current['version']}. "
            "Fetch it with get_my_strategy and re-apply the change."
        )
    analysis = analyse(spec)
    digest = spec_hash(analysis.spec)
    before = parse_spec(current["spec"])
    diff = spec_diff(before, analysis.spec)
    if digest == current["spec_hash"]:
        return _json_safe(
            {"status": "unchanged", "version": current["version"], "spec_hash": digest,
             "diff": diff}
        )
    version_id = new_id()
    new_version = max(v["version"] for v in store.list_versions(strategy_id)) + 1
    store.insert_version(
        {
            "id": version_id,
            "strategy_id": strategy_id,
            "user_id": store.user_id,
            "version": new_version,
            "spec": analysis.spec.model_dump(mode="json"),
            "spec_schema_version": SCHEMA_VERSION,
            "spec_hash": digest,
            "nl_summary": describe(analysis.spec) if analysis.valid else "(has errors)",
            "validation": _validation_blob(analysis),
            "parent_version_id": current["id"],
        }
    )
    updated = store.update_strategy(
        strategy_id,
        {
            "current_version_id": version_id,
            "status": "validated" if analysis.valid else "draft",
            "trial_count": int(strategy.get("trial_count") or 0) + 1,
        },
    )
    return _json_safe(
        {
            "status": "revised",
            "strategy_id": strategy_id,
            "version_id": version_id,
            "version": new_version,
            "strategy_status": updated["status"],
            "trial_count": updated["trial_count"],
            "spec_hash": digest,
            "diff": diff,
            "errors": [i.to_dict() for i in analysis.errors],
            "warnings": [i.to_dict() for i in analysis.warnings],
        }
    )


def backtest_saved_strategy(
    strategy_id: str,
    month: str = "2026-07",
    version: int = 0,
    processed_root: str = str(DEFAULT_PROCESSED_ROOT),
) -> dict[str, object]:
    """Backtest one of the user's saved strategies (``version`` 0 = current)
    over a research month and record the result against that exact version.
    Each run counts as a trial. Numbers come from the engine only."""
    store = _store()
    strategy = _strategy_or_404(store, strategy_id)
    row = _version_row(store, strategy, version)
    valid, _, result = run_spec_backtest(row["spec"], month, processed_root)
    payload = backtest_payload(valid, month, result, include_trades=False)
    trials = int(strategy.get("trial_count") or 0) + 1
    saved = store.insert_backtest(
        {
            "id": new_id(),
            "strategy_version_id": row["id"],
            "user_id": store.user_id,
            "kind": "in_sample",
            "params": {
                "month": month,
                "timeframe": valid.timeframe,
                "slippage": valid.execution.slippage,
                "lot_size": payload["lot_size"],
                "lots": payload["lots"],
            },
            "metrics": payload["metrics"],
            "verdict": {"trials": trials, "exit_reasons": payload["exit_reasons"]},
            "engine_version": ENGINE_VERSION,
            "data_version": month,
            "run_card_hash": row["spec_hash"],
            "status": "ok",
        }
    )
    patch: dict[str, Any] = {"trial_count": trials}
    if strategy["status"] in ("draft", "validated") and row["id"] == strategy.get(
        "current_version_id"
    ):
        patch["status"] = "backtested"
    updated = store.update_strategy(strategy_id, patch)
    return _json_safe(
        {
            **payload,
            "strategy_id": strategy_id,
            "version": row["version"],
            "backtest_id": saved["id"],
            "trial_count": updated["trial_count"],
            "strategy_status": updated["status"],
        }
    )


def archive_strategy(strategy_id: str) -> dict[str, object]:
    """Archive one of the user's strategies (Hisaab UI only, never chat)."""
    store = _store()
    _strategy_or_404(store, strategy_id)
    updated = store.update_strategy(strategy_id, {"status": "archived"})
    return _json_safe({"strategy_id": strategy_id, "status": updated["status"]})


STORE_TOOL_FUNCTIONS = (
    list_my_strategies,
    get_my_strategy,
    save_strategy,
    revise_strategy,
    backtest_saved_strategy,
    archive_strategy,
)
