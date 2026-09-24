#!/usr/bin/env python3
"""T406 raw-first GMO collector.

Integrity-only acquisition. This program MUST NOT calculate candidate returns,
PnL, hit rate, Sharpe, event counts, signal thresholds, or pass/fail performance.
It preserves exact successful HTTP response bodies plus request/acquisition provenance.
Collector revision: v1.0.2.
"""
from __future__ import annotations

import argparse
import hashlib
import json
import time
import urllib.parse
import urllib.request
from datetime import datetime, timezone
from pathlib import Path

BASE = "https://api.coin.z.com/public/v1/trades"
SYMBOLS = ("BTC_JPY", "ETH_JPY")
UA = "method-x-t406-raw-integrity/1.0"


def utc_now() -> str:
    return datetime.now(timezone.utc).isoformat().replace("+00:00", "Z")


def get_raw(symbol: str, page: int, count: int, timeout: int = 20) -> tuple[bytes, str]:
    q = urllib.parse.urlencode({"symbol": symbol, "page": page, "count": count})
    url = f"{BASE}?{q}"
    req = urllib.request.Request(url, headers={"User-Agent": UA, "Accept": "application/json"})
    with urllib.request.urlopen(req, timeout=timeout) as r:
        return r.read(), url


def validate_envelope(raw: bytes) -> None:
    obj = json.loads(raw)
    if obj.get("status") != 0:
        raise RuntimeError(f"GMO status != 0: {obj.get('status')}")
    if not isinstance(obj.get("data", {}).get("list"), list):
        raise RuntimeError("GMO schema sentinel failed: data.list missing")
    for row in obj["data"]["list"]:
        if not all(k in row for k in ("price", "side", "size", "timestamp")):
            raise RuntimeError("GMO schema sentinel failed: trade field missing")


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("--out", default="out/t406-gmo-raw")
    ap.add_argument("--duration-seconds", type=int, default=14700)
    ap.add_argument("--poll-seconds", type=float, default=10.0)
    ap.add_argument("--pages", type=int, default=10)
    ap.add_argument("--count", type=int, default=100)
    ap.add_argument("--request-spacing", type=float, default=0.5)
    ap.add_argument("--max-retries", type=int, default=5)
    args = ap.parse_args()

    out = Path(args.out)
    rawdir = out / "raw"
    rawdir.mkdir(parents=True, exist_ok=True)
    manifest = out / "manifest.ndjson"
    errors = out / "errors.ndjson"
    run_started = utc_now()
    deadline = time.monotonic() + args.duration_seconds
    seq = 0
    request_attempts = 0
    retry_events = 0
    terminal_errors = 0

    with manifest.open("a", encoding="utf-8") as mf, errors.open("a", encoding="utf-8") as ef:
        while time.monotonic() < deadline:
            cycle_start = time.monotonic()
            for symbol in SYMBOLS:
                for page in range(1, args.pages + 1):
                    if time.monotonic() >= deadline:
                        break
                    success = False
                    for attempt in range(1, args.max_retries + 1):
                        acquired = utc_now()
                        request_attempts += 1
                        try:
                            raw, url = get_raw(symbol, page, args.count)
                            validate_envelope(raw)
                            sha = hashlib.sha256(raw).hexdigest()
                            name = f"{seq:09d}_{symbol}_p{page}_{sha[:16]}.json"
                            (rawdir / name).write_bytes(raw)
                            rec = {"seq": seq, "symbol": symbol, "page": page, "request_url": url,
                                   "acquired_at_utc": acquired, "sha256": sha, "bytes": len(raw),
                                   "file": f"raw/{name}", "collector": "t406_gmo_raw_acquire.py/v1.0.2",
                                   "attempt": attempt}
                            mf.write(json.dumps(rec, separators=(",", ":")) + "\n")
                            mf.flush()
                            seq += 1
                            success = True
                            break
                        except Exception as exc:
                            retry_events += 1
                            ef.write(json.dumps({"at_utc": acquired, "symbol": symbol, "page": page,
                                                 "attempt": attempt, "error": type(exc).__name__,
                                                 "detail": str(exc)[:500]}, separators=(",", ":")) + "\n")
                            ef.flush()
                            if attempt < args.max_retries:
                                time.sleep(min(8.0, 0.75 * (2 ** (attempt - 1))))
                        finally:
                            time.sleep(args.request_spacing)
                    if not success:
                        terminal_errors += 1
            time.sleep(max(0.0, args.poll_seconds - (time.monotonic() - cycle_start)))

    summary = {"trial_id": "T406", "purpose": "raw_integrity_only", "run_started_utc": run_started,
               "run_finished_utc": utc_now(), "symbols": list(SYMBOLS), "pages_per_poll": args.pages,
               "count_per_page": args.count, "poll_seconds_target": args.poll_seconds,
               "request_spacing_seconds": args.request_spacing, "max_retries": args.max_retries,
               "request_attempts": request_attempts, "retry_events": retry_events,
               "terminal_errors": terminal_errors, "performance_statistics_computed": False,
               "manifest_sha256": hashlib.sha256(manifest.read_bytes()).hexdigest(),
               "manifest_bytes": manifest.stat().st_size, "raw_file_count": seq}
    (out / "run-summary.json").write_text(json.dumps(summary, indent=2) + "\n", encoding="utf-8")


if __name__ == "__main__":
    main()
