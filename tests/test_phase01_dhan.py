"""Phase 01 unit tests: instrument filtering, candle normalization, contract metadata.

These tests do not touch the network.
"""

import polars as pl

from quant.data.dhan import DhanClient
from quant.data.download import normalize_candles
from quant.data.instruments import (
    FuturesContract,
    filter_nifty_futures,
    normalize_master,
    pick_contract,
)


def _master_with_nifty_futures() -> pl.DataFrame:
    return pl.DataFrame(
        {
            "security_id": ["101", "102", "103", "104"],
            "trading_symbol": [
                "NIFTY 29 JUL 2026",
                "NIFTY 27 AUG 2026",
                "BANKNIFTY 29 JUL 2026",
                "NIFTY 29 JUL 2026 CE",
            ],
            "underlying_symbol": ["NIFTY", "NIFTY", "BANKNIFTY", "NIFTY"],
            "instrument_type": ["FUTIDX", "FUTIDX", "FUTIDX", "OPTIDX"],
            "SM_EXPIRY_DATE": ["2026-07-30", "2026-08-27", "2026-07-30", "2026-07-30"],
            "LOT_SIZE": [50, 50, 25, 50],
            "TICK_SIZE": [0.05, 0.05, 0.05, 0.05],
            "segment": ["NSE_FNO"] * 4,
        }
    )


def test_pick_contract_july():
    master = _master_with_nifty_futures()
    contract = pick_contract(master, "2026-07-01")
    assert contract is not None
    assert contract.security_id == "101"
    assert contract.lot_size == 50
    assert contract.expiry.isoformat() == "2026-07-30"


def test_pick_contract_no_match():
    master = _master_with_nifty_futures()
    assert pick_contract(master, "2025-01-01") is None


def test_filter_nifty_futures():
    master = _master_with_nifty_futures()
    filtered = filter_nifty_futures(normalize_master(master))
    assert len(filtered) == 2  # both FUTIDX NIFTY rows
    assert "NIFTY" in set(filtered["underlying_symbol"])


def test_contract_to_dict():
    contract = FuturesContract(
        security_id="101",
        trading_symbol="NIFTY 29 JUL 2026",
        underlying_symbol="NIFTY",
        expiry="2026-07-30",
        lot_size=50,
        tick_size=0.05,
    )
    data = contract.to_dict()
    assert data["expiry"] == "2026-07-30"
    assert data["security_id"] == "101"


def test_normalize_candles_meta():
    raw = pl.DataFrame(
        {
            "timestamp": ["1722430800000", "1722430860000"],
            "open": [24500.0, 24510.0],
            "high": [24520.0, 24530.0],
            "low": [24490.0, 24500.0],
            "close": [24510.0, 24520.0],
            "volume": [100, 200],
            "open_interest": [12000, 12100],
        }
    )
    contract = FuturesContract(
        security_id="101",
        trading_symbol="NIFTY 29 JUL 2026",
        underlying_symbol="NIFTY",
        expiry="2026-07-30",
        lot_size=50,
        tick_size=0.05,
    )
    frame = normalize_candles(raw, contract)
    assert frame["instrument"].to_list() == ["NIFTY_FUT", "NIFTY_FUT"]
    assert frame["security_id"].to_list() == ["101", "101"]
    assert frame["expiry"].dtype == pl.Date
    assert frame["lot_size"].to_list() == [50, 50]


def test_epoch_sec_vs_ms():
    """Candle epoch timestamps must convert to sensible datetimes."""

    frame = DhanClient._candles_to_frame(
        [
            {
                "timestamp": 1720000000000,
                "open": 1.0,
                "high": 2.0,
                "low": 0.5,
                "close": 1.5,
                "volume": 10,
                "open_interest": 5,
            }
        ]
    )
    assert frame["timestamp"].dt.year().first() == 2024  # near epoch 1.7e12
    assert frame["timestamp"].dtype == pl.Datetime("ms")
