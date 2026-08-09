"""Phase 01 unit tests: Upstox client (expired contracts, candles, download).

These tests do not touch the network.
"""

from datetime import date, datetime

import polars as pl

from quant.data.download import download_nifty_futures_upstox, upstox_contract_to_futures
from quant.data.instruments import FuturesContract
from quant.data.upstox import (
    UpstoxClient,
    _epoch_ms_to_date,
    last_thursday_of_month,
    pick_active_nifty_futures,
)


def _master_sample() -> pl.DataFrame:
    return pl.DataFrame(
        {
            "segment": ["NSE_FO"] * 3,
            "instrument_type": ["FUT"] * 3,
            "underlying_symbol": ["NIFTY"] * 3,
            "instrument_key": ["NSE_FO|100", "NSE_FO|58072", "NSE_FO|68407"],
            "expiry": [date(2026, 7, 30), date(2026, 8, 25), date(2026, 9, 29)],
            "trading_symbol": ["NIFTY FUT 30 JUL 26", "NIFTY FUT 25 AUG 26", "NIFTY FUT 29 SEP 26"],
            "lot_size": [65, 65, 65],
            "tick_size": [10.0, 10.0, 10.0],
        }
    )


def test_pick_active_nifty_future_july_harvest():
    master = _master_sample()
    record = pick_active_nifty_futures(master, year=2026, month=7)
    assert record is not None
    assert record["instrument_key"] == "NSE_FO|58072"
    assert record["expiry"] == date(2026, 8, 25)


def test_pick_active_nifty_future_no_match():
    only_options = pl.DataFrame(
        {
            "segment": ["NSE_FO"],
            "instrument_type": ["CE"],
            "underlying_symbol": ["NIFTY"],
            "expiry": [date(2026, 8, 25)],
        }
    )
    assert pick_active_nifty_futures(only_options, year=2026, month=7) is None


def test_last_thursday_of_month():
    assert last_thursday_of_month(2026, 7) == date(2026, 7, 30)
    assert last_thursday_of_month(2026, 8) == date(2026, 8, 27)
    assert last_thursday_of_month(2026, 12) == date(2026, 12, 31)
    assert last_thursday_of_month(2026, 2) == date(2026, 2, 26)


def test_epoch_ms_to_date():
    assert _epoch_ms_to_date(2111423399000) == date(2036, 11, 27)
    assert _epoch_ms_to_date(2111423399) == date(2036, 11, 27)


def test_candles_to_frame_parses_iso_timestamps():
    candles = [
        ["2026-07-01T09:15:00+05:30", 24501.0, 24520.0, 24495.0, 24510.0, 1200, 30240],
        ["2026-07-01T09:16:00+05:30", 24510.0, 24530.0, 24500.0, 24525.0, 900, 30241],
    ]
    frame = UpstoxClient._candles_to_frame(candles)
    assert frame["timestamp"].dtype == pl.Datetime("ms")
    assert frame["timestamp"][0] == datetime(2026, 7, 1, 9, 15)
    assert frame["open"].to_list() == [24501.0, 24510.0]
    assert frame["volume"].to_list() == [1200, 900]
    assert frame["open_interest"].to_list() == [30240, 30241]


def test_candles_to_frame_empty():
    frame = UpstoxClient._candles_to_frame([])
    assert frame.is_empty()
    assert frame["timestamp"].dtype == pl.Datetime("ms")


def test_upstox_contract_to_futures():
    record = {
        "name": "NIFTY",
        "segment": "NSE_FO",
        "exchange": "NSE",
        "expiry": "2026-07-30",
        "instrument_key": "NSE_FO|54452|30-07-2026",
        "exchange_token": "54452",
        "trading_symbol": "NIFTY FUT 30 JUL 26",
        "tick_size": 10,
        "lot_size": 75,
        "instrument_type": "FUT",
        "freeze_quantity": 1800,
        "underlying_key": "NSE_INDEX|Nifty 50",
        "underlying_symbol": "NIFTY",
        "minimum_lot": 75,
    }
    contract = upstox_contract_to_futures(record)
    assert isinstance(contract, FuturesContract)
    assert contract.security_id == "NSE_FO|54452|30-07-2026"
    assert contract.expiry.isoformat() == "2026-07-30"
    assert contract.lot_size == 75
    assert contract.tick_size == 10.0
    assert contract.exchange_segment == "NSE_FO"


def test_download_pipeline_writes_parquet(tmp_path, monkeypatch):
    class FakeUpstox:
        def find_active_nifty_future(self, year, month):
            return {
                "expiry": "2026-08-25",
                "instrument_key": "NSE_FO|58072",
                "trading_symbol": "NIFTY FUT 25 AUG 26",
                "underlying_symbol": "NIFTY",
                "lot_size": 65,
                "tick_size": 10,
                "segment": "NSE_FO",
                "instrument_type": "FUT",
            }

        def get_historical_candles_v3(self, key, *, unit, interval, from_date, to_date):
            return pl.DataFrame(
                {
                    "timestamp": [
                        "2026-07-01T09:15:00+05:30",
                        "2026-07-01T09:16:00+05:30",
                    ],
                    "open": [24501.0, 24510.0],
                    "high": [24520.0, 24530.0],
                    "low": [24495.0, 24500.0],
                    "close": [24510.0, 24525.0],
                    "volume": [1200, 900],
                    "open_interest": [30240, 30241],
                }
            )

    result = download_nifty_futures_upstox(
        year=2026, month=7, out_dir=tmp_path, client=FakeUpstox()
    )
    assert result["candles"] == 2
    assert result["parquet_path"].exists()
    assert result["metadata_path"].exists()
    frame = pl.read_parquet(result["parquet_path"])
    assert frame["instrument"].to_list() == ["NIFTY_FUT", "NIFTY_FUT"]
    assert frame["expiry"].dtype == pl.Date
    assert frame["security_id"].to_list() == ["NSE_FO|58072"] * 2
    import json

    metadata = json.loads(result["metadata_path"].read_text())
    assert metadata["expiry"] == "2026-08-25"
    assert metadata["lot_size"] == 65
    assert metadata["research"]["harvest_month"] == 7
    assert metadata["research"]["provider"] == "upstox"
