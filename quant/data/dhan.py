"""DhanHQ REST API client.

Phase 01: authentication, instrument master, historical candle download.
Read-only access only — this client never places orders.
"""

from __future__ import annotations

from datetime import date
from typing import Any

import httpx
import polars as pl

from quant.config import Settings, get_settings

DHAN_BASE_URL = "https://api.dhan.co"
DHAN_MASTER_URL = "https://api.dhan.co/v2/instrument/{exchange_segment}"
DHAN_MASTER_CSV_FALLBACK = "https://images.dhan.co/api-data/api-scrip-master-detailed.csv"


class DhanError(RuntimeError):
    """Raised when the DhanHQ API returns a non-2xx response."""


class Interval:
    """Interval codes for /charts/intraday."""

    ONE_MINUTE = "1"
    FIVE_MINUTE = "5"
    FIFTEEN_MINUTE = "15"


class InstrumentType:
    """Instrument types per Annexure."""

    FUTIDX = "FUTIDX"  # Futures of Index
    FUTSTK = "FUTSTK"  # Futures of Stock


class DhanClient:
    """Minimal read-only DhanHQ API client.

    Docs reference: `dhan-api-docs.md` at the repository root.
    Data API rate limit: 5 req/sec, 100 000/day.
    """

    def __init__(self, settings: Settings | None = None) -> None:
        """Initialize required credentials and an HTTP session."""
        self.settings = settings or get_settings()
        self.settings.require_dhan_credentials()
        self._http = httpx.Client(
            base_url=DHAN_BASE_URL,
            headers={
                "access-token": self.settings.dhan_access_token,
                "client-id": self.settings.dhan_client_id,
            },
            timeout=120.0,
            follow_redirects=True,
        )

    ###
    # Session management
    ###

    def close(self) -> None:
        self._http.close()

    def __enter__(self) -> "DhanClient":
        return self

    def __exit__(self, *args: Any) -> None:
        self.close()

    ###
    # Instrument master
    ###

    def fetch_instrument_master(
        self, exchange_segment: str = "NSE_FNO", use_csv_fallback: bool = False
    ) -> pl.DataFrame:
        """Fetch the instrument master for one exchange segment.

        Primary: GET /v2/instrument/{exchangeSegment}
        Fallback: detailed CSV from https://images.dhan.co
        """
        if use_csv_fallback:
            return self._read_master_csv(DHAN_MASTER_CSV_FALLBACK)

        response = self._http.get(DHAN_MASTER_URL.format(exchange_segment=exchange_segment))
        if response.status_code >= 400:
            raise DhanError(
                f"Instrument master {exchange_segment} failed: "
                f"{response.status_code} {response.text[:300]}"
            )
        frames = [pl.read_csv(response.content)]
        return frames[0].rename({c: c.lower() for c in frames[0].columns})

    @staticmethod
    def _parse_master_csv(csv_bytes: bytes) -> pl.DataFrame:
        df = pl.read_csv(csv_bytes)
        return df.rename({c: c.lower() for c in df.columns})

    @classmethod
    def _read_master_csv(cls, url: str) -> pl.DataFrame:
        response = httpx.get(url, timeout=120.0, follow_redirects=True)
        response.raise_for_status()
        return cls._parse_master_csv(response.content)

    ###
    # Historical candles
    ###

    def get_intraday_candles(
        self,
        security_id: str,
        *,
        exchange_segment: str = "NSE_FNO",
        instrument_type: str = InstrumentType.FUTIDX,
        interval: str = Interval.ONE_MINUTE,
        from_date: date,
        to_date: date,
        open_interest: bool = True,
    ) -> pl.DataFrame:
        """Fetch intraday OHLCV candles via POST /v2/charts/intraday.

        Returns a Polars DataFrame with columns:
        timestamp (datetime, IST), open, high, low, close, volume, open_interest.
        """
        payload = {
            "securityId": str(security_id),
            "exchangeSegment": exchange_segment,
            "instrument": instrument_type,
            "interval": interval,
            "oi": "true" if open_interest else "false",
            "fromDate": from_date.isoformat(),
            "toDate": to_date.isoformat(),
        }
        response = self._http.post("/v2/charts/intraday", json=payload)
        if response.status_code >= 400:
            raise DhanError(
                f"Intraday candles failed for {security_id}: "
                f"{response.status_code} {response.text[:500]}"
            )
        data = response.json()
        if not isinstance(data, list) or not data:
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
        return self._candles_to_frame(data)

    @staticmethod
    def _candles_to_frame(data: list[dict[str, Any]]) -> pl.DataFrame:
        frame = pl.DataFrame(data)
        # Guard against missing optional columns
        for column in ("open_interest",):
            if column not in frame.columns:
                frame = frame.with_columns(pl.lit(0, dtype=pl.Int64).alias(column))
        if "timestamp" not in frame.columns:
            raise DhanError("Dhan response missing 'timestamp' column")

        # Dhan returns epoch time; detect seconds vs milliseconds
        max_epoch = int(frame["timestamp"].max())
        epoch_to_ms = 1000 if max_epoch < 10_000_000_000 else 1
        return frame.with_columns(
            (pl.col("timestamp") * epoch_to_ms).cast(pl.Datetime("ms")).alias("timestamp")
        )
