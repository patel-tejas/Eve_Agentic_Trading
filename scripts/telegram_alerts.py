"""Signal alerts to Telegram.

Poll the live NIFTY futures intraday feed (Dhan), resample to the
configured timeframe, run the deterministic EMA strategy and push every
new BUY/SELL signal to a Telegram chat. All numbers come from the quant
engine — this script only moves messages.

Env (add to .env):
    TELEGRAM_BOT_TOKEN, TELEGRAM_CHAT_ID

Usage:
    uv run python scripts/telegram_alerts.py --once          # single check
    uv run python scripts/telegram_alerts.py --interval 300  # poll loop
    uv run python scripts/telegram_alerts.py --no-send       # dry run
"""

from __future__ import annotations

import argparse
import json
import os
import sys
import time
from datetime import date, datetime, timezone
from pathlib import Path

import httpx
import polars as pl

from quant.candles.aggregation import aggregate_candles
from quant.config import get_settings
from quant.data.dhan import DhanClient, InstrumentType, Interval
from quant.data.instruments import filter_nifty_futures, pick_contract
from quant.strategies.ema_9_15 import StrategyConfig, generate_signals

PROJECT_ROOT = Path(__file__).resolve().parents[1]
STATE_PATH = PROJECT_ROOT / "data" / "vault" / "telegram_state.json"

TELEGRAM_API = "https://api.telegram.org"


def _bot_token() -> str:
    return os.environ.get("TELEGRAM_BOT_TOKEN", "")


def _chat_id() -> str:
    return os.environ.get("TELEGRAM_CHAT_ID", "")


def _load_state() -> dict[str, object]:
    if not STATE_PATH.exists():
        return {}
    return json.loads(STATE_PATH.read_text(encoding="utf-8"))


def _save_state(state: dict[str, object]) -> None:
    STATE_PATH.parent.mkdir(parents=True, exist_ok=True)
    STATE_PATH.write_text(json.dumps(state, indent=2), encoding="utf-8")


def fetch_live_candles(settings: object, tf_minutes: int) -> pl.DataFrame:
    """Today's NIFTY futures 1m candles from Dhan, resampled to tf_minutes."""
    with DhanClient(settings) as client:
        master = client.fetch_instrument_master("NSE_FNO")
        contracts = filter_nifty_futures(master)
        contract = pick_contract(contracts, as_of=date.today())
        candles = client.get_intraday_candles(
            str(contract.security_id),
            instrument_type=InstrumentType.FUTIDX,
            interval=Interval.ONE_MINUTE,
            from_date=date.today(),
            to_date=date.today(),
        )
    if candles.height == 0:
        raise ValueError("no intraday candles for today (market closed?)")
    return aggregate_candles(candles, tf_minutes)


def send_telegram(token: str, chat_id: str, text: str, *, dry_run: bool) -> None:
    if dry_run or not token or not chat_id:
        print(f"[dry-run] would send to {chat_id or '<none>'}:\n{text}\n")
        return
    response = httpx.post(
        f"{TELEGRAM_API}/bot{token}/sendMessage",
        json={"chat_id": chat_id, "text": text, "parse_mode": "Markdown"},
        timeout=15,
    )
    response.raise_for_status()


def check_once(
    *,
    dry_run: bool,
    timeframe: str,
    fast_ema: int,
    slow_ema: int,
    angle_threshold: float,
    angle_lookback: int,
    signal_mode: str,
    min_bars: int,
) -> None:
    settings = get_settings()
    state = _load_state()
    day_key = date.today().isoformat()
    day_state = state.get(day_key, {})
    if not isinstance(day_state, dict):
        day_state = {}

    tf_minutes = int(timeframe.replace("m", ""))
    candles = fetch_live_candles(settings, tf_minutes)
    if candles.height < min_bars:
        print(f"only {candles.height} bars so far (need {min_bars}) — nothing to evaluate")
        return

    signals = generate_signals(
        candles,
        config=StrategyConfig(
            fast_ema=fast_ema,
            slow_ema=slow_ema,
            angle_threshold=angle_threshold,
            angle_lookback=angle_lookback,
            signal_mode=signal_mode,
        ),
        timeframe=timeframe,
    )
    events = (
        signals.filter(pl.col("signal_type") != "HOLD")
        .sort("timestamp")
        .select("timestamp", "signal_type", "candle_close")
    )
    if events.height == 0:
        print(f"{day_key} {timeframe}: no signals")
        return

    last_sent = day_state.get(timeframe)
    last_seen_dt = (
        datetime.fromisoformat(last_sent).replace(tzinfo=timezone.utc)
        if last_sent
        else datetime.min.replace(tzinfo=timezone.utc)
    )
    fresh = events.filter(pl.col("timestamp") > last_seen_dt)
    if fresh.height == 0:
        print(f"{day_key} {timeframe}: no new signals (last {last_sent})")
        return

    last_ts: datetime | None = None
    for row in fresh.to_dicts():
        ts: datetime = row["timestamp"]
        direction = row["signal_type"]
        close = float(row["candle_close"])
        side = "LONG" if direction == "BUY" else "SHORT"
        text = (
            f"*{direction} SIGNAL* — NIFTY FUT\n"
            f"{timeframe} | {ts.strftime('%d %b %H:%M')} | {direction}\n"
            f"Close: INR {close:,.2f} | side: {side}"
        )
        send_telegram(_bot_token(), _chat_id(), text, dry_run=dry_run)
        last_ts = ts

    if last_ts is not None:
        day_state[timeframe] = last_ts.isoformat()
        state[day_key] = day_state
        _save_state(state)
        print(f"sent {fresh.height} signal(s); state updated to {last_ts.isoformat()}")


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--once", action="store_true", help="single check then exit")
    parser.add_argument("--interval", type=int, default=300, help="poll interval seconds")
    parser.add_argument("--no-send", action="store_true", help="dry run (print, never send)")
    parser.add_argument("--timeframe", default="5m")
    parser.add_argument("--fast-ema", type=int, default=9)
    parser.add_argument("--slow-ema", type=int, default=15)
    parser.add_argument("--angle-threshold", type=float, default=30.0)
    parser.add_argument("--angle-lookback", type=int, default=1)
    parser.add_argument("--signal-mode", default="crossover_and_angle")
    parser.add_argument(
        "--min-bars", type=int, default=20, help="min bars before evaluating"
    )
    args = parser.parse_args()

    if not _bot_token() and not args.no_send:
        print(
            "TELEGRAM_BOT_TOKEN not set — add to .env or run with --no-send "
            "(this would be a dry run)",
            file=sys.stderr,
        )

    common = dict(
        dry_run=args.no_send,
        timeframe=args.timeframe,
        fast_ema=args.fast_ema,
        slow_ema=args.slow_ema,
        angle_threshold=args.angle_threshold,
        angle_lookback=args.angle_lookback,
        signal_mode=args.signal_mode,
        min_bars=args.min_bars,
    )
    if args.once:
        check_once(**common)
        return
    print(f"polling every {args.interval}s (Ctrl-C to stop)")
    while True:
        try:
            check_once(**common)
        except Exception as exc:  # noqa: BLE001 - alert loop must keep polling
            print(f"check failed: {exc}", file=sys.stderr)
        time.sleep(args.interval)


if __name__ == "__main__":
    main()
