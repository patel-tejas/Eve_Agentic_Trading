"""Phase 13: C2026-09-REALDATA -- dated costs, NSE parsers, continuous
futures roll rule, and the two-session timing lag.

Each property here would silently corrupt a result rather than raise:
a stale STT rate, a lot-size unit slip, a roll on the wrong session, or a
one-day look-ahead from files that NSE publishes after the close.
"""

from __future__ import annotations

import io
import sys
import zipfile
from datetime import date, timedelta
from pathlib import Path

import numpy as np
import polars as pl
import pytest

from quant.backtest import india_costs
from quant.data.nse_archive import nifty_rows, normalise, parse_participant_oi
from quant.research.realdata_features import continuous_futures

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "scripts"))
from run_realdata_phase2 import backtest  # noqa: E402

# ------------------------------------------------------------ costs


class TestDatedCosts:
    @pytest.mark.parametrize(
        ("on", "rate"),
        [
            (date(2019, 6, 3), 0.000100),
            (date(2023, 3, 31), 0.000100),
            (date(2023, 4, 1), 0.000125),
            (date(2024, 9, 30), 0.000125),
            (date(2024, 10, 1), 0.000200),
            (date(2026, 3, 31), 0.000200),
            (date(2026, 4, 1), 0.000500),
        ],
    )
    def test_stt_schedule_boundaries(self, on: date, rate: float) -> None:
        assert india_costs.stt_sell_rate(on) == pytest.approx(rate)

    def test_round_trip_doubles_in_april_2026(self) -> None:
        before = india_costs.round_trip_bps(date(2026, 3, 31))
        after = india_costs.round_trip_bps(date(2026, 4, 1))
        assert after - before == pytest.approx(3.0, abs=1e-6)
        assert 5.8 < after < 6.3

    def test_cost_config_carries_the_regime(self) -> None:
        cfg = india_costs.cost_config_for(date(2026, 7, 1))
        assert cfg.stt_rate == pytest.approx(0.0005)
        assert cfg.exchange_rate == pytest.approx(0.0000173)
        assert cfg.stamp_rate == pytest.approx(0.00002)


# ------------------------------------------------------------ parsers


def _zip(csv_text: str) -> bytes:
    buf = io.BytesIO()
    with zipfile.ZipFile(buf, "w") as zf:
        zf.writestr("bhav.csv", csv_text)
    return buf.getvalue()


LEGACY = (
    "INSTRUMENT,SYMBOL,EXPIRY_DT,STRIKE_PR,OPTION_TYP,OPEN,HIGH,LOW,CLOSE,SETTLE_PR,"
    "CONTRACTS,VAL_INLAKH,OPEN_INT,CHG_IN_OI,TIMESTAMP,\n"
    "FUTIDX,NIFTY,25-Jan-2023,0,XX,100,110,90,105,105,10,52.5,5000,50,02-JAN-2023,\n"
    "FUTIDX,BANKNIFTY,25-Jan-2023,0,XX,1,1,1,1,1,1,1,1,1,02-JAN-2023,\n"
    "OPTIDX,NIFTY,25-Jan-2023,18000,CE,5,6,4,5,5,3,1,900,0,02-JAN-2023,\n"
    "OPTIDX,NIFTY,25-Jan-2023,18000,PE,5,6,4,5,5,3,1,1800,0,02-JAN-2023,\n"
)
UDIFF_HEAD = (
    "TradDt,BizDt,Sgmt,Src,FinInstrmTp,FinInstrmId,ISIN,TckrSymb,SctySrs,XpryDt,"
    "FininstrmActlXpryDt,StrkPric,OptnTp,FinInstrmNm,OpnPric,HghPric,LwPric,ClsPric,"
    "LastPric,PrvsClsgPric,UndrlygPric,SttlmPric,OpnIntrst,ChngInOpnIntrst,TtlTradgVol,"
    "TtlTrfVal,TtlNbOfTxsExctd,SsnId,NewBrdLotQty,Rmks,Rsvd1,Rsvd2,Rsvd3,Rsvd4\n"
)
UDIFF = UDIFF_HEAD + (
    "2025-01-02,2025-01-02,FO,NSE,IDF,1,,NIFTY,,2025-01-30,2025-01-30,,,X,"
    "100,110,90,105,104,99,100,105,1000,10,40,420000,5,F1,25,,,,,\n"
    "2025-01-02,2025-01-02,FO,NSE,IDF,2,,NIFTYNXT50,,2025-01-30,2025-01-30,,,X,"
    "1,1,1,1,1,1,1,1,1,1,1,1,1,F1,25,,,,,\n"
)


class TestNseParsers:
    def test_legacy_keeps_only_nifty_and_converts_lakhs(self) -> None:
        n = normalise(nifty_rows(_zip(LEGACY), "legacy"), date(2023, 1, 2))
        assert n.height == 3  # BANKNIFTY dropped
        fut = n.filter(pl.col("instrument") == "FUT").row(0, named=True)
        assert fut["value_rs"] == pytest.approx(52.5 * 1e5)  # VAL_INLAKH -> rupees
        assert fut["strike"] is None and fut["opt_type"] is None
        assert fut["expiry"] == date(2023, 1, 25)

    def test_udiff_exact_symbol_match(self) -> None:
        n = normalise(nifty_rows(_zip(UDIFF), "udiff"), date(2025, 1, 2))
        assert n.height == 1  # NIFTYNXT50 must not match NIFTY
        row = n.row(0, named=True)
        assert row["settle"] == pytest.approx(105.0)  # SttlmPric, not LastPric
        assert row["lot"] == pytest.approx(25.0)

    def test_participant_ratio_inputs(self) -> None:
        text = (
            '"Participant wise Open Interest",,,\n'
            "Client Type,Future Index Long,Future Index Short,a,b,c,d,e,f,g,h,i,j,k,l\n"
            "FII,60,40,1,1,1,1,1,1,1,1,1,1,100,100\n"
            "TOTAL,60,40,1,1,1,1,1,1,1,1,1,1,100,100\n"
        )
        p = parse_participant_oi(text, date(2023, 1, 2))
        fii = p.filter(pl.col("participant") == "FII").row(0, named=True)
        assert fii["fut_idx_long"] == 60 and fii["fut_idx_short"] == 40


# ---------------------------------------------------- roll and timing


def _sessions(n: int, start: date = date(2024, 1, 1)) -> list[date]:
    out, d = [], start
    while len(out) < n:
        if d.weekday() < 5:
            out.append(d)
        d += timedelta(days=1)
    return out


def _bhav(sessions: list[date], expiries: list[date]) -> pl.DataFrame:
    rows = []
    for i, d in enumerate(sessions):
        for k, ex in enumerate(expiries):
            if ex >= d:
                rows.append(
                    {
                        "date": d,
                        "instrument": "FUT",
                        "expiry": ex,
                        "settle": 100.0 + i + 0.5 * k,
                        "oi": 1.0,
                        "value_rs": 1.0,
                    }
                )
    return pl.DataFrame(rows)


class TestContinuousFutures:
    def test_roll_on_third_session_before_expiry(self) -> None:
        s = _sessions(30)
        near, nxt = s[20], s[29]
        cont = continuous_futures(_bhav(s, [near, nxt]))
        rolls = cont.filter(pl.col("roll_at_close"))["date"].to_list()
        # 3 sessions (s[18], s[19], s[20]) remain after the close of s[17]
        assert rolls == [s[17]]

    def test_returns_are_within_one_contract(self) -> None:
        s = _sessions(30)
        cont = continuous_futures(_bhav(s, [s[20], s[29]]))
        # every settle step is +1 in the synthetic data, whichever contract
        # is held; a cross-contract return would show the 0.5 basis jump
        rets = (cont["settle"] - cont["settle_prev"]).to_numpy()
        assert np.allclose(rets, 1.0)


class TestTimingLag:
    def _panel(self, n: int = 12, jump_at: int = 6) -> pl.DataFrame:
        s = _sessions(n)
        ret = np.zeros(n)
        ret[jump_at] = 0.10
        return pl.DataFrame(
            {"date": s, "fut_ret": ret, "roll_at_close": [False] * n, "settle": [24_000.0] * n}
        )

    def test_day_t_signal_earns_the_return_two_sessions_later(self) -> None:
        p = self._panel()
        e = np.zeros(p.height)
        e[4] = 1.0  # decided on day 4 -> entered at close 5 -> earns day 6
        assert backtest(p, e)["gross"].sum() == pytest.approx(0.10)

    def test_signal_on_the_eve_of_the_jump_cannot_capture_it(self) -> None:
        p = self._panel()
        e = np.zeros(p.height)
        e[5] = 1.0  # NSE files for day 5 appear after its close: too late
        assert backtest(p, e)["gross"].sum() == pytest.approx(0.0)

    def test_short_positions_pay_the_roll(self) -> None:
        p = self._panel().with_columns(roll_at_close=pl.Series([False] * 7 + [True] + [False] * 4))
        e = -np.ones(p.height)
        rolled = backtest(p, e)["cost"].to_numpy()[7]
        plain = backtest(self._panel(), e)["cost"].to_numpy()[7]
        assert rolled > 0 and plain == pytest.approx(0.0)
