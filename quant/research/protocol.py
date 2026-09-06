"""Pre-registered train/validation/test protocol (Phase 09).

Written and committed BEFORE any sweep runs, and never edited afterwards.
Everything here is a frozen constant, not a runtime computation, and its
hash is written to a per-campaign seal file the moment a campaign starts
(``seal_protocol``). No sweep, no agent, and no ranking step may read the
TEST split of either schedule until the final promotion gate, and even
then only once (``run_sweep.py --split test`` must refuse to run without
``--unseal-test`` plus the matching seal hash -- see the plan's Phase 8).

Two independent schedules:

- ``DISCOVERY_SPLITS`` -- index spot (NIFTY/BANKNIFTY/SENSEX), 2022-01
  through 2026-09. This is where parameter search and strategy discovery
  happen; it has real sample size (~1,150 sessions/instrument).
- ``CONFIRM_SPLITS`` -- NIFTY futures, the only cost-realistic data on
  disk (31 trading days total). Its test split is 8 days and CANNOT
  credibly gate anything statistically -- it exists only as a sanity
  check that a candidate's sign and rough magnitude survive real fills
  and the full India-futures cost model, not as a promotion criterion.

``MIN_TRADES`` is tiered, not a flat 100, because the event-driven SMC
strategies (S1/S3/S5) fire on a measured fraction of sessions -- on the
31 sessions available, a PDH/PDL sweep-and-fail fires on 60% of days and
an opening-range break-and-reverse on 68%, i.e. ~102 and ~115 events
projected over a 170-session test split, not 100+ for every family. This
basis is recorded here, before any sweep runs, precisely so it cannot be
adjusted after seeing results -- that would be exactly the p-hacking this
whole module exists to prevent.
"""

from __future__ import annotations

import json
from dataclasses import dataclass
from datetime import date
from pathlib import Path
from typing import Literal

from quant.research.run_card import hash_mapping

Split = Literal["train", "val", "test"]

DISCOVERY_SPLITS: dict[Split, tuple[date, date]] = {
    "train": (date(2022, 1, 1), date(2024, 12, 31)),  # ~740 sessions
    "val": (date(2025, 1, 1), date(2025, 12, 31)),  # ~245 sessions
    "test": (date(2026, 1, 1), date(2026, 9, 5)),  # ~170 sessions -- SEALED
}

CONFIRM_SPLITS: dict[Split, tuple[date, date]] = {
    "train": (date(2026, 7, 1), date(2026, 7, 31)),
    "test": (date(2026, 8, 3), date(2026, 8, 12)),  # 8 days -- sanity check, NOT a gate
}

EMBARGO_TRADING_DAYS = 1

# Measured basis (see module docstring): a flat 100-trade minimum on the
# TEST split would fail every event-driven SMC family on sample size
# alone, independent of any real edge.
MIN_TRADES: dict[Split, int] = {"train": 100, "val": 30, "test": 20}

MAX_ROUNDS = 3

PROTOCOL_VERSION = "2026-09-06"


def protocol_snapshot() -> dict[str, object]:
    """Everything that must be frozen before a campaign's first sweep."""
    return {
        "protocol_version": PROTOCOL_VERSION,
        "discovery_splits": {
            k: [d.isoformat() for d in v] for k, v in DISCOVERY_SPLITS.items()
        },
        "confirm_splits": {k: [d.isoformat() for d in v] for k, v in CONFIRM_SPLITS.items()},
        "embargo_trading_days": EMBARGO_TRADING_DAYS,
        "min_trades": dict(MIN_TRADES),
        "max_rounds": MAX_ROUNDS,
    }


def protocol_hash() -> str:
    return hash_mapping(protocol_snapshot())


@dataclass(frozen=True)
class CampaignSeal:
    """The tamper-evident record a campaign's test split is checked against."""

    campaign_id: str
    protocol_hash: str
    sealed_at: str  # ISO datetime, informational only
    test_unsealed: bool = False
    unsealed_at: str | None = None

    def to_dict(self) -> dict[str, object]:
        return {
            "campaign_id": self.campaign_id,
            "protocol_hash": self.protocol_hash,
            "sealed_at": self.sealed_at,
            "test_unsealed": self.test_unsealed,
            "unsealed_at": self.unsealed_at,
        }


def seal_path(campaign_id: str, *, root: str | Path = "data/results/search") -> Path:
    return Path(root) / campaign_id / "test_seal.json"


def seal_protocol(
    campaign_id: str,
    *,
    root: str | Path = "data/results/search",
    now: str,
) -> CampaignSeal:
    """Write a campaign's seal file. Must be called once, before round 1.

    Refuses to overwrite an existing seal with a DIFFERENT protocol hash
    (a campaign's rules cannot be quietly changed mid-run); re-sealing
    with an identical hash is a no-op that returns the existing seal.
    """
    path = seal_path(campaign_id, root=root)
    current_hash = protocol_hash()
    if path.exists():
        existing = json.loads(path.read_text(encoding="utf-8"))
        if existing["protocol_hash"] != current_hash:
            raise RuntimeError(
                f"campaign {campaign_id!r} was already sealed under a different "
                f"protocol (hash {existing['protocol_hash']} != {current_hash}); "
                "refusing to reseal. Start a new campaign_id if the protocol "
                "genuinely changed."
            )
        return CampaignSeal(**existing)
    seal = CampaignSeal(campaign_id=campaign_id, protocol_hash=current_hash, sealed_at=now)
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(seal.to_dict(), indent=2), encoding="utf-8")
    return seal


def load_seal(campaign_id: str, *, root: str | Path = "data/results/search") -> CampaignSeal:
    path = seal_path(campaign_id, root=root)
    if not path.exists():
        raise FileNotFoundError(
            f"no seal for campaign {campaign_id!r} at {path}; call seal_protocol() first"
        )
    return CampaignSeal(**json.loads(path.read_text(encoding="utf-8")))


def unseal_test(
    campaign_id: str,
    *,
    root: str | Path = "data/results/search",
    now: str,
    confirm_hash: str,
) -> CampaignSeal:
    """Mark a campaign's test split as opened. Callable exactly once.

    ``confirm_hash`` must match the current protocol hash -- this is the
    mechanical enforcement of "no re-tuning after unsealing": a caller
    cannot unseal without first proving it read the same protocol the
    seal was created under.
    """
    seal = load_seal(campaign_id, root=root)
    if confirm_hash != seal.protocol_hash:
        raise ValueError(
            f"confirm_hash {confirm_hash} does not match the sealed protocol hash "
            f"{seal.protocol_hash}; refusing to unseal"
        )
    if seal.test_unsealed:
        raise RuntimeError(
            f"campaign {campaign_id!r} test split was already unsealed at "
            f"{seal.unsealed_at}; the test split may be opened exactly once"
        )
    updated = CampaignSeal(
        campaign_id=seal.campaign_id,
        protocol_hash=seal.protocol_hash,
        sealed_at=seal.sealed_at,
        test_unsealed=True,
        unsealed_at=now,
    )
    seal_path(campaign_id, root=root).write_text(
        json.dumps(updated.to_dict(), indent=2), encoding="utf-8"
    )
    return updated
