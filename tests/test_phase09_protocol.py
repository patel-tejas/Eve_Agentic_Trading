"""Phase 09: pre-registered protocol -- splits, seal, unseal-once."""

from __future__ import annotations

import pytest

from quant.research.protocol import (
    CONFIRM_SPLITS,
    DISCOVERY_SPLITS,
    MIN_TRADES,
    protocol_hash,
    seal_protocol,
    unseal_test,
)


def test_discovery_splits_do_not_overlap():
    train_end = DISCOVERY_SPLITS["train"][1]
    val_start, val_end = DISCOVERY_SPLITS["val"]
    test_start = DISCOVERY_SPLITS["test"][0]
    assert train_end < val_start
    assert val_end < test_start


def test_confirm_splits_do_not_overlap():
    train_end = CONFIRM_SPLITS["train"][1]
    test_start = CONFIRM_SPLITS["test"][0]
    assert train_end < test_start


def test_min_trades_tiered_not_flat():
    # A flat 100 would fail every event-driven family on sample size
    # alone; the test minimum must be lower than train's.
    assert MIN_TRADES["test"] < MIN_TRADES["train"]
    assert MIN_TRADES["val"] < MIN_TRADES["train"]


def test_seal_then_unseal_once(tmp_path):
    campaign = "TEST-CAMPAIGN-1"
    seal = seal_protocol(campaign, root=tmp_path, now="2026-09-06T00:00:00")
    assert seal.test_unsealed is False

    updated = unseal_test(
        campaign, root=tmp_path, now="2026-09-07T00:00:00", confirm_hash=protocol_hash()
    )
    assert updated.test_unsealed is True

    with pytest.raises(RuntimeError, match="already unsealed"):
        unseal_test(
            campaign, root=tmp_path, now="2026-09-08T00:00:00", confirm_hash=protocol_hash()
        )


def test_unseal_rejects_wrong_hash(tmp_path):
    campaign = "TEST-CAMPAIGN-2"
    seal_protocol(campaign, root=tmp_path, now="2026-09-06T00:00:00")
    with pytest.raises(ValueError, match="does not match"):
        unseal_test(campaign, root=tmp_path, now="2026-09-07T00:00:00", confirm_hash="deadbeef")


def test_reseal_with_same_hash_is_noop(tmp_path):
    campaign = "TEST-CAMPAIGN-3"
    first = seal_protocol(campaign, root=tmp_path, now="2026-09-06T00:00:00")
    second = seal_protocol(campaign, root=tmp_path, now="2026-09-06T01:00:00")
    assert first.protocol_hash == second.protocol_hash
    assert first.sealed_at == second.sealed_at  # not overwritten
