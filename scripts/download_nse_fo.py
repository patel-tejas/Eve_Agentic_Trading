"""Download NSE F&O bhavcopy (NIFTY rows) or participant-wise OI.

    python scripts/download_nse_fo.py --kind bhav        --start 2016-01-01 --end 2026-09-25
    python scripts/download_nse_fo.py --kind participant --start 2012-01-01 --end 2026-09-25

Resumable: every date gets one line in ``_manifest.jsonl``; dates already
marked ``ok`` or ``missing`` (no file on either URL -- a holiday) are
skipped on re-run, and ``error`` dates are retried. Only NIFTY rows of the
bhavcopy are kept (as raw text, so parsing can be fixed and re-run without
re-downloading); participant files are kept verbatim.
"""

from __future__ import annotations

import argparse
import json
import sys
import time
from datetime import date, datetime, timedelta
from pathlib import Path

import httpx

from quant.data.nse_archive import HEADERS, bhav_urls, nifty_rows, participant_oi_url

ROOT = Path("data/raw/nse")
PACE_S = 0.35
BACKOFF_S = (3, 8, 20)


def _weekdays(start: date, end: date):
    d = start
    while d <= end:
        if d.weekday() < 5:
            yield d
        d += timedelta(days=1)


def _load_manifest(path: Path) -> dict[str, dict]:
    done: dict[str, dict] = {}
    if path.exists():
        for line in path.read_text(encoding="utf-8").splitlines():
            if line.strip():
                rec = json.loads(line)
                done[rec["date"]] = rec
    return done


def _get(client: httpx.Client, url: str) -> tuple[int, bytes]:
    """GET with retries on transport errors, 429 and 5xx. Returns (code, body)."""
    for attempt in range(len(BACKOFF_S) + 1):
        try:
            r = client.get(url)
            if r.status_code in (429,) or r.status_code >= 500:
                raise httpx.HTTPStatusError("retryable", request=r.request, response=r)
            return r.status_code, r.content
        except (httpx.TransportError, httpx.HTTPStatusError):
            if attempt == len(BACKOFF_S):
                return -1, b""
            time.sleep(BACKOFF_S[attempt])
    return -1, b""


def fetch_bhav(client: httpx.Client, d: date, out_dir: Path) -> dict:
    codes = []
    for fmt, url in bhav_urls(d):
        code, body = _get(client, url)
        codes.append(code)
        time.sleep(PACE_S)
        if code == 200 and body[:2] == b"PK":
            raw = nifty_rows(body, fmt)
            dest = out_dir / f"{d.year}" / f"{d:%Y%m%d}_raw.parquet"
            dest.parent.mkdir(parents=True, exist_ok=True)
            raw.write_parquet(dest)
            return {"status": "ok", "format": fmt, "url": url, "rows": len(raw), "bytes": len(body)}
    status = "missing" if all(c == 404 for c in codes) else "error"
    return {"status": status, "codes": codes}


def fetch_participant(client: httpx.Client, d: date, out_dir: Path) -> dict:
    url = participant_oi_url(d)
    code, body = _get(client, url)
    time.sleep(PACE_S)
    text = body.decode("utf-8", errors="replace") if code == 200 else ""
    if code == 200 and "Client" in text or code == 200 and "CLIENT" in text:
        dest = out_dir / f"{d.year}" / f"{d:%Y%m%d}.csv"
        dest.parent.mkdir(parents=True, exist_ok=True)
        dest.write_text(text, encoding="utf-8")
        return {"status": "ok", "url": url, "bytes": len(body)}
    return {"status": "missing" if code == 404 else "error", "codes": [code]}


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--kind", choices=["bhav", "participant"], required=True)
    ap.add_argument("--start", type=date.fromisoformat, required=True)
    ap.add_argument("--end", type=date.fromisoformat, required=True)
    args = ap.parse_args()

    out_dir = ROOT / ("fo_bhav" if args.kind == "bhav" else "participant_oi")
    out_dir.mkdir(parents=True, exist_ok=True)
    manifest_path = out_dir / "_manifest.jsonl"
    done = _load_manifest(manifest_path)
    fetch = fetch_bhav if args.kind == "bhav" else fetch_participant

    todo = [
        d
        for d in _weekdays(args.start, args.end)
        if done.get(d.isoformat(), {}).get("status") not in ("ok", "missing")
    ]
    print(f"{args.kind}: {len(todo)} dates to fetch ({len(done)} already in manifest)", flush=True)

    counts = {"ok": 0, "missing": 0, "error": 0}
    consecutive_errors = 0
    with (
        httpx.Client(headers=HEADERS, timeout=30.0, follow_redirects=True) as client,
        manifest_path.open("a", encoding="utf-8") as mf,
    ):
        for i, d in enumerate(todo, 1):
            rec = fetch(client, d, out_dir)
            rec.update(
                {"date": d.isoformat(), "fetched_at": datetime.now().isoformat(timespec="seconds")}
            )
            mf.write(json.dumps(rec) + "\n")
            mf.flush()
            counts[rec["status"]] += 1
            consecutive_errors = consecutive_errors + 1 if rec["status"] == "error" else 0
            if consecutive_errors == 10:
                print(f"  10 consecutive errors at {d}; cooling down 120s", flush=True)
                time.sleep(120)
            if consecutive_errors >= 30:
                print(f"  30 consecutive errors at {d}; stopping (re-run to resume)", flush=True)
                return 2
            if i % 50 == 0 or i == len(todo):
                print(
                    f"  [{i}/{len(todo)}] {d}  ok={counts['ok']} missing={counts['missing']} "
                    f"error={counts['error']}",
                    flush=True,
                )
    return 0


if __name__ == "__main__":
    sys.exit(main())
