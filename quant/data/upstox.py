"""Upstox REST API client (read-only analytics token).

Phase 01: expired futures contract (NIFTY) resolution + 1-minute candle download.
The analytics token covers market data only — this client never places orders.

Reference endpoints:
- Instrument master (public): https://assets.upstox.com/market-quote/instruments/exchange/NSE.json.gz
- Expired future contracts: GET /v2/expired-instruments/future/contract
- Expired historical candles: GET /v2/expired-instruments/historical-candle/{key}/
  {interval}/{to_date}/{from_date}
- Historical candles V3 (active): GET /v3/historical-candle/{key}/{unit}/
  {interval}/{to_date}/{from_date}
"""

from __future__ import annotations

import gzip
import json
from datetime import date, datetime, timedelta
from typing import Any
from urllib.parse import quote

import httpx
import polars as pl

from quant.config import Settings, get_settings

UPSTOX_BASE_URL = "https://api.upstox.com"
UPSTOX_ASSETS_BASE = "https://assets.upstox.com/market-quote/instruments/exchange"
NIFTY_INDEX_KEY = "NSE_INDEX|Nifty 50"

INTERVAL_1_MINUTE = "1minute"
INTERVAL_30_MINUTE = "30minute"


class UpstoxError(RuntimeError):
    """Raised when the Upstox API returns a non-2xx response."""


def last_thursday_of_month(year: int, month: int) -> date:
    """Return the last Thursday of the month (NSE monthly futures expiry)."""
    if month == 12:
        next_month_first = date(year + 1, 1, 1)
    else:
        next_month_first = date(year, month + 1, 1)
    last_day = next_month_first - timedelta(days=1)
    offset = (last_day.weekday() - 3) % 7  # Thursday == 3
    return last_day - timedelta(days=offset)


def pick_active_nifty_futures(
    master: pl.DataFrame, *, year: int, month: int
) -> dict[str, Any] | None:
    """Pick the NIFTY futures contract that trades through a harvest month.

    Candidates: NSE_FO futures on NIFTY whose expiry is on/after the last day
    of the harvest month. We take the earliest such expiry (most-traded
    contract during the harvest month).

    ``master`` must have provably parsed ``expiry`` dates (see
    ``UpstoxClient._master_to_frame``).
    """
    df = master.filter(
        pl.col("segment").eq("NSE_FO"),
        pl.col("instrument_type").eq("FUT"),
        pl.col("underlying_symbol").str.to_uppercase().eq("NIFTY"),
    )
    if month == 12:
        last_day = date(year + 1, 1, 1) - timedelta(days=1)
    else:
        last_day = date(year, month + 1, 1) - timedelta(days=1)
    df = df.filter(pl.col("expiry") >= last_day)
    if df.is_empty():
        return None
    return df.sort("expiry").head(1).to_dicts()[0]


def _epoch_ms_to_date(epoch_ms: Any) -> date:
    """Convert an epoch timestamp (seconds or milliseconds) to a date."""
    value = int(epoch_ms)
    if value >= 10_000_000_000:  # milliseconds (year > 2286)
        value = value // 1000
    return datetime.fromtimestamp(value).date()


class UpstoxClient:
    """Minimal read-only Upstox API client for market data."""

    def __init__(self, settings: Settings | None = None) -> None:
        self.settings = settings or get_settings()
        self.settings.require_upstox_credentials()
        self._http = httpx.Client(
            base_url=UPSTOX_BASE_URL,
            headers={
                "Accept": "application/json",
                "Authorization": f"Bearer {self.settings.upstox_analytics_token}",
            },
            timeout=120.0,
        )

    def close(self) -> None:
        self._http.close()

    def __enter__(self) -> "UpstoxClient":
        return self

    def __exit__(self, *args: Any) -> None:
        self.close()

    ###
    # Instrument master (public file, no auth needed)
    ###

    @staticmethod
    def fetch_instrument_master(exchange: str = "NSE") -> list[dict[str, Any]]:
        """Download the BOD instrument master (gzip JSON) for one exchange."""
        url = f"{UPSTOX_ASSETS_BASE}/{exchange}.json.gz"
        response = httpx.get(url, timeout=120.0)
        if response.status_code >= 400:
            raise UpstoxError(
                f"Instrument master {exchange} failed: {response.status_code} {response.text[:300]}"
            )
        return json.loads(gzip.decompress(response.content))

    @staticmethod
    def _master_to_frame(instruments: list[dict[str, Any]]) -> pl.DataFrame:
        """Turn the BOD JSON list into a DataFrame with a parsed expiry column."""
        frame = pl.DataFrame(instruments)
        frame = frame.rename({str(c): str(c).lower() for c in frame.columns})
        if "expiry" in frame.columns:
            frame = frame.with_columns(
                pl.col("expiry").map_elements(_epoch_ms_to_date, return_dtype=pl.Date)
            )
        elif "segment" in frame.columns:
            frame = frame.with_columns(pl.lit(None, dtype=pl.Date).alias("expiry"))
        return frame

    def find_active_nifty_future(self, year: int, month: int) -> dict[str, Any] | None:
        """Resolve the NIFTY futures contract traded during a harvest month.

        Uses the public BOD instrument master (no auth): picks the monthly
        contract whose expiry is the earliest one on/after the last day of
        the harvest month — i.e. the contract that trades through that month.
        Expired contracts (Plus-only API) are NOT needed for this path.
        """
        master = self._master_to_frame(self.fetch_instrument_master())
        return pick_active_nifty_futures(master, year=year, month=month)

    ###
    # Expired futures contracts
    ###

    def get_expired_futures_contracts(
        self, underlying_key: str, expiry_date: date
    ) -> list[dict[str, Any]]:
        """GET /v2/expired-instruments/future/contract.

        Returns records whose ``instrument_key`` is the ``expired_instrument_key``
        (format ``<NSE_FO|token|DD-MM-YYYY>``) used by the candle endpoint.
        """
        url = (
            f"{UPSTOX_BASE_URL}/v2/expired-instruments/future/contract"
            f"?instrument_key={quote(underlying_key, safe='')}"
            f"&expiry_date={expiry_date.isoformat()}"
        )
        payload = self._get(url)
        data = payload.get("data") or []
        return data if isinstance(data, list) else [data]

    def find_nifty_future(self, expiry_date: date) -> dict[str, Any] | None:
        """Resolve the NIFTY index futures contract expiring on a given date."""
        contracts = self.get_expired_futures_contracts(NIFTY_INDEX_KEY, expiry_date)
        for contract in contracts:
            if str(contract.get("underlying_symbol", "")).upper() == "NIFTY":
                return contract
        return None

    ###
    # Candle data
    ###

    def get_expired_historical_candles(
        self,
        expired_instrument_key: str,
        *,
        interval: str = INTERVAL_1_MINUTE,
        from_date: date,
        to_date: date,
    ) -> pl.DataFrame:
        """GET /v2/expired-instruments/historical-candle/{key}/{interval}/{to}/{from}."""
        url = (
            f"{UPSTOX_BASE_URL}/v2/expired-instruments/historical-candle/"
            f"{quote(expired_instrument_key, safe='')}/{interval}"
            f"/{to_date.isoformat()}/{from_date.isoformat()}"
        )
        payload = self._get(url)
        candles = (payload.get("data") or {}).get("candles") or []
        return self._candles_to_frame(candles)

    def get_historical_candles_v3(
        self,
        instrument_key: str,
        *,
        unit: str = "minutes",
        interval: int = 1,
        from_date: date,
        to_date: date,
    ) -> pl.DataFrame:
        """GET /v3/historical-candle/{key}/{unit}/{interval}/{to}/{from} (active)."""
        url = (
            f"{UPSTOX_BASE_URL}/v3/historical-candle/"
            f"{quote(instrument_key, safe='')}/{unit}/{interval}"
            f"/{to_date.isoformat()}/{from_date.isoformat()}"
        )
        payload = self._get(url)
        candles = (payload.get("data") or {}).get("candles") or []
        return self._candles_to_frame(candles)

    @staticmethod
    def _candles_to_frame(candles: list[list[Any]]) -> pl.DataFrame:
        """Convert ``[ts, open, high, low, close, volume, oi]`` arrays.

        Timestamps are ISO-8601 with ``+05:30`` offset; the frame stores them
        as naive IST to match the canonical candle schema
        (``pl.Datetime("ms")``).
        """
        if not candles:
            return pl.DataFrame(
                schema={
                    "timestamp": pl.Datetime("ms"),
                    "open": pl.Float64,
                    "high": pl.Float64,
                    "low": pl.Float64,
                    "close": pl.Float64,
                    "volume": pl.Int64,
                    "open_interest": pl.Int64,
                }
            )
        frame = pl.DataFrame(
            {
                "timestamp": [row[0] for row in candles],
                "open": [float(row[1]) for row in candles],
                "high": [float(row[2]) for row in candles],
                "low": [float(row[3]) for row in candles],
                "close": [float(row[4]) for row in candles],
                "volume": [int(row[5]) for row in candles],
                "open_interest": [int(row[6]) if len(row) > 6 else 0 for row in candles],
            }
        )
        frame = frame.with_columns(
            pl.col("timestamp")
            .str.to_datetime(format="%Y-%m-%dT%H:%M:%S%z")
            .dt.convert_time_zone("Asia/Kolkata")
            .dt.replace_time_zone(None)
            .cast(pl.Datetime("ms"))
            .alias("timestamp")
        )
        return frame

    ###
    # HTTP plumbing
    ###

    def _get(self, url: str) -> dict[str, Any]:
        response = self._http.get(url)
        if response.status_code >= 400:
            raise UpstoxError(f"Request failed: {response.status_code} {response.text[:500]}")
        return response.json()
