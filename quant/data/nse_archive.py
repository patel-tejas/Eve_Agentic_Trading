"""NSE public archives: F&O bhavcopy (NIFTY rows) and participant-wise OI.

Both are published by NSE after the close of the trading day they
describe, which is why anything built on them must act at t+1 at the
earliest (see the C2026-09-REALDATA pre-registration).

Measured reachability (2026-09-28): bhavcopy is served from 2016-01 on
(2015 and earlier return 403); participant OI from 2012-01 on. The
bhavcopy format changed on 2024-07-08 from the legacy ``foDDMONYYYYbhav``
file to the UDiFF ``BhavCopy_NSE_FO_...`` file; both are handled here and
normalised to one schema.

Units, which are easy to get wrong:
- ``oi`` is in UNITS (shares of the index), not contracts.
- ``contracts`` (legacy ``CONTRACTS`` / UDiFF ``TtlTradgVol``) is a count
  of contracts, and the lot size differs across expiries on the same day
  (e.g. 25 vs 75 in January 2025). Use ``value_rs`` or ``oi * settle``
  for anything that must be comparable across time.
- Participant OI is in contracts summed over ALL index futures, so only
  ratios (long / (long + short)) are meaningful.
"""

from __future__ import annotations

import io
import zipfile
from datetime import date

import polars as pl

UDIFF_SWITCH = date(2024, 7, 8)
MONTHS = ["JAN", "FEB", "MAR", "APR", "MAY", "JUN", "JUL", "AUG", "SEP", "OCT", "NOV", "DEC"]
HEADERS = {
    "User-Agent": (
        "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 "
        "(KHTML, like Gecko) Chrome/126.0 Safari/537.36"
    ),
    "Accept": "*/*",
    "Referer": "https://www.nseindia.com/",
}


def legacy_bhav_url(d: date) -> str:
    mon = MONTHS[d.month - 1]
    return (
        "https://archives.nseindia.com/content/historical/DERIVATIVES/"
        f"{d.year}/{mon}/fo{d.day:02d}{mon}{d.year}bhav.csv.zip"
    )


def udiff_bhav_url(d: date) -> str:
    return (
        "https://nsearchives.nseindia.com/content/fo/"
        f"BhavCopy_NSE_FO_0_0_0_{d:%Y%m%d}_F_0000.csv.zip"
    )


def bhav_urls(d: date) -> list[tuple[str, str]]:
    """(format, url) candidates, most likely first."""
    legacy, udiff = ("legacy", legacy_bhav_url(d)), ("udiff", udiff_bhav_url(d))
    return [udiff, legacy] if d >= UDIFF_SWITCH else [legacy, udiff]


def participant_oi_url(d: date) -> str:
    return f"https://archives.nseindia.com/content/nsccl/fao_participant_oi_{d:%d%m%Y}.csv"


def _read_zip_csv(blob: bytes) -> pl.DataFrame:
    with zipfile.ZipFile(io.BytesIO(blob)) as zf:
        name = next(n for n in zf.namelist() if n.lower().endswith(".csv"))
        raw = zf.read(name)
    df = pl.read_csv(io.BytesIO(raw), infer_schema_length=0, truncate_ragged_lines=True)
    keep = [c for c in df.columns if c.strip() and not c.startswith("_")]
    return df.select(keep).rename({c: c.strip() for c in keep})


def nifty_rows(blob: bytes, fmt: str) -> pl.DataFrame:
    """Raw NIFTY index-futures and index-options rows, all columns as text."""
    df = _read_zip_csv(blob)
    if fmt == "legacy":
        df = df.with_columns(pl.col(c).str.strip_chars() for c in ("INSTRUMENT", "SYMBOL"))
        out = df.filter(
            (pl.col("SYMBOL") == "NIFTY") & pl.col("INSTRUMENT").is_in(["FUTIDX", "OPTIDX"])
        )
    else:
        df = df.with_columns(pl.col(c).str.strip_chars() for c in ("TckrSymb", "FinInstrmTp"))
        out = df.filter(
            (pl.col("TckrSymb") == "NIFTY") & pl.col("FinInstrmTp").is_in(["IDF", "IDO"])
        )
    return out.with_columns(pl.lit(fmt).alias("_format"))


def _f(col: str) -> pl.Expr:
    return pl.col(col).str.strip_chars().replace("", None).cast(pl.Float64, strict=False)


def normalise(raw: pl.DataFrame, trade_date: date) -> pl.DataFrame:
    """One schema for both formats. See the module docstring for units."""
    fmt = raw["_format"][0]
    if fmt == "legacy":
        out = raw.select(
            pl.when(pl.col("INSTRUMENT") == "FUTIDX")
            .then(pl.lit("FUT"))
            .otherwise(pl.lit("OPT"))
            .alias("instrument"),
            pl.col("EXPIRY_DT")
            .str.strip_chars()
            .str.to_date("%d-%b-%Y", strict=False)
            .alias("expiry"),
            _f("STRIKE_PR").alias("strike"),
            pl.col("OPTION_TYP").str.strip_chars().alias("opt_type"),
            _f("OPEN").alias("open"),
            _f("HIGH").alias("high"),
            _f("LOW").alias("low"),
            _f("CLOSE").alias("close"),
            _f("SETTLE_PR").alias("settle"),
            _f("CONTRACTS").alias("contracts"),
            (_f("VAL_INLAKH") * 1e5).alias("value_rs"),
            _f("OPEN_INT").alias("oi"),
            _f("CHG_IN_OI").alias("chg_oi"),
            pl.lit(None, dtype=pl.Float64).alias("lot"),
            pl.lit(None, dtype=pl.Float64).alias("underlying"),
        )
    else:
        out = raw.select(
            pl.when(pl.col("FinInstrmTp") == "IDF")
            .then(pl.lit("FUT"))
            .otherwise(pl.lit("OPT"))
            .alias("instrument"),
            pl.col("XpryDt")
            .str.strip_chars()
            .str.to_date("%Y-%m-%d", strict=False)
            .alias("expiry"),
            _f("StrkPric").alias("strike"),
            pl.col("OptnTp").str.strip_chars().alias("opt_type"),
            _f("OpnPric").alias("open"),
            _f("HghPric").alias("high"),
            _f("LwPric").alias("low"),
            _f("ClsPric").alias("close"),
            _f("SttlmPric").alias("settle"),
            _f("TtlTradgVol").alias("contracts"),
            _f("TtlTrfVal").alias("value_rs"),
            _f("OpnIntrst").alias("oi"),
            _f("ChngInOpnIntrst").alias("chg_oi"),
            _f("NewBrdLotQty").alias("lot"),
            _f("UndrlygPric").alias("underlying"),
        )
    is_fut = pl.col("instrument") == "FUT"
    out = out.with_columns(
        pl.when(is_fut).then(None).otherwise(pl.col("opt_type")).alias("opt_type"),
        pl.when(is_fut).then(None).otherwise(pl.col("strike")).alias("strike"),
    )
    return out.with_columns(pl.lit(trade_date).alias("date")).select(
        "date",
        "instrument",
        "expiry",
        "strike",
        "opt_type",
        "open",
        "high",
        "low",
        "close",
        "settle",
        "contracts",
        "value_rs",
        "oi",
        "chg_oi",
        "lot",
        "underlying",
    )


PARTICIPANT_COLS = [
    "fut_idx_long",
    "fut_idx_short",
    "fut_stk_long",
    "fut_stk_short",
    "opt_idx_call_long",
    "opt_idx_put_long",
    "opt_idx_call_short",
    "opt_idx_put_short",
    "opt_stk_call_long",
    "opt_stk_put_long",
    "opt_stk_call_short",
    "opt_stk_put_short",
    "total_long",
    "total_short",
]
PARTICIPANTS = {"CLIENT", "DII", "FII", "PRO", "TOTAL"}


def parse_participant_oi(text: str, trade_date: date) -> pl.DataFrame:
    """Parse the 5-row participant table by position; header wording varies."""
    rows = []
    for line in text.splitlines():
        cells = [c.strip().strip('"').strip() for c in line.split(",")]
        if not cells or cells[0].upper() not in PARTICIPANTS:
            continue
        nums: list[float | None] = []
        for c in cells[1:15]:
            try:
                nums.append(float(c.replace("\t", "")))
            except ValueError:
                nums.append(None)
        if len(nums) == 14:
            rows.append(
                {
                    "date": trade_date,
                    "participant": cells[0].upper(),
                    **dict(zip(PARTICIPANT_COLS, nums)),
                }
            )
    return pl.DataFrame(rows) if rows else pl.DataFrame()
